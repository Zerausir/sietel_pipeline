"""dashboard/pages/concentracion.py — IHH, participación y concentración de mercado."""
from __future__ import annotations

import dash_ag_grid as dag
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html, no_update, register_page

from components.filters_shared import (
    register_shared_filters_callbacks,
    register_universal_opera_isp_sync,
    shared_filters_layout,
)
from components.territory_filters import register_territory_callbacks, territory_filter_layout
from components.ui import (
    PALETTE,
    build_sparkline_figure,
    chart_card,
    clean_records,
    empty_figure,
    error_panel,
    excel_download_button,
    filters_summary_bar,
    format_number,
    kpi_card,
    month_year_picker,
    page_header,
    periodo_id_to_iso,
    register_excel_download_callback,
    register_filters_summary_callback,
    register_month_year_picker_callback,
    register_shared_period_sync,
    style_figure,
)
from services.queries import (
    get_dependencia_geografica_dominante_ausente,
    get_ihh,
    get_ihh_filtrado,
    get_participation,
    get_participation_filtrado,
    get_periods,
    get_provider_history,
    get_provider_options,
)

register_page(__name__, path="/sai/concentracion", name="IHH y participación", order=2)
PREFIX = "con"


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
        return html.Div([page_header("Concentración de mercado", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Concentración y participación",
                "Evolución histórica del IHH, concentración acumulada y posición de cada prestador, "
                "calculados exclusivamente sobre datos reportados -- sin relleno interior (imputado).",
            ),
            html.Section(
                className="filter-panel",
                children=[
                    territory_filter_layout(PREFIX),
                    html.Div(
                        className="period-grid four-periods",
                        children=[
                            month_year_picker("con-start-period", "Historia desde", min_period, min_period,
                                              max_period),
                            month_year_picker("con-end-period", "Historia hasta", max_period, min_period,
                                              max_period),
                            month_year_picker("con-current-period", "Período de participación", max_period,
                                              min_period, max_period),
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Prestador para evolución"),
                                    dcc.Dropdown(
                                        id="con-provider", options=[], value=None,
                                        placeholder="Seleccione un prestador", clearable=True,
                                    ),
                                ],
                            ),
                        ],
                    ),
                    shared_filters_layout(PREFIX),
                ],
            ),
            filters_summary_bar("con-filters-summary"),
            html.Div(id="con-message", className="data-message"),
            html.Section(
                className="kpi-grid six",
                children=[
                    kpi_card("IHH", "con-kpi-ihh", "con-kpi-ihh-note"),
                    kpi_card("Cobertura del índice", "con-kpi-cobertura", "con-kpi-cobertura-note",
                             "con-kpi-cobertura-spark"),
                    kpi_card("Líder", "con-kpi-leader", "con-kpi-leader-note"),
                    kpi_card("Participación líder", "con-kpi-leader-share", "con-kpi-leader-share-note",
                             "con-kpi-leader-share-spark"),
                    kpi_card("CR2", "con-kpi-cr2", "con-kpi-cr2-note"),
                    kpi_card("CR4", "con-kpi-cr4", "con-kpi-cr4-note"),
                ],
            ),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card("Evolución histórica del IHH", "con-ihh-chart",
                               "Calculado solo sobre prestadores con reporte real cada mes."),
                    chart_card("CR2 y CR4 en el tiempo", "con-cr-chart",
                               "Concentración acumulada de los 2 y 4 principales prestadores -- el IHH resume "
                               "todo el mercado en un número, CR2/CR4 responden una pregunta más concreta: "
                               "¿cuánto controlan los líderes?"),
                ],
            ),
            html.Section(
                className="chart-grid",
                children=[
                    chart_card(
                        "Dependencia geográfica del prestador ausente", "con-dependencia-geografica-chart",
                        "Solo aparece cuando el prestador dominante (Nacional) no reportó en el período de "
                        "participación elegido -- % que representaría su última huella geográfica conocida "
                        "sobre el total actual de cada provincia, si retomara el reporte.",
                    ),
                ],
            ),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card("Participación por prestador", "con-participation-chart",
                               "Principales prestadores del período seleccionado, solo datos reales."),
                    chart_card("Aporte individual al IHH", "con-contribution-chart",
                               "Contribución de cada prestador al índice del mercado."),
                ],
            ),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card("Participación del prestador seleccionado", "con-provider-participation-chart",
                               "Participación %, dentro del territorio seleccionado -- solo datos reales."),
                    chart_card("Cuentas del prestador seleccionado", "con-provider-lines-chart",
                               "Volumen de cuentas reportadas, misma serie que el gráfico de al lado."),
                ],
            ),
            html.Section(
                className="table-card",
                children=[
                    html.Div(
                        className="chart-header",
                        children=[
                            html.H3("Detalle de participación", className="chart-title"),
                            html.P(
                                "Incluye TODOS los prestadores del territorio, incluso quienes no "
                                "reportaron ese mes exacto (columna 'Estado') -- para auditoría de "
                                "cobertura, no solo los que entran en el cálculo del IHH.",
                                className="chart-subtitle",
                            ),
                        ],
                    ),
                    dag.AgGrid(
                        id="con-participation-grid",
                        columnDefs=[
                            {"field": "ranking_prestador", "headerName": "Pos.", "width": 85},
                            {"field": "isp_nombre", "headerName": "Prestador", "minWidth": 260, "flex": 2},
                            {"field": "ruc_limpio", "headerName": "RUC", "minWidth": 150},
                            {"field": "cantidad_peva", "headerName": "PEVA", "width": 95},
                            {"field": "total_lineas_prestador", "headerName": "Cuentas (real + imputado)",
                             "type": "numericColumn", "minWidth": 170},
                            {"field": "lineas_reportadas", "headerName": "Cuentas reportadas",
                             "type": "numericColumn", "minWidth": 150},
                            {"field": "participacion_porcentaje", "headerName": "Participación %",
                             "type": "numericColumn", "minWidth": 150},
                            {"field": "aporte_ihh", "headerName": "Aporte IHH", "type": "numericColumn",
                             "minWidth": 135},
                            {"field": "estado_lineas", "headerName": "Estado", "minWidth": 150},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 10,
                                         "animateRows": True},
                        columnSize="responsiveSizeToFit",
                        style={"height": "560px", "width": "100%"},
                    ),
                    excel_download_button("con-participation-grid"),
                ],
            ),
        ]
    )


register_territory_callbacks(PREFIX)
register_shared_filters_callbacks(PREFIX)
register_universal_opera_isp_sync(PREFIX, lambda: get_provider_options("NACIONAL|ECUADOR"))
register_month_year_picker_callback("con-start-period")
register_month_year_picker_callback("con-end-period")
register_month_year_picker_callback("con-current-period")
register_shared_period_sync("con-start-period", "con-end-period")
register_filters_summary_callback(PREFIX)
register_excel_download_callback("con-participation-grid", "detalle_de_participacion.xlsx")


@callback(
    Output("con-current-period-picker", "value"),
    Input("con-opera-estado", "value"),
    Input("con-isp-nombre", "value"),
    Input("con-territory-id", "data"),
    State("con-start-period", "data"),
    State("con-end-period", "data"),
    prevent_initial_call=True,
)
def auto_ajustar_periodo_participacion(opera_estados, isp_nombres, territory_id, start_period, end_period):
    """
    CORRECCIÓN (20-ago-2026, confirmado con 1000TEL CIA. LTDA.): "Período
    de participación" siempre arrancaba en el ÚLTIMO mes de todo el rango
    histórico, sin importar qué prestador quedara filtrado -- si ese
    prestador dejó de reportar antes del fin del rango (1000TEL: último
    reporte real 2025-09, rango hasta 2025-12), "Participación por
    prestador", "Aporte individual al IHH", "Detalle de participación" y
    el dropdown "Prestador para evolución" se quedaban vacíos sin ninguna
    pista de por qué -- no estaban rotos, el período elegido genuinamente
    no tenía datos para ese filtro.

    Se dispara con Estado/Prestador/Territorio -- SOLO estos tres, nunca
    con el propio "con-current-period" como Input (evita el mismo tipo de
    ciclo real ya corregido antes en este proyecto). Recalcula el ÚLTIMO
    período con datos reales para el filtro vigente y mueve el calendario
    ahí -- si el usuario después elige un período distinto a mano, esa
    elección se respeta hasta el próximo cambio de Estado/Prestador/
    Territorio.
    """
    if not territory_id or start_period is None or end_period is None:
        return no_update
    opera_estados = opera_estados or []
    isp_nombres = isp_nombres or []
    try:
        if opera_estados or isp_nombres:
            df = get_ihh_filtrado(territory_id, int(start_period), int(end_period), opera_estados, isp_nombres)
        else:
            df = get_ihh(territory_id, int(start_period), int(end_period))
    except Exception:
        return no_update
    if df.empty:
        return no_update
    ultimo_periodo_real = int(df["periodo_id"].max())
    return periodo_id_to_iso(ultimo_periodo_real)


@callback(
    Output("con-provider", "options"),
    Output("con-provider", "value"),
    Input("con-territory-id", "data"),
    Input("con-current-period", "data"),
    Input("con-opera-estado", "value"),
    Input("con-isp-nombre", "value"),
)
def update_provider_options(territory_id: str, period_id: int, opera_estados: list[str] | None,
                            isp_nombres: list[str] | None):
    if not territory_id or period_id is None:
        return [], None
    opera_estados = opera_estados or []
    isp_nombres = isp_nombres or []
    try:
        if opera_estados or isp_nombres:
            df = get_participation_filtrado(territory_id, int(period_id), opera_estados, isp_nombres)
        else:
            df = get_participation(territory_id, int(period_id))
    except Exception:
        return [], None
    if df.empty:
        return [], None

    df = df.copy()
    df["provider_label"] = df["isp_nombre"].fillna(df["nombrecomercial"]).fillna(df["prestador_id"])
    options = [{"label": str(row.provider_label), "value": str(row.prestador_id)} for row in df.itertuples()]
    positive = df[pd.to_numeric(df["lineas_reportadas"], errors="coerce").fillna(0) > 0]
    selected = str(positive.iloc[0]["prestador_id"]) if not positive.empty else str(df.iloc[0]["prestador_id"])
    return options, selected


@callback(
    Output("con-kpi-ihh", "children"),
    Output("con-kpi-ihh-note", "children"),
    Output("con-kpi-cobertura", "children"),
    Output("con-kpi-cobertura-note", "children"),
    Output("con-kpi-cobertura-spark", "figure"),
    Output("con-kpi-leader", "children"),
    Output("con-kpi-leader-note", "children"),
    Output("con-kpi-leader-share", "children"),
    Output("con-kpi-leader-share-note", "children"),
    Output("con-kpi-leader-share-spark", "figure"),
    Output("con-kpi-cr2", "children"),
    Output("con-kpi-cr2-note", "children"),
    Output("con-kpi-cr4", "children"),
    Output("con-kpi-cr4-note", "children"),
    Output("con-ihh-chart", "figure"),
    Output("con-dependencia-geografica-chart", "figure"),
    Output("con-cr-chart", "figure"),
    Output("con-participation-chart", "figure"),
    Output("con-contribution-chart", "figure"),
    Output("con-participation-grid", "rowData"),
    Output("con-message", "children"),
    Input("con-territory-id", "data"),
    Input("con-start-period", "data"),
    Input("con-end-period", "data"),
    Input("con-current-period", "data"),
    Input("con-opera-estado", "value"),
    Input("con-isp-nombre", "value"),
)
def update_concentration(
        territory_id: str,
        start_period: int | None,
        end_period: int | None,
        current_period: int | None,
        opera_estados: list[str] | None,
        isp_nombres: list[str] | None,
):
    opera_estados = opera_estados or []
    isp_nombres = isp_nombres or []

    empty_figures = [empty_figure() for _ in range(5)]
    empty_spark = empty_figure()
    empty_return = (
        "—", "", "—", "", empty_spark, "—", "", "—", "", empty_spark, "—", "", "—", "",
        empty_figures[0], empty_figures[1], empty_figures[2], empty_figures[3], empty_figures[4],
        [], "",
    )
    if not territory_id or None in (start_period, end_period, current_period):
        return empty_return

    start_period, end_period = sorted((int(start_period), int(end_period)))
    current_period = int(current_period)
    hay_filtros = bool(opera_estados) or bool(isp_nombres)

    try:
        if hay_filtros:
            ihh = get_ihh_filtrado(territory_id, start_period, end_period, opera_estados, isp_nombres)
            participation = get_participation_filtrado(territory_id, current_period, opera_estados, isp_nombres)
        else:
            ihh = get_ihh(territory_id, start_period, end_period)
            participation = get_participation(territory_id, current_period)
    except Exception as exc:
        values = list(empty_return)
        values[-1] = str(exc)
        return tuple(values)

    if not ihh.empty and "prestador_dominante_ausente" not in ihh.columns:
        # CORRECCIÓN (19-ago-2026): bug real en producción, confirmado con
        # "1000TEL CIA. LTDA." -- get_ihh_filtrado() (recalcula el IHH EN
        # VIVO cuando hay Estado/Prestador elegido) nunca tuvo estas dos
        # columnas -- solo existen en mart.vw_dashboard_ihh, que get_ihh()
        # (sin filtros) sí consulta directamente. El código de abajo las
        # asume presentes sin importar la ruta, y con "hay_filtros=True"
        # lanzaba KeyError, tumbando el callback completo (Dash no
        # actualiza nada cuando un callback falla -- por eso el filtro
        # "parecía" no hacer nada). Además, conceptualmente: una vez que
        # se filtra a un prestador específico, "¿está ausente el
        # prestador dominante del mercado completo?" deja de tener una
        # respuesta clara -- se completan como ausentes por defecto
        # (False) y la sección de dependencia geográfica simplemente no
        # aplica en esta ruta, sin intentar replicar esa lógica en vivo.
        ihh = ihh.copy()
        ihh["prestador_dominante_ausente"] = False
        ihh["prestadores_dominantes_ausentes_nombres"] = None

    if ihh.empty:
        values = list(empty_return)
        values[-1] = "No existen datos de IHH para los filtros seleccionados."
        return tuple(values)

    ihh = ihh.copy()
    ihh["periodo"] = pd.to_datetime(ihh["periodo"])
    for column in [
        "ihh", "numero_prestadores_reportaron", "numero_prestadores_registrados",
        "porcentaje_cobertura_prestadores", "participacion_lider", "cr2", "cr4",
    ]:
        if column in ihh:
            ihh[column] = pd.to_numeric(ihh[column], errors="coerce")

    exact = ihh[ihh["periodo_id"] == current_period]
    selected_row = exact.iloc[-1] if not exact.empty else ihh.iloc[-1]
    selected_label = str(selected_row.get("anio_mes", ""))

    leader_name = selected_row.get("prestador_lider_nombre")
    if pd.isna(leader_name) or not leader_name:
        leader_name = selected_row.get("prestador_lider_nombrecomercial")
    leader_name = leader_name if pd.notna(leader_name) and leader_name else "—"

    ihh_value = format_number(selected_row.get("ihh"), 1)
    ihh_note = (
        f"Período {selected_label} · Calculado exclusivamente sobre cuentas reportadas (dato real) -- "
        "ningún prestador sin reporte ese mes entra al cálculo, ni en cero ni con su último valor conocido."
    )

    cobertura = selected_row.get("porcentaje_cobertura_prestadores")
    cobertura_value = f"{format_number(cobertura, 1)}%" if pd.notna(cobertura) else "—"
    cobertura_note = (
        f"{format_number(selected_row.get('numero_prestadores_reportaron'))} de "
        f"{format_number(selected_row.get('numero_prestadores_registrados'))} prestadores registrados "
        f"reportaron este mes -- el IHH de al lado se calculó solo sobre ellos. Una cobertura baja "
        "significa que el índice representa una porción menor del mercado real ese mes."
    )
    # Sparklines: "Cobertura del índice" y "Participación líder" son las
    # dos tarjetas que no tienen ningún gráfico completo en esta página --
    # a diferencia de IHH (tiene su línea de al lado) o CR2/CR4 (tienen el
    # gráfico nuevo de abajo), un número aislado aquí sí era un hueco real
    # de contexto. Reutiliza la serie "ihh" ya calculada arriba -- ninguna
    # consulta nueva.
    cobertura_spark = build_sparkline_figure(ihh["porcentaje_cobertura_prestadores"].tolist(), PALETTE["blue"])
    leader_share_spark = build_sparkline_figure(ihh["participacion_lider"].tolist(), PALETTE["orange"])

    leader_value = str(leader_name)
    leader_note = "Prestador con mayor participación, entre quienes reportaron"
    leader_share_value = f"{format_number(selected_row.get('participacion_lider'), 2)}%"
    leader_share_note = "Participación del principal prestador (sobre el mercado reportado)"
    cr2_value = f"{format_number(selected_row.get('cr2'), 2)}%"
    cr2_note = "Participación conjunta de los dos primeros (sobre el mercado reportado)"
    cr4_value = f"{format_number(selected_row.get('cr4'), 2)}%"
    cr4_note = "Participación conjunta de los cuatro primeros (sobre el mercado reportado)"

    texto_hover_ihh = [
        f"{p.strftime('%Y-%m')}<br>IHH: {v:,.0f}" + (
            f"<br>⚠ {n or 'prestador dominante'} ausente ese mes" if a else ""
        )
        for p, v, a, n in zip(
            ihh["periodo"], ihh["ihh"],
            ihh["prestador_dominante_ausente"].fillna(False),
            ihh["prestadores_dominantes_ausentes_nombres"],
        )
    ]
    ihh_fig = go.Figure()
    ihh_fig.add_trace(
        go.Scatter(
            x=ihh["periodo"], y=ihh["ihh"], mode="lines+markers", name="IHH",
            line={"color": PALETTE["blue"], "width": 3},
            fill="tozeroy", fillcolor="rgba(20, 100, 244, 0.08)",
            text=texto_hover_ihh, hovertemplate="%{text}<extra></extra>",
        )
    )
    style_figure(ihh_fig)
    ihh_fig.update_yaxes(title="IHH", rangemode="tozero")

    # CONEXIÓN (14-ago-2026, hallazgo #1 del EDA, marcado ahí como "el más
    # importante de todo el análisis"): prestador_dominante_ausente ya
    # llegaba al DataFrame de esta página desde hace semanas (get_ihh hace
    # SELECT * sobre mart.vw_dashboard_ihh, que la trae desde el parche #08)
    # -- pero el código de esta página nunca la usaba. Cuando el prestador
    # líder de un territorio (ej. CNT a nivel Nacional) deja de reportar,
    # el IHH cae mecánicamente -- no porque el mercado se volvió más
    # competitivo, sino porque falta quien más pesa. Sin esta marca, ese
    # tramo del gráfico se lee como una mejora real de competencia.
    #
    # SOLO tiene sentido a nivel NACIONAL -- confirmado en sql/08_patch_
    # fact_ihh_geografico.sql: la columna viene forzada a FALSE en
    # cualquier otro nivel geográfico (el concepto de "prestador dominante"
    # está definido y validado solo ahí).
    #
    # CORRECCIÓN (19-ago-2026, a pedido de Iván): se quitó el mensaje de
    # texto bajo el gráfico -- con varios episodios de ausencia en el
    # rango completo (2011-2025), la lista de fechas se volvía una pared
    # de texto poco legible, y mezclaba nombres (CNT junto a COMM & NET
    # S.A., que también cruza el umbral de 30% en algún momento de su
    # historia) sin distinguir cuál pesa más. El sombreado rojo en el
    # gráfico y el aviso en el hover de cada punto se mantienen -- son
    # más discretos y no compiten por atención en una presentación.
    tiene_ausencias = ihh["prestador_dominante_ausente"].fillna(False).astype(bool).any()
    if territory_id == "NACIONAL|ECUADOR" and tiene_ausencias:
        ihh_ordenado = ihh.sort_values("periodo").reset_index(drop=True)
        ausente_serie = ihh_ordenado["prestador_dominante_ausente"].fillna(False).astype(bool)
        # Agrupa períodos CONSECUTIVOS con el mismo valor de "ausente" --
        # cada cambio de valor (False->True o True->False) incrementa el
        # número de grupo; permite mostrar un solo rectángulo sombreado por
        # episodio (ej. "2012-01 a 2015-12"), no un rectángulo por mes.
        grupo = (ausente_serie != ausente_serie.shift()).cumsum()
        rangos = (
            ihh_ordenado.assign(_ausente=ausente_serie, _grupo=grupo)
            .groupby("_grupo")
            .agg(inicio=("periodo", "min"), fin=("periodo", "max"), ausente=("_ausente", "first"))
        )
        rangos = rangos[rangos["ausente"]]

        for _, rango in rangos.iterrows():
            ihh_fig.add_vrect(
                x0=rango["inicio"], x1=rango["fin"] + pd.DateOffset(months=1),
                fillcolor=PALETTE["red"], opacity=0.08, line_width=0,
            )

    # Dependencia geográfica del prestador ausente (hallazgo 9.6 del EDA)
    # -- generaliza el caso CNT (el EDA hardcodeaba su nombre y un período
    # fijo '2024-06-01') a cualquier prestador dominante ausente en el
    # período de PARTICIPACIÓN elegido (current_period, no el rango
    # histórico completo) -- es una foto de un momento específico, no una
    # serie de tiempo. Ver services/queries.py:
    # get_dependencia_geografica_dominante_ausente().
    ausente_periodo_actual = bool(selected_row.get("prestador_dominante_ausente"))
    if territory_id == "NACIONAL|ECUADOR" and ausente_periodo_actual:
        try:
            dependencia = get_dependencia_geografica_dominante_ausente(current_period)
        except Exception:
            dependencia = pd.DataFrame()
        if dependencia.empty:
            dependencia_fig = empty_figure(
                "El prestador ausente no tiene huella geográfica histórica registrada"
            )
        else:
            dependencia = dependencia.sort_values("pct_potencial_subestimado")
            dependencia_fig = go.Figure(go.Bar(
                x=dependencia["pct_potencial_subestimado"], y=dependencia["provincia"], orientation="h",
                marker_color=PALETTE["red"],
                text=dependencia["cuentas_ausente"],
                hovertemplate=(
                    "%{y}<br>Subestimación potencial: %{x}%"
                    "<br>Cuentas del ausente (último reporte): %{text:,.0f}<extra></extra>"
                ),
            ))
            style_figure(dependencia_fig, height=max(280, 24 * len(dependencia)), hovermode="closest")
            dependencia_fig.update_xaxes(title="% potencial de subestimación por provincia")
            dependencia_fig.update_yaxes(title="")
    else:
        motivo = (
            "Este análisis solo aplica a nivel Nacional." if territory_id != "NACIONAL|ECUADOR"
            else "El prestador dominante sí reportó en el período de participación elegido -- nada que mostrar."
        )
        dependencia_fig = empty_figure(motivo)

    # CR2/CR4 en el tiempo -- responde una pregunta que el IHH por sí solo
    # no responde directamente ("¿cuánto controlan específicamente los 2 o
    # 4 principales?"). Un solo eje (0-100%, ambas series son porcentajes
    # de la misma naturaleza) -- no es el caso de doble eje que se evita en
    # otras partes del dashboard, aquí SÍ comparten unidad.
    cr_fig = go.Figure()
    cr_fig.add_trace(go.Scatter(
        x=ihh["periodo"], y=ihh["cr2"], mode="lines", name="CR2", line={"color": PALETTE["blue"], "width": 2.5},
    ))
    cr_fig.add_trace(go.Scatter(
        x=ihh["periodo"], y=ihh["cr4"], mode="lines", name="CR4", line={"color": PALETTE["orange"], "width": 2.5},
    ))
    style_figure(cr_fig)
    cr_fig.update_yaxes(title="Concentración acumulada (%)", rangemode="tozero", range=[0, 100])

    if participation.empty:
        participation_fig = empty_figure("No hay participación para el período seleccionado")
        contribution_fig = empty_figure("No hay aportes al IHH para el período seleccionado")
        grid_rows = []
    else:
        participation = participation.copy()
        participation["provider_label"] = (
            participation["isp_nombre"].fillna(participation["nombrecomercial"]).fillna(participation["prestador_id"])
        )
        for column in [
            "total_lineas_prestador", "lineas_reportadas", "participacion_porcentaje", "aporte_ihh",
            "ranking_prestador",
        ]:
            participation[column] = pd.to_numeric(participation[column], errors="coerce")

        positive = participation[participation["ranking_prestador"].notna()].copy()
        positive = positive.sort_values("participacion_porcentaje", ascending=False)
        top = positive.head(15).sort_values("participacion_porcentaje")

        participation_fig = go.Figure(
            go.Bar(
                x=top["participacion_porcentaje"], y=top["provider_label"], orientation="h",
                marker_color=PALETTE["blue"],
                hovertemplate="%{y}<br>Participación: %{x:.2f}%<extra></extra>",
            )
        )
        style_figure(participation_fig, height=420, hovermode="closest")
        participation_fig.update_xaxes(title="Participación (%, solo reportadas)")
        participation_fig.update_yaxes(title="")

        contribution_top = positive.head(15).sort_values("aporte_ihh")
        contribution_fig = go.Figure(
            go.Bar(
                x=contribution_top["aporte_ihh"], y=contribution_top["provider_label"], orientation="h",
                marker_color=PALETTE["cyan"],
                hovertemplate="%{y}<br>Aporte IHH: %{x:.2f}<extra></extra>",
            )
        )
        style_figure(contribution_fig, height=420, hovermode="closest")
        contribution_fig.update_xaxes(title="Aporte al IHH")
        contribution_fig.update_yaxes(title="")

        grid_columns = [
            "ranking_prestador", "isp_nombre", "ruc_limpio", "cantidad_peva",
            "total_lineas_prestador", "lineas_reportadas", "participacion_porcentaje", "aporte_ihh",
            "estado_lineas",
        ]
        grid_rows = clean_records(participation[grid_columns])

    filtros_txt = []
    if opera_estados:
        filtros_txt.append(f"Estado: {', '.join(opera_estados)}")
    if isp_nombres:
        filtros_txt.append(f"Prestador: {', '.join(isp_nombres)}")
    filtros_sufijo = f" · Filtros: {'; '.join(filtros_txt)}" if filtros_txt else ""
    message = (
        f"Territorio: {territory_id} · "
        f"Período de participación: {selected_label} · "
        f"Cobertura: {cobertura_value}{filtros_sufijo}"
    )

    return (
        ihh_value, ihh_note,
        cobertura_value, cobertura_note, cobertura_spark,
        leader_value, leader_note,
        leader_share_value, leader_share_note, leader_share_spark,
        cr2_value, cr2_note,
        cr4_value, cr4_note,
        ihh_fig, dependencia_fig, cr_fig, participation_fig, contribution_fig,
        grid_rows, message,
    )


@callback(
    Output("con-provider-participation-chart", "figure"),
    Output("con-provider-lines-chart", "figure"),
    Input("con-territory-id", "data"),
    Input("con-provider", "value"),
    Input("con-start-period", "data"),
    Input("con-end-period", "data"),
)
def update_provider_history(territory_id: str, provider_id: str | None, start_period: int | None,
                            end_period: int | None):
    if not territory_id or not provider_id or start_period is None or end_period is None:
        vacio = empty_figure("Seleccione un prestador")
        return vacio, vacio

    start_period, end_period = sorted((int(start_period), int(end_period)))
    try:
        history = get_provider_history(territory_id, provider_id, start_period, end_period)
    except Exception:
        vacio = empty_figure("Error al consultar la historia del prestador")
        return vacio, vacio
    if history.empty:
        vacio = empty_figure("El prestador no tiene registros en el período")
        return vacio, vacio

    history = history.copy()
    history["periodo"] = pd.to_datetime(history["periodo"])
    history["participacion_porcentaje"] = pd.to_numeric(history["participacion_porcentaje"], errors="coerce")
    history["total_lineas_prestador"] = pd.to_numeric(history["total_lineas_prestador"], errors="coerce")

    # Dos gráficos de un solo eje cada uno, no uno de doble eje -- un
    # doble eje con escalas arbitrarias (% vs. cuentas) invita a leer una
    # correlación visual entre las dos series que puede no existir; son
    # dos preguntas distintas ("¿qué tan grande es respecto al mercado?"
    # vs. "¿cuántas cuentas reporta en términos absolutos?"), mejor
    # respondidas por separado.
    participation_fig = go.Figure(go.Scatter(
        x=history["periodo"], y=history["participacion_porcentaje"], mode="lines+markers",
        line={"color": PALETTE["blue"], "width": 3}, fill="tozeroy", fillcolor="rgba(20, 100, 244, 0.08)",
    ))
    style_figure(participation_fig, hovermode="x unified")
    participation_fig.update_yaxes(title="Participación (%)", rangemode="tozero")

    lines_fig = go.Figure(go.Scatter(
        x=history["periodo"], y=history["total_lineas_prestador"], mode="lines+markers",
        line={"color": PALETTE["cyan"], "width": 3},
    ))
    style_figure(lines_fig, hovermode="x unified")
    lines_fig.update_yaxes(title="Cuentas", tickformat=",", rangemode="tozero")

    return participation_fig, lines_fig
