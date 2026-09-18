"""dashboard/pages/conflictos_ruc_peva.py — Cola de conflictos RUC/PEVA para priorización de revisión.

SOLO LECTURA -- mismo criterio y misma decisión de arquitectura ya confirmada
para discrepancias_geografia.py (06-ago-2026, opción A: cero roles nuevos,
cero cambios al modelo de permisos de dashboard_lector). estado_revision se
muestra tal cual está en calidad.conflictos_ruc_peva, vía el puente
mart.vw_conflictos_ruc_peva (sql/10_patch_vw_conflictos_ruc_peva.sql). La
revisión real (confirmar, descartar, dejar notas) ocurre fuera de OBTEL, con
el rol calidad_revisor.

PROPÓSITO -- distinto de pages/control.py: Control mide inconsistencias de
REPORTE (prestadores que dejaron de reportar, variaciones anómalas -- afecta
la medición del mercado). Esta página mide inconsistencias de IDENTIDAD
(qué RUC corresponde a qué PEVA) que afectan la calidad de los DATOS MAESTROS
antes de llegar a cualquier cálculo de mercado. Categorías A/B/C, ver
sql/04_ddl_calidad.sql y mart/detectar_conflictos_peva.py:
  - A_DUPLICADO_MIGRACION_CODIFICACION: resolución automática (confiable,
    6 casos reales confirmados 28-jul-2026) -- normalmente NO queda
    pendiente por mucho tiempo, si aparece aquí como PENDIENTE es señal de
    que el pipeline de mart no ha vuelto a correr desde la detección.
  - B_SECUENCIA_MISMO_TITULAR / C_NOMBRES_DISTINTOS_MISMO_RUC: SIEMPRE
    requieren revisión manual -- son la cola de trabajo humano real de esta
    página.

SIN TERRITORIO: un conflicto RUC/PEVA no tiene columna de geografía propia
(no es un nodo físico) -- por eso esta página, a diferencia de Control o
Discrepancias de geografía, no tiene panel de Provincia/Cantón/Parroquia.

FILTRO POR DEFECTO: estado_revision arranca en ["PENDIENTE"] -- el objetivo
de esta página es mostrar qué priorizar HOY, no un historial completo. Ver
histórico completo (incluidos ya resueltos) requiere vaciar el filtro
explícitamente.
"""
from __future__ import annotations

import dash_ag_grid as dag
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html, register_page

from components.ui import (
    PALETTE, chart_card, clean_records, empty_figure, error_panel, excel_download_button,
    format_number, kpi_card, page_header, register_excel_download_callback, style_figure,
)
from services.queries import (
    get_conflictos_ruc_peva, get_conflictos_ruc_peva_categorias, get_conflictos_ruc_peva_estados,
)

register_page(__name__, path="/sai/conflictos-ruc-peva", name="Conflictos RUC/PEVA", order=5)
PREFIX = "cruc"

_CATEGORIA_LABELS = {
    "A_DUPLICADO_MIGRACION_CODIFICACION": "A · Duplicado por migración",
    "B_SECUENCIA_MISMO_TITULAR": "B · Secuencia mismo titular",
    "C_NOMBRES_DISTINTOS_MISMO_RUC": "C · Nombres distintos",
}
_ESTADO_COLORS = {
    "PENDIENTE": PALETTE["red"],
    "CONFIRMADO_AUTOMATICO": PALETTE["teal"],
    "CONFIRMADO_MANUAL": PALETTE["blue"],
    "DESCARTADO_MANUAL": PALETTE["muted"],
}


def layout():
    try:
        categoria_options = get_conflictos_ruc_peva_categorias()
        estado_options = get_conflictos_ruc_peva_estados()
    except Exception as exc:
        return html.Div([page_header("Conflictos RUC/PEVA", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Conflictos RUC/PEVA",
                "Cola de revisión de calidad de datos maestros -- RUC con más de un PEVA en conflicto. "
                "Solo lectura: la revisión (confirmar, descartar, dejar notas) ocurre fuera de OBTEL, "
                "con el rol calidad_revisor. Arranca mostrando solo lo PENDIENTE.",
            ),
            html.Section(
                className="filter-panel",
                children=[
                    html.Div(
                        className="territory-grid",
                        children=[
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Categoría"),
                                    dcc.Dropdown(
                                        id=f"{PREFIX}-categoria", options=categoria_options, value=[],
                                        multi=True, placeholder="Todas",
                                    ),
                                ],
                            ),
                            html.Div(
                                className="filter-field",
                                children=[
                                    html.Label("Estado de revisión"),
                                    dcc.Dropdown(
                                        id=f"{PREFIX}-estado", options=estado_options, value=["PENDIENTE"],
                                        multi=True, placeholder="Todos",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(id=f"{PREFIX}-message", className="data-message"),

            html.Section(
                className="kpi-grid four",
                children=[
                    kpi_card("Conflictos mostrados", f"{PREFIX}-kpi-total"),
                    kpi_card("Categoría B pendiente", f"{PREFIX}-kpi-b",
                             note_id=f"{PREFIX}-kpi-b-note"),
                    kpi_card("Categoría C pendiente", f"{PREFIX}-kpi-c",
                             note_id=f"{PREFIX}-kpi-c-note"),
                    kpi_card("Más antiguo sin revisar (días)", f"{PREFIX}-kpi-antiguedad"),
                ],
            ),

            html.Section(
                className="chart-grid two",
                style={"marginTop": "20px"},
                children=[
                    chart_card(
                        "Conflictos por categoría y estado", f"{PREFIX}-categoria-bar",
                        "Cuánto de cada categoría sigue pendiente vs. ya resuelto -- A se resuelve solo "
                        "en la siguiente corrida de mart; B y C siempre requieren revisión manual.",
                    ),
                    chart_card(
                        "Antigüedad de lo pendiente", f"{PREFIX}-antiguedad-bar",
                        "Días desde la detección -- lo más viejo es lo que más urge revisar primero.",
                    ),
                ],
            ),

            html.Section(
                className="chart-card",
                style={"marginTop": "20px"},
                children=[
                    html.Div(
                        className="chart-header",
                        children=[
                            html.H3("Detalle de conflictos", className="chart-title"),
                            html.P(
                                "estado_revision, revisado_por y notas_revision reflejan el workflow humano "
                                "(calidad_revisor), solo lectura desde aquí.",
                                className="chart-subtitle",
                            ),
                        ],
                    ),
                    dag.AgGrid(
                        id=f"{PREFIX}-grid",
                        columnDefs=[
                            {"field": "ruc_limpio", "headerName": "RUC", "minWidth": 140},
                            {"field": "categoria", "headerName": "Categoría", "minWidth": 220},
                            {"field": "isp_nombre_a", "headerName": "Prestador (PEVA A)", "minWidth": 200, "flex": 2},
                            {"field": "peva_a", "headerName": "PEVA A", "width": 110},
                            {"field": "isp_nombre_b", "headerName": "Prestador (PEVA B)", "minWidth": 200, "flex": 2},
                            {"field": "peva_b", "headerName": "PEVA B", "width": 110},
                            {"field": "coexisten_en_periodo", "headerName": "Coexisten", "width": 110},
                            {"field": "accion_recomendada", "headerName": "Acción recomendada", "minWidth": 190},
                            {"field": "estado_revision", "headerName": "Estado", "minWidth": 160},
                            {"field": "revisado_por", "headerName": "Revisado por", "minWidth": 150},
                            {"field": "fecha_deteccion", "headerName": "Detectado", "minWidth": 130},
                            {"field": "fecha_revision", "headerName": "Revisado", "minWidth": 130},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 10,
                                         "animateRows": True},
                        columnSize="responsiveSizeToFit",
                        style={"height": "480px", "width": "100%"},
                    ),
                    excel_download_button(f"{PREFIX}-grid"),
                ],
            ),
        ],
    )


register_excel_download_callback(f"{PREFIX}-grid", "conflictos_ruc_peva.xlsx")


@callback(
    Output(f"{PREFIX}-kpi-total", "children"),
    Output(f"{PREFIX}-kpi-b", "children"),
    Output(f"{PREFIX}-kpi-b-note", "children"),
    Output(f"{PREFIX}-kpi-c", "children"),
    Output(f"{PREFIX}-kpi-c-note", "children"),
    Output(f"{PREFIX}-kpi-antiguedad", "children"),
    Output(f"{PREFIX}-categoria-bar", "figure"),
    Output(f"{PREFIX}-antiguedad-bar", "figure"),
    Output(f"{PREFIX}-grid", "rowData"),
    Output(f"{PREFIX}-message", "children"),
    Input(f"{PREFIX}-categoria", "value"),
    Input(f"{PREFIX}-estado", "value"),
)
def update_conflictos(categorias, estados):
    try:
        df = get_conflictos_ruc_peva(tuple(categorias or ()), tuple(estados or ()))
    except Exception as exc:
        vacio = empty_figure("Error al consultar PostgreSQL")
        return "—", "—", "", "—", "", "—", vacio, vacio, [], f"Error al consultar PostgreSQL: {exc}"

    if df.empty:
        vacio = empty_figure("Ningún conflicto para estos filtros")
        return "0", "0", "", "0", "", "—", vacio, vacio, [], "0 conflictos para los filtros seleccionados."

    df = df.copy()
    df["fecha_deteccion"] = pd.to_datetime(df["fecha_deteccion"])
    df["fecha_revision"] = pd.to_datetime(df["fecha_revision"])

    pendientes = df[df["estado_revision"] == "PENDIENTE"]
    total = len(df)
    b_pendiente = len(pendientes[pendientes["categoria"] == "B_SECUENCIA_MISMO_TITULAR"])
    c_pendiente = len(pendientes[pendientes["categoria"] == "C_NOMBRES_DISTINTOS_MISMO_RUC"])

    if not pendientes.empty:
        dias = (pd.Timestamp.now() - pendientes["fecha_deteccion"]).dt.days
        antiguedad_max = int(dias.max())
        b_nota = f"de {len(df[df['categoria'] == 'B_SECUENCIA_MISMO_TITULAR']):,}".replace(",", ".") + " en total"
        c_nota = f"de {len(df[df['categoria'] == 'C_NOMBRES_DISTINTOS_MISMO_RUC']):,}".replace(",", ".") + " en total"
    else:
        antiguedad_max = 0
        b_nota = "sin pendientes"
        c_nota = "sin pendientes"

    # Barras apiladas por categoría/estado -- prioriza responder "¿cuánto
    # falta?" sobre "¿cuál es el más reciente?" (eso lo da la tabla).
    resumen = (
        df.groupby(["categoria", "estado_revision"]).size().reset_index(name="conteo")
    )
    categoria_fig = go.Figure()
    for estado in sorted(resumen["estado_revision"].unique()):
        sub = resumen[resumen["estado_revision"] == estado]
        categoria_fig.add_trace(go.Bar(
            x=[_CATEGORIA_LABELS.get(c, c) for c in sub["categoria"]],
            y=sub["conteo"],
            name=estado,
            marker_color=_ESTADO_COLORS.get(estado, PALETTE["muted"]),
            hovertemplate="%{x}<br>" + estado + ": %{y}<extra></extra>",
        ))
    categoria_fig.update_layout(barmode="stack", legend={"orientation": "h", "y": -0.2})
    style_figure(categoria_fig, height=360, hovermode="closest")
    categoria_fig.update_yaxes(title="Conflictos")

    if not pendientes.empty:
        pend_dias = pendientes.copy()
        pend_dias["dias_pendiente"] = (pd.Timestamp.now() - pend_dias["fecha_deteccion"]).dt.days
        top_antiguos = pend_dias.sort_values("dias_pendiente", ascending=False).head(15)
        top_antiguos = top_antiguos.sort_values("dias_pendiente")
        etiqueta = top_antiguos["ruc_limpio"] + " · " + top_antiguos["categoria"].map(
            lambda c: _CATEGORIA_LABELS.get(c, c)
        )
        antiguedad_fig = go.Figure(go.Bar(
            x=top_antiguos["dias_pendiente"], y=etiqueta, orientation="h",
            marker_color=PALETTE["red"],
            hovertemplate="%{y}<br>%{x} días pendiente<extra></extra>",
        ))
        style_figure(antiguedad_fig, height=420, hovermode="closest")
        antiguedad_fig.update_xaxes(title="Días desde la detección")
        antiguedad_fig.update_yaxes(title="")
    else:
        antiguedad_fig = empty_figure("Nada pendiente para estos filtros")

    mensaje = f"{total:,} conflictos mostrados ({len(pendientes):,} pendientes)".replace(",", ".")

    columnas = [
        "ruc_limpio", "categoria", "isp_nombre_a", "peva_a", "isp_nombre_b", "peva_b",
        "coexisten_en_periodo", "accion_recomendada", "estado_revision", "revisado_por",
        "fecha_deteccion", "fecha_revision",
    ]
    return (
        format_number(total), format_number(b_pendiente), b_nota, format_number(c_pendiente), c_nota,
        format_number(antiguedad_max), categoria_fig, antiguedad_fig, clean_records(df[columnas]), mensaje,
    )
