"""dashboard/pages/evolucion.py — Evolución del mercado: cuentas, prestadores, velocidades."""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html, register_page

from components.filters_shared import (
    register_shared_filters_callbacks,
    register_universal_opera_isp_sync,
    shared_filters_layout,
)
from components.territory_filters import (
    register_territory_callbacks,
    seleccion_desde_territorio,
    territory_filter_layout,
)
from components.ui import (
    OKABE_ITO,
    PALETTE,
    build_linked_magnitude_variation_figure,
    build_sparkline_figure,
    chart_card,
    clean_records,
    empty_figure,
    error_panel,
    excel_download_button,
    filters_summary_bar,
    format_number,
    format_signed,
    kpi_card,
    month_year_picker,
    page_header,
    register_excel_download_callback,
    register_filters_summary_callback,
    register_month_year_picker_callback,
    register_shared_period_sync,
    style_figure,
)
from services.queries import (
    get_churn_history,
    get_desglose_territorial,
    get_evolution_filtrado,
    get_periods,
    get_prestadores_nunca_reportaron_detalle,
    get_provider_count_in_range,
    get_reporting_summary,
    get_velocities,
)

register_page(__name__, path="/sai/evolucion", name="Evolución", order=1)
PREFIX = "evo"


def _period_options():
    periods = get_periods()
    if periods.empty:
        raise RuntimeError("mart.dim_periodo no contiene registros.")
    options = [{"label": row.anio_mes, "value": int(row.periodo_id)} for row in periods.itertuples()]
    min_period = int(periods["periodo_id"].min())
    max_period = int(periods["periodo_id"].max())
    return options, min_period, max_period


def layout():
    try:
        _, min_period, max_period = _period_options()
    except Exception as exc:
        return html.Div([page_header("Evolución del mercado", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Evolución del mercado",
                "Cuentas reportadas, prestadores y cambios en la composición por velocidad.",
            ),
            html.Section(
                className="filter-panel",
                children=[
                    territory_filter_layout(PREFIX),
                    html.Div(
                        className="period-grid four-periods",
                        children=[
                            month_year_picker("evo-start-period", "Desde", min_period, min_period, max_period),
                            month_year_picker("evo-end-period", "Hasta", max_period, min_period, max_period),
                        ],
                    ),
                    shared_filters_layout(PREFIX),
                    html.Div(
                        className="filter-field",
                        style={"marginTop": "14px", "maxWidth": "260px"},
                        children=[
                            html.Label("Velocidad"),
                            dcc.RadioItems(
                                id="evo-speed-type",
                                options=[
                                    {"label": "Descarga", "value": "DESCARGA"},
                                    {"label": "Subida", "value": "SUBIDA"},
                                ],
                                value="DESCARGA",
                                inline=True,
                                className="radio-group",
                            ),
                        ],
                    ),
                ],
            ),
            filters_summary_bar("evo-filters-summary"),
            html.Div(id="evo-message", className="data-message"),
            html.H3(id="evo-titulo-estado-actual", children="Estado actual"),
            html.Section(
                className="kpi-grid four",
                children=[
                    kpi_card("Cuentas reportadas (último período)", "evo-kpi-lines", "evo-kpi-lines-note"),
                    kpi_card("Prestadores que reportaron", "evo-kpi-providers", "evo-kpi-providers-note"),
                    kpi_card("Cambio mensual (reportadas)", "evo-kpi-change", "evo-kpi-change-note"),
                    kpi_card("Dejaron de reportar este mes", "evo-kpi-churn", "evo-kpi-churn-note",
                             "evo-kpi-churn-spark"),
                ],
            ),
            html.H3(id="evo-titulo-resumen-rango", children="Resumen del rango seleccionado"),
            html.Section(
                className="kpi-grid four",
                children=[
                    kpi_card("Prestadores con actividad en el rango", "evo-kpi-rango-prestadores",
                             "evo-kpi-rango-prestadores-note"),
                    kpi_card("Total de prestadores (con o sin reportes)", "evo-kpi-rango-total",
                             "evo-kpi-rango-total-note"),
                    kpi_card("Tasa de entrega de reportes", "evo-kpi-rango-tasa",
                             "evo-kpi-rango-tasa-note"),
                    kpi_card("Nunca han reportado", "evo-kpi-nunca-reportaron",
                             "evo-kpi-nunca-reportaron-note"),
                ],
            ),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card("Cuentas reportadas por mes", "evo-lines-combined-chart",
                               "Arriba: magnitud, solo lo reportado (sin imputación). Abajo: variación % "
                               "respecto al mes anterior, mismo eje de tiempo. Una caída puede ser falta de "
                               "reporte: compárela con la cobertura del gráfico de prestadores."),
                    chart_card("Prestadores que reportaron", "evo-providers-combined-chart",
                               "Arriba: prestadores con reporte cada mes; la línea punteada son los "
                               "esperados (cobertura en el hover). Abajo: variación % respecto al mes anterior."),
                ],
            ),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card("Composición por velocidad", "evo-speed-composition-chart",
                               "Distribución mensual por rango de velocidad, solo cuentas reportadas."),
                    chart_card("Diferencia mensual por velocidad", "evo-speed-difference-chart",
                               "Cambio absoluto frente al mes anterior para el último período visible."),
                ],
            ),
            html.H3(id="evo-desglose-titulo", children="Cuentas por territorio", style={"marginTop": "28px"}),
            html.Section(
                className="chart-grid",
                children=[
                    chart_card(
                        "Cuentas reportadas por territorio", "evo-desglose-chart",
                        "Un nivel más abajo del territorio elegido, en el último período visible. Haga clic en "
                        "una barra (o en una fila de la tabla) para bajar a ese territorio.",
                    ),
                ],
            ),
            html.Section(
                className="table-card",
                children=[
                    html.Div(
                        className="chart-header",
                        children=[
                            html.H3("Detalle por territorio", className="chart-title"),
                            html.P(
                                "Solo cuentas reportadas (sin imputación). Lea las cuentas junto a la cobertura: "
                                "un territorio donde falta el reporte de su prestador principal aparece con "
                                "pocas cuentas y cobertura baja. Las cuentas de los territorios suman el total "
                                "(incluida 'Sin geografía asignada', si existe); los prestadores no, porque un "
                                "prestador puede operar en varios.",
                                className="chart-subtitle",
                            ),
                        ],
                    ),
                    dag.AgGrid(
                        id="evo-desglose-grid",
                        columnDefs=[
                            {"field": "territorio", "headerName": "Territorio", "minWidth": 220, "flex": 2},
                            {"field": "cuentas", "headerName": "Cuentas", "type": "numericColumn",
                             "minWidth": 120},
                            {"field": "porcentaje_del_total", "headerName": "% del total",
                             "type": "numericColumn", "minWidth": 110},
                            {"field": "cuentas_mes_anterior", "headerName": "Cuentas (mes anterior)",
                             "type": "numericColumn", "minWidth": 150},
                            {"field": "diferencia", "headerName": "Diferencia", "type": "numericColumn",
                             "minWidth": 120},
                            {"field": "variacion_porcentaje", "headerName": "Variación %",
                             "type": "numericColumn", "minWidth": 120},
                            {"field": "prestadores_reportaron", "headerName": "Prestadores que reportaron",
                             "type": "numericColumn", "minWidth": 170},
                            {"field": "prestadores_esperados", "headerName": "Prestadores esperados",
                             "type": "numericColumn", "minWidth": 150},
                            {"field": "porcentaje_cobertura", "headerName": "Cobertura %",
                             "type": "numericColumn", "minWidth": 120},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 15,
                                         "animateRows": True},
                        # rowId = territorio_id: identifica la fila del clic aunque el
                        # usuario haya ordenado o paginado la tabla.
                        getRowId="params.data.territorio_id || 'SIN_GEOGRAFIA'",
                        columnSize="responsiveSizeToFit",
                        className="ag-theme-balham",
                    ),
                    excel_download_button("evo-desglose-grid"),
                ],
            ),
        ]
    )


register_territory_callbacks(PREFIX)
register_shared_filters_callbacks(PREFIX)
register_universal_opera_isp_sync(PREFIX)
register_month_year_picker_callback("evo-start-period")
register_month_year_picker_callback("evo-end-period")
register_shared_period_sync("evo-start-period", "evo-end-period")
register_filters_summary_callback(PREFIX)
register_excel_download_callback("evo-desglose-grid", "cuentas_por_territorio.xlsx")

NOMBRE_NIVEL_HIJO = {"NACIONAL": "provincia", "PROVINCIA": "cantón", "CANTON": "parroquia"}
COLUMNAS_DESGLOSE = [
    "territorio_id", "territorio", "cuentas", "porcentaje_del_total", "cuentas_mes_anterior", "diferencia",
    "variacion_porcentaje", "prestadores_reportaron", "prestadores_esperados", "porcentaje_cobertura",
]


@callback(
    Output("evo-kpi-lines", "children"),
    Output("evo-kpi-lines-note", "children"),
    Output("evo-kpi-providers", "children"),
    Output("evo-kpi-providers-note", "children"),
    Output("evo-kpi-change", "children"),
    Output("evo-kpi-change-note", "children"),
    Output("evo-kpi-churn", "children"),
    Output("evo-kpi-churn-note", "children"),
    Output("evo-kpi-churn-spark", "figure"),
    Output("evo-lines-combined-chart", "figure"),
    Output("evo-providers-combined-chart", "figure"),
    Output("evo-speed-composition-chart", "figure"),
    Output("evo-speed-difference-chart", "figure"),
    Output("evo-message", "children"),
    Output("evo-titulo-estado-actual", "children"),
    Output("evo-titulo-resumen-rango", "children"),
    Output("evo-kpi-rango-prestadores", "children"),
    Output("evo-kpi-rango-prestadores-note", "children"),
    Output("evo-kpi-rango-total", "children"),
    Output("evo-kpi-rango-total-note", "children"),
    Output("evo-kpi-rango-tasa", "children"),
    Output("evo-kpi-rango-tasa-note", "children"),
    Output("evo-kpi-nunca-reportaron", "children"),
    Output("evo-kpi-nunca-reportaron-note", "children"),
    Input("evo-territory-id", "data"),
    Input("evo-start-period", "data"),
    Input("evo-end-period", "data"),
    Input("evo-speed-type", "value"),
    Input("evo-opera-estado", "value"),
    Input("evo-isp-nombre", "value"),
)
def update_evolution(
        territory_id: str,
        start_period: int | None,
        end_period: int | None,
        speed_type: str,
        opera_estados: list[str] | None,
        isp_nombres: list[str] | None,
):
    opera_estados = opera_estados or []
    isp_nombres = isp_nombres or []

    if not territory_id or start_period is None or end_period is None:
        figures = [empty_figure("Seleccione todos los filtros") for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", empty_figure(), *figures, "", "Estado actual",
                "Resumen del rango seleccionado", "—", "", "—", "", "—", "", "—", "")

    start_period, end_period = sorted((int(start_period), int(end_period)))

    try:
        evolution = get_evolution_filtrado(territory_id, start_period, end_period, opera_estados, isp_nombres)
        velocities = get_velocities(territory_id, start_period, end_period, speed_type, opera_estados, isp_nombres)
    except Exception as exc:
        figures = [empty_figure("Error al consultar PostgreSQL") for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", empty_figure(), *figures, str(exc), "Estado actual",
                "Resumen del rango seleccionado", "—", "", "—", "", "—", "", "—", "")

    if evolution.empty:
        figures = [empty_figure() for _ in range(4)]
        return ("—", "", "—", "", "—", "", "—", "", empty_figure(), *figures,
                "No existen datos para este territorio, período y filtros seleccionados.",
                "Estado actual", "Resumen del rango seleccionado", "—", "", "—", "", "—", "", "—", "")

    evolution = evolution.copy()
    evolution["periodo"] = pd.to_datetime(evolution["periodo"])
    numeric_columns = [
        "total_lineas", "numero_prestadores", "numero_prestadores_esperados",
        "porcentaje_cobertura_prestadores", "diferencia_mensual_lineas", "variacion_mensual_porcentaje",
    ]
    for column in numeric_columns:
        if column in evolution:
            evolution[column] = pd.to_numeric(evolution[column], errors="coerce")

    latest = evolution.sort_values("periodo_id").iloc[-1]
    latest_label = str(latest.get("anio_mes", ""))

    lines_value = format_number(latest.get("total_lineas"))
    lines_note = f"Período {latest_label}"

    providers_value = format_number(latest.get("numero_prestadores"))
    providers_note = (
        f"De {format_number(latest.get('numero_prestadores_esperados'))} esperados en {latest_label} "
        f"(cobertura {format_number(latest.get('porcentaje_cobertura_prestadores'), 1)}%)"
    )

    # La variación compara dos meses con coberturas posiblemente distintas
    # -- se muestran ambas para que una caída por falta de reporte no se lea
    # como caída del mercado.
    evolution_por_periodo = evolution.sort_values("periodo_id")
    cobertura_anterior = (
        evolution_por_periodo.iloc[-2]["porcentaje_cobertura_prestadores"] if len(evolution_por_periodo) > 1 else None
    )
    change_value = format_signed(latest.get("diferencia_mensual_lineas"))
    change_note = (
        f"{format_signed(latest.get('variacion_mensual_porcentaje'), 2, '%')} respecto al mes anterior · "
        f"cobertura {format_number(latest.get('porcentaje_cobertura_prestadores'), 1)}% vs. "
        f"{format_number(cobertura_anterior, 1)}%"
    )

    # "Dejaron de reportar este mes" y su sparkline salen de la MISMA serie
    # (get_churn_history, misma definición que Control): activos = reportaron
    # con al menos una cuenta; el valor puntual es la última fila. Respeta
    # los filtros de Estado/Prestador, igual que el resto de la fila.
    churn_value, churn_note, churn_spark = "—", "", empty_figure()
    try:
        periodo_actual_id = int(latest["periodo_id"])
        churn_hist = get_churn_history(territory_id, periodo_actual_id, 12, opera_estados, isp_nombres)
        fila_actual = churn_hist[churn_hist["periodo_id"] == periodo_actual_id]
        if not fila_actual.empty:
            churn_value = format_number(fila_actual.iloc[0]["churn"])
            churn_note = f"De {format_number(fila_actual.iloc[0]['activos_mes_anterior'])} activos en el mes anterior"
        churn_spark = build_sparkline_figure(
            pd.to_numeric(churn_hist["churn"], errors="coerce").tolist(), PALETTE["red"],
        )
    except Exception:
        churn_value, churn_note, churn_spark = "—", "No se pudo calcular", empty_figure()

    evolution_ordenada = evolution.sort_values("periodo")

    # Un solo gráfico combinado por métrica (magnitud + variación, eje X
    # compartido, hover unificado) en vez de dos dcc.Graph sueltos -- a
    # pedido del usuario (14-ago-2026), ver
    # components/ui.py:build_linked_magnitude_variation_figure(). Sin
    # consulta nueva a PostgreSQL: "evolution" solo trae lo reportado (el
    # mart no tiene imputación), así que pct_change() directo sobre esa
    # serie es consistente con la metodología del proyecto.
    lines_variacion_pct = (
            evolution_ordenada["total_lineas"].pct_change().replace([float("inf"), float("-inf")],
                                                                    float("nan")) * 100
    )
    lines_combined_fig = build_linked_magnitude_variation_figure(
        evolution_ordenada["periodo"], evolution_ordenada["total_lineas"], lines_variacion_pct,
        titulo_magnitud="Cuentas reportadas", titulo_variacion="Variación % (escala log, signo preservado)",
        etiqueta_absoluta="cuentas", color=PALETTE["blue"], rellenar_area=True,
    )

    providers_variacion_pct = (
            evolution_ordenada["numero_prestadores"].pct_change().replace([float("inf"), float("-inf")],
                                                                          float("nan")) * 100
    )
    providers_combined_fig = build_linked_magnitude_variation_figure(
        evolution_ordenada["periodo"], evolution_ordenada["numero_prestadores"], providers_variacion_pct,
        titulo_magnitud="Prestadores", titulo_variacion="Variación % (escala log, signo preservado)",
        etiqueta_absoluta="prestadores", color=PALETTE["blue"], rellenar_area=False,
    )
    # Esperados (panel de obligación) en el mismo panel superior: la
    # distancia entre las dos líneas es la falta de reporte de ese mes.
    providers_combined_fig.add_trace(
        go.Scatter(
            x=evolution_ordenada["periodo"], y=evolution_ordenada["numero_prestadores_esperados"],
            mode="lines", name="Esperados", line={"color": PALETTE["muted"], "width": 1.6, "dash": "dash"},
            customdata=evolution_ordenada["porcentaje_cobertura_prestadores"],
            hovertemplate="Esperados: %{y:,.0f} · cobertura %{customdata:.1f}%<extra></extra>",
            showlegend=False,
        ),
        row=1, col=1,
    )

    if velocities.empty:
        speed_comp_fig = empty_figure("No existen datos de velocidad")
        speed_diff_fig = empty_figure("No existen diferencias de velocidad")
    else:
        velocities = velocities.copy()
        velocities["periodo"] = pd.to_datetime(velocities["periodo"])
        velocities["total_lineas"] = pd.to_numeric(velocities["total_lineas"], errors="coerce").fillna(0)
        velocities["diferencia_mensual"] = pd.to_numeric(velocities["diferencia_mensual"], errors="coerce")

        speed_comp_fig = px.area(
            velocities, x="periodo", y="total_lineas", color="rango_velocidad",
            category_orders={
                "rango_velocidad": velocities.sort_values("orden_rango")["rango_velocidad"].drop_duplicates().tolist()
            },
            labels={"total_lineas": "Cuentas", "periodo": "Período", "rango_velocidad": "Rango"},
            # Paleta cualitativa por defecto de Plotly reemplazada por
            # Okabe-Ito -- con 7 categorías simultáneas (rangos de
            # velocidad), el color por defecto no está verificado contra
            # daltonismo; este sí (ver components/ui.py:OKABE_ITO).
            color_discrete_sequence=OKABE_ITO,
        )
        style_figure(speed_comp_fig)
        speed_comp_fig.update_yaxes(tickformat=",")

        latest_speed_period = velocities["periodo_id"].max()
        latest_speed = velocities[velocities["periodo_id"] == latest_speed_period].sort_values("orden_rango")
        speed_diff_fig = go.Figure(
            go.Bar(
                x=latest_speed["rango_velocidad"], y=latest_speed["diferencia_mensual"],
                marker_color=[
                    PALETTE["teal"] if pd.notna(value) and value >= 0 else PALETTE["red"]
                    for value in latest_speed["diferencia_mensual"]
                ],
                hovertemplate="%{x}<br>Diferencia: %{y:,.0f}<extra></extra>",
            )
        )
        style_figure(speed_diff_fig, hovermode="closest")
        speed_diff_fig.update_xaxes(tickangle=-25)
        speed_diff_fig.update_yaxes(title="Diferencia mensual", tickformat=",")

    filtros_txt = []
    if opera_estados:
        filtros_txt.append(f"Estado: {', '.join(opera_estados)}")
    if isp_nombres:
        filtros_txt.append(f"Prestador: {', '.join(isp_nombres)}")
    filtros_sufijo = f" · Filtros: {'; '.join(filtros_txt)}" if filtros_txt else ""
    message = f"Territorio: {territory_id} · Último período visible: {latest_label}{filtros_sufijo}"

    titulo_estado_actual = f"Estado actual — {latest_label}"

    primero = evolution.sort_values("periodo_id").iloc[0]
    rango_desde_label = str(primero.get("anio_mes", ""))
    rango_hasta_label = latest_label
    titulo_resumen_rango = f"Resumen del rango seleccionado — {rango_desde_label} a {rango_hasta_label}"

    try:
        cantidad_rango = get_provider_count_in_range(territory_id, start_period, end_period)
        rango_prestadores_value = format_number(cantidad_rango)
        rango_prestadores_note = (
            f"Con al menos un reporte real entre {rango_desde_label} y {rango_hasta_label}. "
            "En rangos amplios (varios años), este número tiende a coincidir con el total de "
            "prestadores presentes -- casi todos tienen al menos un reporte real en algún punto. "
            "No equivale a título habilitante vigente."
        )
    except Exception:
        rango_prestadores_value, rango_prestadores_note = "—", "No se pudo calcular"

    incluir_nunca = territory_id == "NACIONAL|ECUADOR"
    try:
        resumen = get_reporting_summary(
            territory_id, start_period, end_period, opera_estados, isp_nombres,
            incluir_nunca_reportaron=incluir_nunca,
        )
        rango_total_value = format_number(resumen["total_prestadores"])
        if incluir_nunca:
            rango_total_note = (
                f"Con o sin reportes (incluye a quienes nunca han reportado), "
                f"registrados hasta {rango_hasta_label}."
            )
        else:
            rango_total_note = (
                f"Con al menos un reporte real, registrados hasta {rango_hasta_label}. "
                "No incluye a quienes nunca han reportado -- ese dato solo existe a nivel Nacional."
            )

        tasa = resumen["tasa_entrega_porcentaje"]
        rango_tasa_value = f"{format_number(tasa, 1)}%" if tasa is not None else "—"
        if incluir_nunca:
            rango_tasa_note = (
                f"{format_number(resumen['celdas_reportadas'])} de {format_number(resumen['celdas_esperadas'])} "
                "meses-prestador con reporte real, contados desde que cumplen un año del título "
                "habilitante. INCLUYE a quienes nunca han reportado ni una sola vez -- aportan "
                "meses esperados sin ningún mes entregado, arrastrando la tasa hacia abajo."
            )
        else:
            rango_tasa_note = (
                f"{format_number(resumen['celdas_reportadas'])} de {format_number(resumen['celdas_esperadas'])} "
                "meses-prestador con reporte real, contados desde que cumplen un año del título "
                "habilitante. No incluye a quienes nunca han reportado -- ese dato solo existe a "
                "nivel Nacional."
            )
    except Exception:
        rango_total_value, rango_total_note = "—", "No se pudo calcular"
        rango_tasa_value, rango_tasa_note = "—", "No se pudo calcular"

    if territory_id == "NACIONAL|ECUADOR":
        try:
            # CORRECCIÓN (14-ago-2026, hallazgo #2 del EDA): antes esta
            # tarjeta mostraba get_prestadores_sin_reportar() -- el
            # universo CRUDO de mart.vw_prestadores_sin_reportar (285),
            # sin aplicar ninguna clasificación. Control, en el mismo
            # concepto, sí aplica la clasificación de tres vías
            # (activo_sin_reportar/no_operativo/zona_gris) y muestra 104
            # como "el caso de incumplimiento real" -- mismo dato, dos
            # criterios distintos según la página. Se unifica aquí: esta
            # tarjeta ahora cuenta lo mismo que "Activo sin reportar" en
            # Control (título vigente, opera, cero reportes), no el bruto.
            detalle_nunca = get_prestadores_nunca_reportaron_detalle(tuple(opera_estados), tuple(isp_nombres))
            activo_sin_reportar = int(
                (detalle_nunca["clasificacion_incumplimiento"] == "activo_sin_reportar").sum()
            ) if not detalle_nunca.empty else 0
            nunca_reportaron_value = format_number(activo_sin_reportar)
            nunca_reportaron_note = (
                "Título vigente, opera, cero reportes en toda su historia -- el caso de incumplimiento "
                "real (excluye cancelados/revocados y casos administrativamente ambiguos). Ver Control "
                "para el desglose completo por clasificación."
            )
        except Exception:
            nunca_reportaron_value, nunca_reportaron_note = "—", "No se pudo calcular"
    else:
        nunca_reportaron_value = "Sin datos disponibles"
        nunca_reportaron_note = "Este indicador solo existe a nivel Nacional -- cambie el Nivel geográfico para verlo."

    return (
        lines_value, lines_note,
        providers_value, providers_note,
        change_value, change_note,
        churn_value, churn_note, churn_spark,
        lines_combined_fig, providers_combined_fig, speed_comp_fig, speed_diff_fig,
        message,
        titulo_estado_actual, titulo_resumen_rango,
        rango_prestadores_value, rango_prestadores_note,
        rango_total_value, rango_total_note,
        rango_tasa_value, rango_tasa_note,
        nunca_reportaron_value, nunca_reportaron_note,
    )


@callback(
    Output("evo-desglose-titulo", "children"),
    Output("evo-desglose-chart", "figure"),
    Output("evo-desglose-grid", "rowData"),
    Input("evo-territory-id", "data"),
    Input("evo-start-period", "data"),
    Input("evo-end-period", "data"),
    Input("evo-opera-estado", "value"),
    Input("evo-isp-nombre", "value"),
)
def update_desglose_territorial(territory_id, start_period, end_period, opera_estados, isp_nombres):
    """
    "Cuentas por territorio": un nivel más abajo del territorio elegido, en
    el último período del rango (el mismo "Estado actual" de las tarjetas).
    Ver services/queries.py:get_desglose_territorial().
    """
    if not territory_id or start_period is None or end_period is None:
        return "Cuentas por territorio", empty_figure("Seleccione todos los filtros"), []
    nivel = territory_id.split("|")[0]
    if nivel not in NOMBRE_NIVEL_HIJO:
        return ("Cuentas por territorio", empty_figure("La parroquia es el nivel más detallado disponible."), [])

    periodo_id = max(int(start_period), int(end_period))
    periods = get_periods()
    fila = periods[periods["periodo_id"] == periodo_id]
    etiqueta_periodo = str(fila.iloc[0]["anio_mes"]) if not fila.empty else str(periodo_id)
    titulo = f"Cuentas por {NOMBRE_NIVEL_HIJO[nivel]} — {etiqueta_periodo}"

    try:
        df = get_desglose_territorial(territory_id, periodo_id, opera_estados or [], isp_nombres or [])
    except Exception:
        return titulo, empty_figure("Error al consultar PostgreSQL"), []
    if df.empty or df["cuentas"].fillna(0).sum() == 0:
        return titulo, empty_figure("Sin cuentas reportadas en este período para los filtros elegidos."), []

    for columna in ["porcentaje_del_total", "variacion_porcentaje", "porcentaje_cobertura"]:
        df[columna] = pd.to_numeric(df[columna], errors="coerce").round(2)

    # Barras: solo territorios reales (la fila "Sin geografía asignada" va en
    # la tabla, no se puede profundizar en ella), ordenados por cuentas.
    TOP = 25
    reales = df[~df["es_sin_geografia"].astype(bool)].sort_values("cuentas", ascending=False)
    top = reales.head(TOP).iloc[::-1]
    cobertura_txt = top["porcentaje_cobertura"].map(lambda v: "—" if pd.isna(v) else f"{v:.1f}%")
    fig = go.Figure(go.Bar(
        x=top["cuentas"], y=top["territorio"], orientation="h",
        marker_color=PALETTE["blue"],
        customdata=list(zip(top["territorio_id"], top["porcentaje_del_total"].fillna(0), cobertura_txt,
                            top["prestadores_reportaron"].fillna(0), top["prestadores_esperados"].fillna(0))),
        hovertemplate=(
            "%{y}<br>Cuentas: %{x:,.0f} (%{customdata[1]:.1f}% del total)"
            "<br>Prestadores: %{customdata[3]:,.0f} de %{customdata[4]:,.0f} esperados"
            " · cobertura %{customdata[2]}<extra></extra>"
        ),
    ))
    style_figure(fig, height=max(320, 22 * len(top) + 80), hovermode="closest")
    fig.update_xaxes(title="Cuentas reportadas", tickformat=",")
    fig.update_yaxes(title="")
    if len(reales) > TOP:
        fig.update_layout(title={"text": f"Top {TOP} de {len(reales)} -- la tabla trae todos", "font": {"size": 12}})

    return titulo, fig, clean_records(df[COLUMNAS_DESGLOSE])


@callback(
    Output("shared-territory", "data", allow_duplicate=True),
    Input("evo-desglose-chart", "clickData"),
    Input("evo-desglose-grid", "cellClicked"),
    prevent_initial_call=True,
)
def profundizar_territorio(click_barra, click_celda):
    """
    Clic en una barra o en una fila del desglose = elegir ese territorio en
    el filtro. Escribe el store compartido; la restauración de
    components/territory_filters.py actualiza los selectores (y con ellos
    toda la página, y Concentración si el usuario cambia de pestaña).
    """
    territorio_id = None
    if dash.ctx.triggered_id == "evo-desglose-chart" and click_barra:
        territorio_id = click_barra["points"][0]["customdata"][0]
    elif dash.ctx.triggered_id == "evo-desglose-grid" and click_celda:
        territorio_id = click_celda.get("rowId")
    if not territorio_id or territorio_id == "SIN_GEOGRAFIA":
        return dash.no_update
    return seleccion_desde_territorio(territorio_id)
