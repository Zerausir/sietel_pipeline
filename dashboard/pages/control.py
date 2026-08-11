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

Solo lectura, sin territorio (estas tres inconsistencias son a nivel
Nacional -- ver el límite ya documentado en vw_prestadores_sin_reportar:
SIETEL no conoce la geografía de quien nunca reportó).
"""
from __future__ import annotations

import dash_ag_grid as dag
from dash import Input, Output, callback, dcc, html, register_page

from components.ui import (
    clean_records, error_panel, excel_download_button, format_number, kpi_card, month_year_picker, page_header,
    register_excel_download_callback, register_month_year_picker_callback,
)
from services.queries import (
    get_periods, get_prestadores_nunca_reportaron_detalle, get_prestadores_reporte_detenido_detalle,
    get_variacion_mensual_anomala,
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
            html.H3("Prestadores que nunca han reportado"),
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
                children=[
                    html.Div(
                        className="filter-field",
                        style={"maxWidth": "260px"},
                        children=[
                            html.Label("Meses mínimos sin reportar"),
                            dcc.Input(
                                id="ctrl-meses-minimo", type="number", min=1, step=1, value=3,
                                className="numeric-input",
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(id="ctrl-detenido-message", className="data-message"),
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

            html.H3("Variación mensual anómala en cuentas reportadas", style={"marginTop": "28px"}),
            html.Div(
                className="filter-panel",
                children=[
                    html.Div(
                        className="period-grid four-periods",
                        children=[
                            month_year_picker("ctrl-start-period", "Desde", min_period, min_period, max_period),
                            month_year_picker("ctrl-end-period", "Hasta", max_period, min_period, max_period),
                            html.Div(
                                className="filter-field",
                                style={"maxWidth": "220px"},
                                children=[
                                    html.Label("Umbral de variación (%)"),
                                    dcc.Input(
                                        id="ctrl-umbral-variacion", type="number", min=1, step=1, value=30,
                                        className="numeric-input",
                                    ),
                                ],
                            ),
                        ],
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


register_excel_download_callback("ctrl-nunca-grid", "prestadores_sin_reportar.xlsx")
register_excel_download_callback("ctrl-detenido-grid", "prestadores_reporte_detenido.xlsx")
register_excel_download_callback("ctrl-variacion-grid", "variacion_mensual_anomala.xlsx")
register_month_year_picker_callback("ctrl-start-period")
register_month_year_picker_callback("ctrl-end-period")


@callback(
    Output("ctrl-kpi-activo", "children"),
    Output("ctrl-kpi-activo-note", "children"),
    Output("ctrl-kpi-no-operativo", "children"),
    Output("ctrl-kpi-no-operativo-note", "children"),
    Output("ctrl-kpi-zona-gris", "children"),
    Output("ctrl-kpi-zona-gris-note", "children"),
    Output("ctrl-kpi-total-nunca", "children"),
    Output("ctrl-kpi-total-nunca-note", "children"),
    Output("ctrl-nunca-grid", "rowData"),
    Input("ctrl-nunca-grid", "id"),  # dispara una sola vez al montar la página
)
def update_nunca_reportaron(_):
    try:
        df = get_prestadores_nunca_reportaron_detalle()
    except Exception as exc:
        vacio = ("—", "No se pudo calcular")
        return (*vacio, *vacio, *vacio, *vacio, [])

    if df.empty:
        vacio = ("0", "")
        return (*vacio, *vacio, *vacio, *vacio, [])

    conteos = df["clasificacion_incumplimiento"].value_counts()
    activo = int(conteos.get("activo_sin_reportar", 0))
    no_operativo = int(conteos.get("no_operativo", 0))
    zona_gris = int(conteos.get("zona_gris", 0))
    total = len(df)

    return (
        format_number(activo), "Título vigente, opera, cero reportes -- el caso de incumplimiento real",
        format_number(no_operativo), "Cancelado/revocado -- nunca llegó a operar, universo administrativo distinto",
        format_number(zona_gris), "Estado ambiguo en 'opera' -- requiere revisión caso por caso",
        format_number(total), "Total de prestadores con título habilitante y cero reportes en toda su historia",
        clean_records(df),
    )


@callback(
    Output("ctrl-detenido-grid", "rowData"),
    Output("ctrl-detenido-message", "children"),
    Input("ctrl-meses-minimo", "value"),
)
def update_reporte_detenido(meses_minimo):
    meses_minimo = int(meses_minimo) if meses_minimo else 1
    try:
        df = get_prestadores_reporte_detenido_detalle(meses_minimo)
    except Exception as exc:
        return [], f"Error al consultar PostgreSQL: {exc}"
    if df.empty:
        return [], f"Ningún prestador con {meses_minimo} o más meses sin reportar."
    return clean_records(df), f"{len(df):,} prestadores con {meses_minimo} o más meses sin reportar".replace(",", ".")


@callback(
    Output("ctrl-variacion-grid", "rowData"),
    Output("ctrl-variacion-message", "children"),
    Input("ctrl-start-period", "data"),
    Input("ctrl-end-period", "data"),
    Input("ctrl-umbral-variacion", "value"),
)
def update_variacion(start_period, end_period, umbral):
    if start_period is None or end_period is None:
        return [], "Seleccione un rango de períodos"
    start_period, end_period = sorted((int(start_period), int(end_period)))
    umbral = float(umbral) if umbral else 30.0
    try:
        df = get_variacion_mensual_anomala(start_period, end_period, umbral)
    except Exception as exc:
        return [], f"Error al consultar PostgreSQL: {exc}"
    if df.empty:
        return [], f"Ninguna variación mensual igual o mayor a {format_number(umbral)}% en el rango seleccionado."
    columnas = [
        "isp_nombre", "ruc_limpio", "anio_mes", "lineas_mes_anterior", "lineas_reportadas",
        "diferencia", "variacion_porcentaje",
    ]
    mensaje = f"{len(df):,} variaciones iguales o mayores a {format_number(umbral)}%".replace(",", ".")
    return clean_records(df[columnas]), mensaje
