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
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html, register_page

from components.ui import (
    PALETTE, chart_card, clean_records, empty_figure, error_panel, excel_download_button, format_number,
    month_year_picker, numeric_stepper, page_header, register_excel_download_callback,
    register_month_year_picker_callback, style_figure,
)
from services.queries import (
    get_periods, get_prestadores_nunca_reportaron_detalle, get_prestadores_reporte_detenido_detalle,
    get_variacion_mensual_anomala,
)

register_page(__name__, path="/sai/control", name="Control", order=4)
PREFIX = "ctrl"


def _kpi_card_static(title: str, value: str, note: str = "") -> html.Div:
    """
    Igual que components/ui.py:kpi_card(), pero con el valor ya resuelto
    en vez de un placeholder "—" a la espera de un callback -- estas
    cuatro cifras se calculan una sola vez al construir el layout (no
    dependen de ningún filtro de la página), así que no necesitan
    Output/Input propios.
    """
    title_row = [html.Span(title, className="kpi-title-text")]
    if note:
        title_row.append(
            html.Div(
                className="kpi-info",
                children=[
                    html.Span("i", className="kpi-info-icon"),
                    html.Div(note, className="kpi-info-tooltip"),
                ],
            )
        )
    return html.Div(
        className="kpi-card",
        children=[
            html.Div(title_row, className="kpi-title-row"),
            html.Div(value, className="kpi-value"),
        ],
    )


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

    # "Prestadores que nunca han reportado" no depende de ningún filtro de
    # la página -- se calcula una sola vez al construir el layout, igual
    # que min_period/max_period arriba. CORRECCIÓN (11-ago-2026): antes
    # vivía en un @callback disparado con Input("ctrl-nunca-grid", "id"),
    # que NUNCA se ejecuta -- "id" no es una prop observable por el motor
    # de callbacks de Dash (a diferencia de "data"/"value"/"children").
    # Confirmado en producción: las 4 tarjetas KPI quedaban en "—" y la
    # tabla en "No Rows To Show" porque la función nunca corría.
    try:
        df_nunca = get_prestadores_nunca_reportaron_detalle()
    except Exception as exc:
        df_nunca = None
        error_nunca = str(exc)
    else:
        error_nunca = None

    if df_nunca is None:
        kpi_activo = kpi_no_operativo = kpi_zona_gris = kpi_total = "—"
        nota_kpi = f"No se pudo calcular: {error_nunca}"
        nunca_fig = empty_figure("No se pudo consultar PostgreSQL")
    elif df_nunca.empty:
        kpi_activo = kpi_no_operativo = kpi_zona_gris = kpi_total = "0"
        nota_kpi = ""
        nunca_fig = empty_figure("No hay prestadores sin reportar")
    else:
        conteos = df_nunca["clasificacion_incumplimiento"].value_counts()
        kpi_activo = format_number(int(conteos.get("activo_sin_reportar", 0)))
        kpi_no_operativo = format_number(int(conteos.get("no_operativo", 0)))
        kpi_zona_gris = format_number(int(conteos.get("zona_gris", 0)))
        kpi_total = format_number(len(df_nunca))
        nota_kpi = ""

        # Barras horizontales, no dona/pastel -- con solo 3 categorías el
        # objetivo es comparar magnitudes con precisión (104 vs 125 vs 56),
        # algo que un gráfico circular hace mal por diseño (el ojo humano
        # compara longitudes mucho mejor que ángulos/áreas). Orden fijo
        # (no por magnitud) para que la lectura sea siempre la misma:
        # el caso de incumplimiento real primero.
        categorias = ["activo_sin_reportar", "no_operativo", "zona_gris"]
        etiquetas = {
            "activo_sin_reportar": "Activo sin reportar",
            "no_operativo": "No operativo",
            "zona_gris": "Zona gris",
        }
        colores = {
            "activo_sin_reportar": PALETTE["red"],
            "no_operativo": PALETTE["muted"],
            "zona_gris": PALETTE["cyan"],
        }
        valores = [int(conteos.get(c, 0)) for c in categorias]
        nunca_fig = go.Figure(go.Bar(
            x=valores, y=[etiquetas[c] for c in categorias], orientation="h",
            marker_color=[colores[c] for c in categorias],
            text=valores, textposition="outside",
            hovertemplate="%{y}: %{x}<extra></extra>",
        ))
        style_figure(nunca_fig, height=230, hovermode="closest")
        nunca_fig.update_xaxes(title="Prestadores")
        nunca_fig.update_yaxes(title="")

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
                    _kpi_card_static(
                        "Activo sin reportar", kpi_activo,
                        nota_kpi or "Título vigente, opera, cero reportes -- el caso de incumplimiento real",
                    ),
                    _kpi_card_static(
                        "No operativo", kpi_no_operativo,
                        nota_kpi or "Cancelado/revocado -- nunca llegó a operar, universo administrativo distinto",
                    ),
                    _kpi_card_static(
                        "Zona gris", kpi_zona_gris,
                        nota_kpi or "Estado ambiguo en 'opera' -- requiere revisión caso por caso",
                    ),
                    _kpi_card_static(
                        "Total", kpi_total,
                        nota_kpi or "Total de prestadores con título habilitante y cero reportes en toda su historia",
                    ),
                ],
            ),
            html.Section(
                className="chart-card",
                children=[
                    html.Div(
                        className="chart-header",
                        children=[html.H3("Distribución por clasificación", className="chart-title")],
                    ),
                    dcc.Graph(figure=nunca_fig, config={"displaylogo": False}),
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
                        rowData=clean_records(df_nunca) if df_nunca is not None and not df_nunca.empty else [],
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

            html.H3("Variación mensual anómala en cuentas reportadas", style={"marginTop": "28px"}),
            html.Div(
                className="filter-panel",
                children=[
                    html.Div(
                        className="period-grid four-periods",
                        children=[
                            month_year_picker("ctrl-start-period", "Desde", min_period, min_period, max_period),
                            month_year_picker("ctrl-end-period", "Hasta", max_period, min_period, max_period),
                            numeric_stepper("ctrl-umbral-variacion", "Umbral de variación (%)", 30, min_value=1),
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


register_excel_download_callback("ctrl-nunca-grid", "prestadores_sin_reportar.xlsx")
register_excel_download_callback("ctrl-detenido-grid", "prestadores_reporte_detenido.xlsx")
register_excel_download_callback("ctrl-variacion-grid", "variacion_mensual_anomala.xlsx")
register_month_year_picker_callback("ctrl-start-period")
register_month_year_picker_callback("ctrl-end-period")


@callback(
    Output("ctrl-detenido-grid", "rowData"),
    Output("ctrl-detenido-message", "children"),
    Output("ctrl-detenido-hist", "figure"),
    Output("ctrl-detenido-scatter", "figure"),
    Input("ctrl-meses-minimo", "value"),
)
def update_reporte_detenido(meses_minimo):
    meses_minimo = int(meses_minimo) if meses_minimo else 1
    try:
        df = get_prestadores_reporte_detenido_detalle(meses_minimo)
    except Exception as exc:
        vacio = empty_figure("Error al consultar PostgreSQL")
        return [], f"Error al consultar PostgreSQL: {exc}", vacio, vacio
    if df.empty:
        vacio = empty_figure(f"Ningún prestador con {meses_minimo} o más meses sin reportar")
        return [], f"Ningún prestador con {meses_minimo} o más meses sin reportar.", vacio, vacio

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
    Input("ctrl-start-period", "data"),
    Input("ctrl-end-period", "data"),
    Input("ctrl-umbral-variacion", "value"),
)
def update_variacion(start_period, end_period, umbral):
    if start_period is None or end_period is None:
        vacio = empty_figure("Seleccione un rango de períodos")
        return [], "Seleccione un rango de períodos", vacio, vacio
    start_period, end_period = sorted((int(start_period), int(end_period)))
    umbral = float(umbral) if umbral else 30.0
    try:
        df = get_variacion_mensual_anomala(start_period, end_period, umbral)
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
    # de partida de triage, más accionable que una tabla de 6.000 filas
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
    # El hover siempre muestra el % real, sin transformar.
    df["variacion_transformada"] = np.sign(df["variacion_porcentaje"]) * np.log10(1 + df["variacion_porcentaje"].abs())
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
    tiempo_fig.update_yaxes(title="Variación % (escala log, signo preservado)", zeroline=True, zerolinecolor="#c7d2dc")

    columnas = [
        "isp_nombre", "ruc_limpio", "anio_mes", "lineas_mes_anterior", "lineas_reportadas",
        "diferencia", "variacion_porcentaje",
    ]
    mensaje = f"{len(df):,} variaciones iguales o mayores a {format_number(umbral)}%".replace(",", ".")
    return clean_records(df[columnas]), mensaje, ranking_fig, tiempo_fig
