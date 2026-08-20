"""dashboard/pages/control.py — Inconsistencias para control y seguimiento regulatorio.

Módulo NUEVO (11-ago-2026, a pedido de Iván) -- reúne en un solo lugar tres
tipos de inconsistencia que antes solo vivían dispersas (un KPI aislado en
Evolución, o solo visibles corriendo SQL a mano):

1. Prestadores que NUNCA han entregado un reporte (mart.vw_prestadores_sin_
   reportar) -- ya existía como conteo en el KPI "Nunca han reportado" de
   Evolución; aquí se ve el detalle completo, no solo el número.
2. Prestadores que SÍ reportaron alguna vez y dejaron de hacerlo
   (mart.vw_prestadores_reporte_detenido) -- vista ya existente, nunca
   antes expuesta en el dashboard.
3. Variación mensual anómala en cuentas reportadas por prestador
   (services.queries.get_variacion_mensual_anomala) -- consulta NUEVA,
   comparando solo pares de meses donde el prestador reportó de verdad en
   AMBOS extremos (nunca mezcla "dejó de reportar" -- ya cubierto en el
   punto 2 -- con "cambió de verdad lo que reporta").

Todas las tablas exponen umbral/rango como controles de la página, no como
un corte fijo escondido en SQL -- mismo principio que las vistas fuente
(vw_prestadores_sin_reportar/vw_prestadores_reporte_detenido), que
deliberadamente no filtran nada por sí mismas.

FILTROS (12-ago-2026, a pedido de Iván): panel único arriba de la página
-- territory_filter_layout/shared_filters_layout, MISMOS componentes que
Evolución/Concentración (comparten "shared-territory"/"shared-filters" en
app.py: elegir un territorio o prestador en cualquiera de esas páginas ya
llega preseleccionado aquí). Aplican de forma DESIGUAL entre las tres
secciones, porque las fuentes de datos no son simétricas -- no es un
descuido, está documentado en cada función de services/queries.py:
  - "Nunca han reportado": SOLO Estado/Prestador. La vista fuente no tiene
    columna de geografía (SIETEL no conoce la ubicación de quien nunca
    reportó) ni de período (es "alguna vez, sí/no", no una serie de tiempo).
  - "Reporte detenido": territorio = "reportó alguna vez ahí" (no la
    geografía de su último reporte, la vista no la tiene por prestador);
    Desde/Hasta filtra por fecha del ÚLTIMO reporte, no por "meses mínimos
    sin reportar" (ese sigue siendo su propio control, con otro sentido).
  - "Variación mensual": los cinco filtros aplican tal cual, recalculando
    la suma de cuentas EN el territorio elegido antes de comparar mes a
    mes (mismo principio que get_evolution_filtrado).
"""
from __future__ import annotations

import dash_ag_grid as dag
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html, register_page

from components.filters_shared import register_universal_opera_isp_sync, sync_armado_store
from components.lines_territory_filters import lines_territory_filter_layout, register_lines_territory_callbacks
from components.ui import (
    PALETTE, build_linked_magnitude_variation_figure, build_sparkline_figure, chart_card, clean_records,
    empty_figure, error_panel, excel_download_button, format_number, format_signed, kpi_card, month_year_picker,
    numeric_stepper, page_header, register_excel_download_callback, register_month_year_picker_callback,
    register_shared_period_sync, signed_log_tickvals, style_figure, transformar_signed_log,
)
from services.queries import (
    get_churn_history_multiselect, get_evolution_filtrado_multiselect, get_operation_states, get_periods,
    get_prestadores_nunca_reportaron_detalle, get_prestadores_reporte_detenido_detalle,
    get_provider_count_in_range_multiselect, get_provider_options, get_reporting_summary_multiselect,
    get_universo_incumplimiento_consolidado, get_variacion_mensual_anomala, resolve_period_id,
)

register_page(__name__, path="/sai/control", name="Control", order=4)
PREFIX = "ctrl"


def _period_options():
    periods = get_periods()
    if periods.empty:
        raise RuntimeError("mart.dim_periodo no contiene registros.")
    min_period = int(periods["periodo_id"].min())
    max_period = int(periods["periodo_id"].max())
    return min_period, max_period


def layout():
    try:
        min_period, max_period = _period_options()
    except Exception as exc:
        return html.Div([page_header("Control", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Control",
                "Inconsistencias de reporte para seguimiento regulatorio -- prestadores sin reportar, "
                "reportes detenidos y variaciones mensuales fuera de lo normal.",
            ),
            sync_armado_store(PREFIX),
            html.Section(
                className="filter-panel",
                children=[
                    lines_territory_filter_layout(PREFIX),
                    html.Div(
                        className="territory-grid",
                        children=[
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Estado de operación"),
                                    dcc.Dropdown(
                                        id="ctrl-opera-estado", options=get_operation_states(), value=[],
                                        multi=True, placeholder="Todos",
                                    ),
                                ],
                            ),
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Prestador"),
                                    dcc.Dropdown(
                                        id="ctrl-isp-nombre", options=get_provider_options("NACIONAL|ECUADOR"),
                                        value=[], multi=True, placeholder="Todos",
                                    ),
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        className="period-grid four-periods",
                        children=[
                            month_year_picker("ctrl-start-period", "Desde", min_period, min_period, max_period),
                            month_year_picker("ctrl-end-period", "Hasta", max_period, min_period, max_period),
                        ],
                    ),
                ],
            ),
            html.P(
                "Los filtros de arriba no aplican igual a las tres secciones -- 'Nunca han reportado' solo usa "
                "Estado/Prestador (sin geografía ni período: la fuente no los tiene); 'Reporte detenido' usa "
                "Desde/Hasta sobre la fecha del último reporte, no sobre 'meses mínimos sin reportar'.",
                className="chart-subtitle",
            ),

            # Bloque duplicado de Evolución (14-ago-2026, a pedido de Iván)
            # -- mismo contenido, contexto general del mercado antes de
            # entrar a las tres inconsistencias específicas de abajo. NO
            # incluye "Nunca han reportado" del bloque "Resumen del rango"
            # de Evolución -- Control ya tiene su propia sección dedicada
            # a eso más abajo, con más detalle (KPIs por clasificación +
            # gráfico + tabla completa); repetirla aquí sería el mismo
            # número dos veces en la misma página. Usa las versiones
            # "_multiselect" de services/queries.py -- el filtro de
            # Control (Provincia/Cantón/Parroquia independientes, sin
            # Nivel) no es compatible con las funciones originales de
            # Evolución (territory_id único).
            html.H3(id="ctrl-resumen-titulo-estado", children="Estado actual"),
            html.Section(
                className="kpi-grid four",
                children=[
                    kpi_card("Cuentas reportadas (último período)", "ctrl-resumen-kpi-cuentas",
                             "ctrl-resumen-kpi-cuentas-note"),
                    kpi_card("Prestadores que reportaron", "ctrl-resumen-kpi-prestadores",
                             "ctrl-resumen-kpi-prestadores-note"),
                    kpi_card("Cambio mensual (reportadas)", "ctrl-resumen-kpi-cambio",
                             "ctrl-resumen-kpi-cambio-note"),
                    kpi_card("Dejaron de reportar este mes", "ctrl-resumen-kpi-churn",
                             "ctrl-resumen-kpi-churn-note", "ctrl-resumen-kpi-churn-spark"),
                ],
            ),
            html.H3(id="ctrl-resumen-titulo-rango", children="Resumen del rango seleccionado"),
            html.Section(
                className="kpi-grid three",
                children=[
                    kpi_card("Prestadores con actividad en el rango", "ctrl-resumen-kpi-rango-prestadores",
                             "ctrl-resumen-kpi-rango-prestadores-note"),
                    kpi_card("Total de prestadores (con o sin reportes)", "ctrl-resumen-kpi-rango-total",
                             "ctrl-resumen-kpi-rango-total-note"),
                    kpi_card("Tasa de entrega de reportes", "ctrl-resumen-kpi-rango-tasa",
                             "ctrl-resumen-kpi-rango-tasa-note"),
                ],
            ),
            html.Div(id="ctrl-resumen-message", className="data-message"),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card("Cuentas reportadas por mes", "ctrl-resumen-lines-chart",
                               "Arriba: magnitud (solo datos reales). Abajo: variación % respecto al mes "
                               "anterior, mismo eje de tiempo."),
                    chart_card("Prestadores que reportaron", "ctrl-resumen-providers-chart",
                               "Arriba: cantidad de prestadores con al menos un reporte real cada mes. "
                               "Abajo: variación % respecto al mes anterior, mismo eje de tiempo."),
                ],
            ),

            html.H3("Prestadores que nunca han reportado", style={"marginTop": "20px"}),
            html.Section(
                className="kpi-grid four",
                children=[
                    kpi_card("Activo sin reportar", "ctrl-kpi-activo", "ctrl-kpi-activo-note"),
                    kpi_card("No operativo", "ctrl-kpi-no-operativo", "ctrl-kpi-no-operativo-note"),
                    kpi_card("Zona gris", "ctrl-kpi-zona-gris", "ctrl-kpi-zona-gris-note"),
                    kpi_card("Total", "ctrl-kpi-total-nunca", "ctrl-kpi-total-nunca-note"),
                ],
            ),
            html.Section(
                className="chart-card",
                children=[
                    html.Div(
                        className="chart-header",
                        children=[html.H3("Distribución por clasificación", className="chart-title")],
                    ),
                    dcc.Graph(id="ctrl-nunca-chart", config={"displaylogo": False}),
                ],
            ),
            html.Section(
                className="table-card",
                children=[
                    dag.AgGrid(
                        id="ctrl-nunca-grid",
                        columnDefs=[
                            {"field": "peva_codigo", "headerName": "PEVA", "minWidth": 110},
                            {"field": "isp_nombre", "headerName": "Prestador", "minWidth": 260, "flex": 2},
                            {"field": "isp_ruc", "headerName": "RUC", "minWidth": 150},
                            {"field": "opera", "headerName": "Estado (opera)", "minWidth": 160},
                            {"field": "fechapermiso", "headerName": "Fecha de permiso", "minWidth": 140},
                            {"field": "fuera_de_gracia", "headerName": "Fuera de año de gracia", "minWidth": 170},
                            {"field": "clasificacion_incumplimiento", "headerName": "Clasificación", "minWidth": 170},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 10,
                                         "animateRows": True},
                        columnSize="responsiveSizeToFit",
                        style={"height": "420px", "width": "100%"},
                    ),
                    excel_download_button("ctrl-nunca-grid"),
                ],
            ),

            html.H3("Prestadores con reporte detenido", style={"marginTop": "28px"}),
            html.Div(
                className="filter-panel",
                children=[numeric_stepper("ctrl-meses-minimo", "Meses mínimos sin reportar", 3, min_value=1)],
            ),
            html.Div(id="ctrl-detenido-message", className="data-message"),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card(
                        "Distribución de meses sin reportar", "ctrl-detenido-hist",
                        "Cuántos prestadores llevan cuánto tiempo detenidos -- la forma de la cola importa "
                        "tanto como el total.",
                    ),
                    chart_card(
                        "Priorización: antigüedad vs. peso histórico", "ctrl-detenido-scatter",
                        "Eje Y logarítmico -- separa a un prestador grande detenido hace poco de uno "
                        "pequeño detenido hace años, ambos invisibles en una sola cifra de 'meses sin reportar'.",
                    ),
                ],
            ),
            html.Section(
                className="table-card",
                children=[
                    dag.AgGrid(
                        id="ctrl-detenido-grid",
                        columnDefs=[
                            {"field": "isp_nombre", "headerName": "Prestador", "minWidth": 260, "flex": 2},
                            {"field": "ruc_limpio", "headerName": "RUC", "minWidth": 150},
                            {"field": "opera_actual", "headerName": "Estado actual", "minWidth": 160},
                            {"field": "ultimo_periodo_reportado", "headerName": "Último reporte", "minWidth": 140},
                            {"field": "meses_desde_ultimo_reporte", "headerName": "Meses sin reportar",
                             "type": "numericColumn", "minWidth": 150},
                            {"field": "lineas_ultimo_reporte", "headerName": "Cuentas (último reporte)",
                             "type": "numericColumn", "minWidth": 170},
                            {"field": "total_lineas_historico", "headerName": "Cuentas (histórico)",
                             "type": "numericColumn", "minWidth": 160},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 10,
                                         "animateRows": True},
                        columnSize="responsiveSizeToFit",
                        style={"height": "420px", "width": "100%"},
                    ),
                    excel_download_button("ctrl-detenido-grid"),
                ],
            ),

            # Universo consolidado (14-ago-2026, hallazgo 2.6 del EDA) --
            # suma "nunca reportaron, activos" (arriba) + "reportaron y
            # detuvieron, materialmente relevantes" (justo arriba de esto)
            # -- sin este KPI, un analista tendría que sumar los dos
            # números a mano para responder "¿cuál es mi universo TOTAL de
            # incumplimiento activo hoy?". Umbral de materialidad para la
            # segunda mitad DISTINTO del "meses_minimo" ajustable de
            # arriba -- ver services/queries.py:get_universo_incumplimiento_consolidado.
            html.H3("Universo consolidado de incumplimiento activo", style={"marginTop": "28px"}),
            html.P(
                "Nunca han reportado (activo, arriba) + reportaron y detuvieron (materialmente "
                "relevante: opera normalmente, no cancelado, más de 100.000 cuentas históricas, "
                "3+ meses sin reportar -- umbral fijo, distinto del ajustable de la sección de "
                "arriba). Sin solapamiento entre ambos grupos por construcción.",
                className="chart-subtitle",
            ),
            html.Section(
                className="kpi-grid three",
                children=[
                    kpi_card("Nunca reportaron (activo)", "ctrl-universo-kpi-nunca",
                             "ctrl-universo-kpi-nunca-note"),
                    kpi_card("Reportaron y detuvieron (relevante)", "ctrl-universo-kpi-detenido",
                             "ctrl-universo-kpi-detenido-note"),
                    kpi_card("Universo total", "ctrl-universo-kpi-total", "ctrl-universo-kpi-total-note"),
                ],
            ),

            html.H3("Variación mensual anómala en cuentas reportadas", style={"marginTop": "28px"}),
            html.Div(
                className="filter-panel",
                children=[
                    html.Div(
                        className="period-grid four-periods",
                        children=[numeric_stepper("ctrl-umbral-variacion", "Umbral de variación (%)", 30, min_value=1)],
                    ),
                ],
            ),
            html.P(
                "Solo compara pares de meses consecutivos donde el prestador reportó de verdad en AMBOS "
                "extremos -- un salto frente a un mes sin reporte real no es una variación genuina, es "
                "artefacto del relleno interior (LOCF). Ver 'Prestadores con reporte detenido' arriba para "
                "ese caso.",
                className="chart-subtitle",
            ),
            html.Div(id="ctrl-variacion-message", className="data-message"),
            html.Section(
                className="chart-grid two",
                children=[
                    chart_card(
                        "Casos más extremos (Top 15)", "ctrl-variacion-ranking",
                        "Las variaciones más grandes en valor absoluto dentro del rango -- punto de partida "
                        "natural para revisar caso por caso.",
                    ),
                    chart_card(
                        "Variación en el tiempo", "ctrl-variacion-tiempo",
                        "Eje Y con signo preservado en escala logarítmica -- para que un caso de +10.000% no "
                        "aplaste visualmente al resto. Ayuda a ver si las anomalías se concentran en ciertos "
                        "meses/años o están dispersas.",
                    ),
                ],
            ),
            html.Section(
                className="table-card",
                children=[
                    dag.AgGrid(
                        id="ctrl-variacion-grid",
                        columnDefs=[
                            {"field": "isp_nombre", "headerName": "Prestador", "minWidth": 240, "flex": 2},
                            {"field": "ruc_limpio", "headerName": "RUC", "minWidth": 150},
                            {"field": "anio_mes", "headerName": "Período", "minWidth": 110},
                            {"field": "lineas_mes_anterior", "headerName": "Cuentas (mes anterior)",
                             "type": "numericColumn", "minWidth": 160},
                            {"field": "lineas_reportadas", "headerName": "Cuentas (este mes)",
                             "type": "numericColumn", "minWidth": 150},
                            {"field": "diferencia", "headerName": "Diferencia", "type": "numericColumn",
                             "minWidth": 130},
                            {"field": "variacion_porcentaje", "headerName": "Variación %",
                             "type": "numericColumn", "minWidth": 130},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 10,
                                         "animateRows": True},
                        columnSize="responsiveSizeToFit",
                        style={"height": "420px", "width": "100%"},
                    ),
                    excel_download_button("ctrl-variacion-grid"),
                ],
            ),
        ]
    )


register_lines_territory_callbacks(PREFIX)
register_universal_opera_isp_sync(PREFIX, lambda: get_provider_options("NACIONAL|ECUADOR"))
register_month_year_picker_callback("ctrl-start-period")
register_month_year_picker_callback("ctrl-end-period")
register_shared_period_sync("ctrl-start-period", "ctrl-end-period")
register_excel_download_callback("ctrl-nunca-grid", "prestadores_sin_reportar.xlsx")
register_excel_download_callback("ctrl-detenido-grid", "prestadores_reporte_detenido.xlsx")
register_excel_download_callback("ctrl-variacion-grid", "variacion_mensual_anomala.xlsx")


@callback(
    Output("ctrl-resumen-kpi-cuentas", "children"),
    Output("ctrl-resumen-kpi-cuentas-note", "children"),
    Output("ctrl-resumen-kpi-prestadores", "children"),
    Output("ctrl-resumen-kpi-prestadores-note", "children"),
    Output("ctrl-resumen-kpi-cambio", "children"),
    Output("ctrl-resumen-kpi-cambio-note", "children"),
    Output("ctrl-resumen-kpi-churn", "children"),
    Output("ctrl-resumen-kpi-churn-note", "children"),
    Output("ctrl-resumen-kpi-churn-spark", "figure"),
    Output("ctrl-resumen-lines-chart", "figure"),
    Output("ctrl-resumen-providers-chart", "figure"),
    Output("ctrl-resumen-message", "children"),
    Output("ctrl-resumen-titulo-estado", "children"),
    Output("ctrl-resumen-titulo-rango", "children"),
    Output("ctrl-resumen-kpi-rango-prestadores", "children"),
    Output("ctrl-resumen-kpi-rango-prestadores-note", "children"),
    Output("ctrl-resumen-kpi-rango-total", "children"),
    Output("ctrl-resumen-kpi-rango-total-note", "children"),
    Output("ctrl-resumen-kpi-rango-tasa", "children"),
    Output("ctrl-resumen-kpi-rango-tasa-note", "children"),
    Input("ctrl-territory-selection", "data"),
    Input("ctrl-start-period", "data"),
    Input("ctrl-end-period", "data"),
    Input("ctrl-opera-estado", "value"),
    Input("ctrl-isp-nombre", "value"),
)
def update_resumen(seleccion, start_period, end_period, opera_estados, isp_nombres):
    """
    Duplica el bloque "Estado actual"/"Resumen del rango seleccionado" de
    Evolución (14-ago-2026, a pedido de Iván) -- mismo contenido, MISMA
    lógica de cálculo, pero usando las versiones "_multiselect" de
    services/queries.py: el filtro de Control (Provincia/Cantón/Parroquia
    independientes, sin Nivel geográfico) no es compatible con las
    funciones que usa Evolución (territory_id único). Ver el docstring de
    esa sección en queries.py para el porqué completo.

    NO incluye "Nunca han reportado" -- Control ya tiene su propia sección
    dedicada a eso, con más detalle, más abajo en esta misma página.
    """
    seleccion = seleccion or {}
    provincias = tuple(seleccion.get("provincias") or ())
    cantones = tuple(seleccion.get("cantones") or ())
    parroquias = tuple(seleccion.get("parroquias") or ())
    opera_estados = tuple(opera_estados or ())
    isp_nombres = tuple(isp_nombres or ())

    if start_period is None or end_period is None:
        figures = [empty_figure("Seleccione un rango de períodos") for _ in range(2)]
        return ("—", "", "—", "", "—", "", "—", "", empty_figure(), *figures, "", "Estado actual",
                "Resumen del rango seleccionado", "—", "", "—", "", "—", "")

    start_period, end_period = sorted((int(start_period), int(end_period)))

    try:
        evolution = get_evolution_filtrado_multiselect(
            provincias, cantones, parroquias, start_period, end_period, opera_estados, isp_nombres,
        )
    except Exception as exc:
        figures = [empty_figure("Error al consultar PostgreSQL") for _ in range(2)]
        return ("—", "", "—", "", "—", "", "—", "", empty_figure(), *figures, str(exc), "Estado actual",
                "Resumen del rango seleccionado", "—", "", "—", "", "—", "")

    if evolution.empty:
        figures = [empty_figure() for _ in range(2)]
        return ("—", "", "—", "", "—", "", "—", "", empty_figure(), *figures,
                "No existen datos para este territorio, período y filtros seleccionados.",
                "Estado actual", "Resumen del rango seleccionado", "—", "", "—", "", "—", "")

    evolution = evolution.copy()
    evolution["periodo"] = pd.to_datetime(evolution["periodo"])
    for columna in ["total_lineas", "lineas_reportadas", "numero_prestadores",
                    "diferencia_mensual_lineas", "variacion_mensual_porcentaje"]:
        if columna in evolution:
            evolution[columna] = pd.to_numeric(evolution[columna], errors="coerce")

    latest = evolution.sort_values("periodo_id").iloc[-1]
    latest_label = str(latest.get("anio_mes", ""))

    lines_value = format_number(latest.get("lineas_reportadas"))
    lines_note = f"Período {latest_label}"

    providers_value = format_number(latest.get("numero_prestadores"))
    providers_note = f"Con reporte real en {latest_label}"

    change_value = format_signed(latest.get("diferencia_mensual_lineas"))
    change_note = (
        f"{format_signed(latest.get('variacion_mensual_porcentaje'), 2, '%')} respecto al mes anterior "
        "(sobre reportadas)"
    )

    # "Dejaron de reportar este mes" y su sparkline comparten la MISMA
    # consulta (get_churn_history_multiselect) -- el valor puntual es
    # simplemente la última fila de esa misma serie, no una consulta
    # aparte (ver services/queries.py para por qué no puede reusar
    # get_participation/get_churn_history originales aquí).
    churn_value, churn_note, churn_spark = "—", "", empty_figure()
    try:
        periodo_actual_id = int(latest["periodo_id"])
        churn_hist = get_churn_history_multiselect(provincias, cantones, parroquias, periodo_actual_id, meses=12)
        if not churn_hist.empty:
            fila_actual = churn_hist[churn_hist["periodo_id"] == periodo_actual_id]
            if not fila_actual.empty:
                churn_actual = int(pd.to_numeric(fila_actual.iloc[0]["churn"], errors="coerce") or 0)
                fecha_mes_anterior = (latest["periodo"] - pd.DateOffset(months=1)).date().isoformat()
                periodo_anterior_id = resolve_period_id(fecha_mes_anterior)
                activos_anterior = (
                    get_provider_count_in_range_multiselect(
                        provincias, cantones, parroquias, periodo_anterior_id, periodo_anterior_id,
                    ) if periodo_anterior_id is not None else 0
                )
                churn_value = format_number(churn_actual)
                churn_note = f"De {format_number(activos_anterior)} activos en el mes anterior"
            churn_spark = build_sparkline_figure(
                pd.to_numeric(churn_hist["churn"], errors="coerce").tolist(), PALETTE["red"],
            )
    except Exception:
        churn_value, churn_note, churn_spark = "—", "No se pudo calcular", empty_figure()

    evolution_ordenada = evolution.sort_values("periodo")
    lines_variacion_pct = (
            evolution_ordenada["lineas_reportadas"].pct_change().replace([float("inf"), float("-inf")],
                                                                         float("nan")) * 100
    )
    lines_combined_fig = build_linked_magnitude_variation_figure(
        evolution_ordenada["periodo"], evolution_ordenada["lineas_reportadas"], lines_variacion_pct,
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

    filtros_txt = []
    if provincias or cantones or parroquias:
        partes = []
        if provincias:
            partes.append(f"{len(provincias)} provincia(s)")
        if cantones:
            partes.append(f"{len(cantones)} cantón(es)")
        if parroquias:
            partes.append(f"{len(parroquias)} parroquia(s)")
        filtros_txt.append("Territorio: " + ", ".join(partes))
    else:
        filtros_txt.append("Territorio: Nacional")
    if opera_estados:
        filtros_txt.append(f"Estado: {', '.join(opera_estados)}")
    if isp_nombres:
        filtros_txt.append(f"Prestador: {', '.join(isp_nombres)}")
    message = f"{'; '.join(filtros_txt)} · Último período visible: {latest_label}"

    titulo_estado_actual = f"Estado actual — {latest_label}"
    primero = evolution.sort_values("periodo_id").iloc[0]
    rango_desde_label = str(primero.get("anio_mes", ""))
    rango_hasta_label = latest_label
    titulo_resumen_rango = f"Resumen del rango seleccionado — {rango_desde_label} a {rango_hasta_label}"

    try:
        cantidad_rango = get_provider_count_in_range_multiselect(
            provincias, cantones, parroquias, start_period, end_period,
        )
        rango_prestadores_value = format_number(cantidad_rango)
        rango_prestadores_note = (
            f"Con al menos un reporte real entre {rango_desde_label} y {rango_hasta_label}. "
            "No equivale a título habilitante vigente."
        )
    except Exception:
        rango_prestadores_value, rango_prestadores_note = "—", "No se pudo calcular"

    # "Nacional-equivalente" para Control = ningún territorio elegido --
    # mismo criterio que territory_id == "NACIONAL|ECUADOR" en Evolución.
    # CORRECCIÓN (14-ago-2026): esto faltaba por completo -- confirmado en
    # producción, con el mismo filtro (sin territorio, rango completo)
    # "Total de prestadores" mostraba 1.369 en Control y 1.654 en
    # Evolución; la diferencia (285) es exactamente el "Total" de la
    # sección "Nunca han reportado" de más abajo en esta misma página.
    incluir_nunca = not (provincias or cantones or parroquias)

    try:
        resumen = get_reporting_summary_multiselect(
            provincias, cantones, parroquias, start_period, end_period, opera_estados, isp_nombres,
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
                "No incluye a quienes nunca han reportado -- ese dato solo existe sin territorio elegido."
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
                "habilitante. No incluye a quienes nunca han reportado -- ese dato solo existe sin "
                "territorio elegido."
            )
    except Exception:
        rango_total_value, rango_total_note = "—", "No se pudo calcular"
        rango_tasa_value, rango_tasa_note = "—", "No se pudo calcular"

    return (
        lines_value, lines_note,
        providers_value, providers_note,
        change_value, change_note,
        churn_value, churn_note, churn_spark,
        lines_combined_fig, providers_combined_fig,
        message,
        titulo_estado_actual, titulo_resumen_rango,
        rango_prestadores_value, rango_prestadores_note,
        rango_total_value, rango_total_note,
        rango_tasa_value, rango_tasa_note,
    )


@callback(
    Output("ctrl-kpi-activo", "children"),
    Output("ctrl-kpi-activo-note", "children"),
    Output("ctrl-kpi-no-operativo", "children"),
    Output("ctrl-kpi-no-operativo-note", "children"),
    Output("ctrl-kpi-zona-gris", "children"),
    Output("ctrl-kpi-zona-gris-note", "children"),
    Output("ctrl-kpi-total-nunca", "children"),
    Output("ctrl-kpi-total-nunca-note", "children"),
    Output("ctrl-nunca-chart", "figure"),
    Output("ctrl-nunca-grid", "rowData"),
    Input("ctrl-opera-estado", "value"),
    Input("ctrl-isp-nombre", "value"),
)
def update_nunca_reportaron(opera_estados, isp_nombres):
    try:
        df = get_prestadores_nunca_reportaron_detalle(tuple(opera_estados or ()), tuple(isp_nombres or ()))
    except Exception as exc:
        vacio_txt = ("—", f"No se pudo calcular: {exc}")
        return (*vacio_txt, *vacio_txt, *vacio_txt, *vacio_txt, empty_figure("No se pudo consultar PostgreSQL"), [])

    if df.empty:
        vacio_txt = ("0", "")
        return (*vacio_txt, *vacio_txt, *vacio_txt, *vacio_txt, empty_figure("No hay prestadores sin reportar"), [])

    conteos = df["clasificacion_incumplimiento"].value_counts()
    activo = int(conteos.get("activo_sin_reportar", 0))
    no_operativo = int(conteos.get("no_operativo", 0))
    zona_gris = int(conteos.get("zona_gris", 0))
    total = len(df)

    # Barras horizontales, no dona/pastel -- con solo 3 categorías el
    # objetivo es comparar magnitudes con precisión, algo que un gráfico
    # circular hace mal por diseño. Orden fijo (no por magnitud) para que
    # la lectura sea siempre la misma: el caso de incumplimiento real
    # primero.
    categorias = ["activo_sin_reportar", "no_operativo", "zona_gris"]
    etiquetas = {
        "activo_sin_reportar": "Activo sin reportar", "no_operativo": "No operativo", "zona_gris": "Zona gris",
    }
    colores = {"activo_sin_reportar": PALETTE["red"], "no_operativo": PALETTE["muted"], "zona_gris": PALETTE["cyan"]}
    valores = [int(conteos.get(c, 0)) for c in categorias]
    nunca_fig = go.Figure(go.Bar(
        x=valores, y=[etiquetas[c] for c in categorias], orientation="h",
        marker_color=[colores[c] for c in categorias], text=valores, textposition="outside",
        hovertemplate="%{y}: %{x}<extra></extra>",
    ))
    style_figure(nunca_fig, height=230, hovermode="closest")
    nunca_fig.update_xaxes(title="Prestadores")
    nunca_fig.update_yaxes(title="")

    return (
        format_number(activo), "Título vigente, opera, cero reportes -- el caso de incumplimiento real",
        format_number(no_operativo), "Cancelado/revocado -- nunca llegó a operar, universo administrativo distinto",
        format_number(zona_gris), "Estado ambiguo en 'opera' -- requiere revisión caso por caso",
        format_number(total), "Total de prestadores con título habilitante y cero reportes en toda su historia",
        nunca_fig, clean_records(df),
    )


@callback(
    Output("ctrl-universo-kpi-nunca", "children"),
    Output("ctrl-universo-kpi-nunca-note", "children"),
    Output("ctrl-universo-kpi-detenido", "children"),
    Output("ctrl-universo-kpi-detenido-note", "children"),
    Output("ctrl-universo-kpi-total", "children"),
    Output("ctrl-universo-kpi-total-note", "children"),
    Input("ctrl-opera-estado", "value"),
    Input("ctrl-isp-nombre", "value"),
)
def update_universo_consolidado(opera_estados, isp_nombres):
    """Hallazgo 2.6 del EDA -- ver services/queries.py:get_universo_incumplimiento_consolidado."""
    try:
        resumen = get_universo_incumplimiento_consolidado(tuple(opera_estados or ()), tuple(isp_nombres or ()))
    except Exception as exc:
        vacio = ("—", f"No se pudo calcular: {exc}")
        return (*vacio, *vacio, *vacio)

    return (
        format_number(resumen["nunca_reporto"]),
        "Mismo criterio que 'Activo sin reportar' arriba.",
        format_number(resumen["reporto_y_detuvo"]),
        "Opera normalmente, no cancelado, más de 100.000 cuentas históricas, 3+ meses sin reportar.",
        format_number(resumen["total"]),
        "Sin solapamiento entre ambos grupos -- quien nunca reportó, por definición, no puede "
        "aparecer también en 'reporte detenido'.",
    )


@callback(
    Output("ctrl-detenido-grid", "rowData"),
    Output("ctrl-detenido-message", "children"),
    Output("ctrl-detenido-hist", "figure"),
    Output("ctrl-detenido-scatter", "figure"),
    Input("ctrl-territory-selection", "data"),
    Input("ctrl-start-period", "data"),
    Input("ctrl-end-period", "data"),
    Input("ctrl-opera-estado", "value"),
    Input("ctrl-isp-nombre", "value"),
    Input("ctrl-meses-minimo", "value"),
)
def update_reporte_detenido(seleccion, start_period, end_period, opera_estados, isp_nombres, meses_minimo):
    seleccion = seleccion or {}
    meses_minimo = int(meses_minimo) if meses_minimo else 1
    start_period = int(start_period) if start_period is not None else None
    end_period = int(end_period) if end_period is not None else None
    if start_period is not None and end_period is not None:
        start_period, end_period = sorted((start_period, end_period))

    try:
        df = get_prestadores_reporte_detenido_detalle(
            meses_minimo,
            tuple(seleccion.get("provincias") or ()),
            tuple(seleccion.get("cantones") or ()),
            tuple(seleccion.get("parroquias") or ()),
            start_period, end_period,
            tuple(opera_estados or ()), tuple(isp_nombres or ()),
        )
    except Exception as exc:
        vacio = empty_figure("Error al consultar PostgreSQL")
        return [], f"Error al consultar PostgreSQL: {exc}", vacio, vacio
    if df.empty:
        vacio = empty_figure(f"Ningún prestador con {meses_minimo} o más meses sin reportar")
        return [], f"Ningún prestador con {meses_minimo} o más meses sin reportar para estos filtros.", vacio, vacio

    df = df.copy()
    df["meses_desde_ultimo_reporte"] = pd.to_numeric(df["meses_desde_ultimo_reporte"], errors="coerce")
    df["total_lineas_historico"] = pd.to_numeric(df["total_lineas_historico"], errors="coerce")

    # Histograma: la FORMA de la distribución importa -- ¿son casi todos
    # detenidos recientes con una cola larga de casos viejos (esperado en
    # un flujo de bajas normal), o hay un segundo grupo separado (señal de
    # un problema estructural, ej. un cambio de sistema que rompió el
    # reporte de un lote de prestadores en un mes puntual)?
    hist_fig = px.histogram(df, x="meses_desde_ultimo_reporte", nbins=30)
    hist_fig.update_traces(marker_color=PALETTE["blue"])
    style_figure(hist_fig, height=340, hovermode="x")
    hist_fig.update_xaxes(title="Meses sin reportar")
    hist_fig.update_yaxes(title="Prestadores")

    # Dispersión: "meses sin reportar" solo no alcanza para priorizar --
    # un prestador con 160 meses de inactividad y 13 cuentas históricas
    # importa mucho menos que uno con 6 meses y 100.000 cuentas. Escala
    # log en Y porque el rango observado va de unidades a cientos de miles.
    scatter_df = df[df["total_lineas_historico"] > 0]
    scatter_fig = go.Figure(go.Scatter(
        x=scatter_df["meses_desde_ultimo_reporte"], y=scatter_df["total_lineas_historico"],
        mode="markers",
        marker={"color": PALETTE["red"], "size": 8, "opacity": 0.6},
        text=scatter_df["isp_nombre"],
        hovertemplate="%{text}<br>Meses sin reportar: %{x}<br>Cuentas históricas: %{y:,.0f}<extra></extra>",
    ))
    style_figure(scatter_fig, height=340, hovermode="closest")
    scatter_fig.update_xaxes(title="Meses sin reportar")
    scatter_fig.update_yaxes(title="Cuentas históricas (escala log)", type="log")

    mensaje = f"{len(df):,} prestadores con {meses_minimo} o más meses sin reportar".replace(",", ".")
    return clean_records(df), mensaje, hist_fig, scatter_fig


@callback(
    Output("ctrl-variacion-grid", "rowData"),
    Output("ctrl-variacion-message", "children"),
    Output("ctrl-variacion-ranking", "figure"),
    Output("ctrl-variacion-tiempo", "figure"),
    Input("ctrl-territory-selection", "data"),
    Input("ctrl-start-period", "data"),
    Input("ctrl-end-period", "data"),
    Input("ctrl-opera-estado", "value"),
    Input("ctrl-isp-nombre", "value"),
    Input("ctrl-umbral-variacion", "value"),
)
def update_variacion(seleccion, start_period, end_period, opera_estados, isp_nombres, umbral):
    seleccion = seleccion or {}
    if start_period is None or end_period is None:
        vacio = empty_figure("Seleccione un rango de períodos")
        return [], "Seleccione un rango de períodos", vacio, vacio
    start_period, end_period = sorted((int(start_period), int(end_period)))
    umbral = float(umbral) if umbral else 30.0
    try:
        df = get_variacion_mensual_anomala(
            start_period, end_period, umbral,
            tuple(seleccion.get("provincias") or ()),
            tuple(seleccion.get("cantones") or ()),
            tuple(seleccion.get("parroquias") or ()),
            tuple(opera_estados or ()), tuple(isp_nombres or ()),
        )
    except Exception as exc:
        vacio = empty_figure("Error al consultar PostgreSQL")
        return [], f"Error al consultar PostgreSQL: {exc}", vacio, vacio
    if df.empty:
        vacio = empty_figure(f"Ninguna variación ≥ {format_number(umbral)}%")
        return (
            [], f"Ninguna variación mensual igual o mayor a {format_number(umbral)}% en el rango seleccionado.",
            vacio, vacio,
        )

    df = df.copy()
    df["variacion_porcentaje"] = pd.to_numeric(df["variacion_porcentaje"], errors="coerce")
    df["diferencia"] = pd.to_numeric(df["diferencia"], errors="coerce")
    df["periodo"] = pd.to_datetime(df["periodo"])

    # Ranking: las 15 variaciones más extremas en valor absoluto -- punto
    # de partida de triage, más accionable que una tabla de miles de filas
    # ordenada por fecha.
    top = df.reindex(df["variacion_porcentaje"].abs().sort_values(ascending=False).index).head(15)
    top = top.sort_values("variacion_porcentaje")
    etiqueta_top = top["isp_nombre"].fillna("(sin nombre)") + " · " + top["anio_mes"].astype(str)
    ranking_fig = go.Figure(go.Bar(
        x=top["variacion_porcentaje"], y=etiqueta_top, orientation="h",
        marker_color=[PALETTE["teal"] if v >= 0 else PALETTE["red"] for v in top["variacion_porcentaje"]],
        hovertemplate="%{y}<br>Variación: %{x:.1f}%<extra></extra>",
    ))
    style_figure(ranking_fig, height=420, hovermode="closest")
    ranking_fig.update_xaxes(title="Variación % (vs. mes anterior)")
    ranking_fig.update_yaxes(title="")

    # Dispersión temporal: sign(v) * log10(1 + |v|) -- Plotly no tiene un
    # eje "symlog" nativo; esta transformación logra lo mismo a mano,
    # preservando el signo (positivo/negativo) mientras evita que un caso
    # de +10.000% comprima visualmente el resto de puntos contra el cero.
    # El hover siempre muestra el % real, sin transformar. Función
    # compartida (components/ui.py) -- Evolución la usa también para sus
    # dos gráficos de variación mensual, ver pages/evolucion.py.
    df["variacion_transformada"] = transformar_signed_log(df["variacion_porcentaje"])
    tiempo_fig = go.Figure(go.Scatter(
        x=df["periodo"], y=df["variacion_transformada"],
        mode="markers",
        marker={
            "color": [PALETTE["teal"] if v >= 0 else PALETTE["red"] for v in df["variacion_porcentaje"]],
            "size": 7, "opacity": 0.5,
        },
        text=df["isp_nombre"].fillna("(sin nombre)") + " · " + df["variacion_porcentaje"].round(1).astype(str) + "%",
        hovertemplate="%{text}<extra></extra>",
    ))
    style_figure(tiempo_fig, height=360, hovermode="closest")
    tiempo_fig.update_xaxes(title="Período")

    # tickvals/ticktext/range fuerzan las marcas del eje a porcentajes
    # "redondos" reales (+300%, +1.000%...), no el valor transformado
    # (-2, 0, 2, 4) que no significa nada para quien no leyó el subtítulo
    # -- y "range" fuerza que el eje visible siempre llegue hasta -100%,
    # aunque el dato real de este territorio/rango no baje tanto (ver el
    # docstring de signed_log_tickvals()).
    tickvals, ticktext, rango = signed_log_tickvals(df["variacion_transformada"])
    tiempo_fig.update_yaxes(
        title="Variación % (escala log, signo preservado)",
        zeroline=True, zerolinecolor="#c7d2dc",
        tickvals=tickvals, ticktext=ticktext, range=rango,
    )

    columnas = [
        "isp_nombre", "ruc_limpio", "anio_mes", "lineas_mes_anterior", "lineas_reportadas",
        "diferencia", "variacion_porcentaje",
    ]
    mensaje = f"{len(df):,} variaciones iguales o mayores a {format_number(umbral)}%".replace(",", ".")
    return clean_records(df[columnas]), mensaje, ranking_fig, tiempo_fig
