"""dashboard/pages/conciliacion_siger.py — Conciliación SIGER ↔ SIETEL por RUC (08-oct-2026).

Responde el requerimiento "qué coincide entre SIETEL y SIGER en prestador,
RUC y estado de operación". Una fila por RUC del universo OBTEL ∪ SIGER con
título SAI VIGENTE, desde calidad.conciliacion_siger_obtel vía el puente de
solo lectura mart.vw_conciliacion_siger_obtel (dashboard_lector solo lee
mart; nunca el esquema siger). Se recalcula a diario en siger_pipeline
(siger/construir_cruce_obtel.py, reglas en siger/reglas.py).

Reglas (fijadas con siger/perfilar_cruce.py, 08-oct-2026):
  - RUC: solo dígitos en ambos lados (todos los de OBTEL tienen 13).
  - Nombre: similitud normalizada -> COINCIDE >= 0,90 (incluye un nombre
    contenido en el otro), PARECIDO >= 0,50, DIFIERE.
  - Estado: SIETEL OPERANDO (Nuevo, Opera Normalmente, SI, Opera
    Irregularmente) / NO_OPERA (Cancelación, NO) / INDETERMINADO (Otro
    Estado) frente al THESTADO REAL del título SAI de referencia en SIGER;
    solo VIGENTE cuenta como habilitado.

SOLO LECTURA, igual que Conflictos RUC/PEVA: la página no corrige nada. La
cola de revisión con workflow sigue siendo calidad.hallazgos_siger_obtel.
Muestra los nombres de SIGER de personas naturales (decisión del usuario,
08-oct-2026), como OBTEL ya muestra isp_nombre; nunca la cédula.
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
from services.queries import get_conciliacion_estados_siger, get_conciliacion_siger

register_page(__name__, path="/sai/conciliacion-siger", name="Conciliación SIGER", order=6)
PREFIX = "csig"

# De la más leve a la más grave: orden de las barras y del filtro.
_CATEGORIAS = {
    "COINCIDE": ("Coincide en todo", PALETTE["teal"]),
    "ESTADO_INDETERMINADO": ("Estado indeterminado en SIETEL", PALETTE["muted"]),
    "REVISAR_NOMBRE": ("Revisar nombre (parecido)", PALETTE["orange"]),
    "DIFIERE_ESTADO": ("Difiere el estado", PALETTE["red"]),
    "DIFIERE_NOMBRE": ("Difiere el nombre", PALETTE["red"]),
    "DIFIERE_NOMBRE_Y_ESTADO": ("Difieren nombre y estado", PALETTE["navy"]),
    "SOLO_SIETEL": ("Solo en SIETEL (RUC no existe en SIGER)", PALETTE["blue"]),
    "SOLO_SIGER": ("Solo en SIGER (SAI vigente sin PEVA)", PALETTE["cyan"]),
}
_ESTADOS_SIETEL = {
    "OPERANDO": ("Opera", PALETTE["teal"]),
    "NO_OPERA": ("No opera", PALETTE["red"]),
    "INDETERMINADO": ("Indeterminado", PALETTE["muted"]),
}
_COLUMNAS = [
    "ruc_limpio", "categoria", "nombre_sietel", "nombre_siger", "similitud_nombre", "nivel_nombre",
    "pevas_sietel", "opera_sietel", "estado_sietel", "reporta_sietel", "ultimo_periodo_sietel",
    "estado_siger", "estados_siger", "vigencia_siger", "ucp_concnums", "ruc_por_cedula_001",
    "coincide_estado", "coincide_reporte",
]


def _filtro(label: str, componente) -> html.Div:
    return html.Div(className="filter-field", children=[html.Label(label), componente])


def layout():
    try:
        estados_siger = get_conciliacion_estados_siger()
    except Exception as exc:
        return html.Div([page_header("Conciliación SIGER ↔ SIETEL", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Conciliación SIGER ↔ SIETEL",
                "Qué coincide entre los títulos habilitantes de SIGER y los prestadores de SIETEL, por RUC: "
                "nombre del prestador y estado de operación (SIETEL opera ↔ título SAI VIGENTE en SIGER). "
                "Solo lectura; se recalcula cada día.",
            ),
            html.Section(
                className="filter-panel",
                children=[
                    html.Div(
                        className="territory-grid",
                        children=[
                            _filtro("Categoría", dcc.Dropdown(
                                id=f"{PREFIX}-categoria", multi=True, placeholder="Todas", value=[],
                                options=[{"label": v[0], "value": k} for k, v in _CATEGORIAS.items()],
                            )),
                            _filtro("Estado en SIETEL", dcc.Dropdown(
                                id=f"{PREFIX}-estado-sietel", multi=True, placeholder="Todos", value=[],
                                options=[{"label": v[0], "value": k} for k, v in _ESTADOS_SIETEL.items()],
                            )),
                            _filtro("Estado del título en SIGER", dcc.Dropdown(
                                id=f"{PREFIX}-estado-siger", multi=True, placeholder="Todos", value=[],
                                options=estados_siger,
                            )),
                            _filtro("Buscar RUC o nombre", dcc.Input(
                                id=f"{PREFIX}-buscar", type="text", debounce=True, placeholder="RUC o nombre",
                                style={"width": "100%"},
                            )),
                        ],
                    ),
                ],
            ),
            html.Div(id=f"{PREFIX}-message", className="data-message"),

            html.Section(
                className="kpi-grid five",
                children=[
                    kpi_card("RUC en ambas fuentes", f"{PREFIX}-kpi-ambos", note_id=f"{PREFIX}-kpi-ambos-note"),
                    kpi_card("Coinciden en todo", f"{PREFIX}-kpi-coincide", note_id=f"{PREFIX}-kpi-coincide-note"),
                    kpi_card("Difiere el estado", f"{PREFIX}-kpi-estado", note_id=f"{PREFIX}-kpi-estado-note"),
                    kpi_card("Nombre a revisar o distinto", f"{PREFIX}-kpi-nombre",
                             note_id=f"{PREFIX}-kpi-nombre-note"),
                    kpi_card("Solo en una fuente", f"{PREFIX}-kpi-solo", note_id=f"{PREFIX}-kpi-solo-note"),
                ],
            ),

            html.Section(
                className="chart-grid two",
                style={"marginTop": "20px"},
                children=[
                    chart_card(
                        "RUC por categoría", f"{PREFIX}-categoria-bar",
                        "Cada RUC cae en una sola categoría, de la más grave a la más leve: primero si está en "
                        "una sola fuente, después nombre y estado.",
                    ),
                    chart_card(
                        "Estado en SIETEL según el estado del título en SIGER", f"{PREFIX}-estado-bar",
                        "Solo RUC presentes en ambas fuentes. Coincide cuando SIETEL opera y el título está "
                        "VIGENTE, o cuando no opera y el título no está VIGENTE.",
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
                            html.H3("Detalle por RUC", className="chart-title"),
                            html.P(
                                "estado_siger es el THESTADO real del título SAI de referencia (el VIGENTE si "
                                "hay; si no, el más reciente); estados_siger resume todos sus títulos SAI.",
                                className="chart-subtitle",
                            ),
                        ],
                    ),
                    dag.AgGrid(
                        id=f"{PREFIX}-grid",
                        columnDefs=[
                            {"field": "ruc_limpio", "headerName": "RUC", "minWidth": 140, "pinned": "left"},
                            {"field": "categoria", "headerName": "Categoría", "minWidth": 190},
                            {"field": "nombre_sietel", "headerName": "Prestador (SIETEL)", "minWidth": 220, "flex": 2},
                            {"field": "nombre_siger", "headerName": "Concesionario (SIGER)", "minWidth": 220,
                             "flex": 2},
                            {"field": "similitud_nombre", "headerName": "Similitud", "width": 110},
                            {"field": "nivel_nombre", "headerName": "Nombre", "width": 120},
                            {"field": "estado_sietel", "headerName": "Estado SIETEL", "minWidth": 140},
                            {"field": "opera_sietel", "headerName": "opera (SIETEL)", "minWidth": 160},
                            {"field": "estado_siger", "headerName": "Estado título (SIGER)", "minWidth": 200},
                            {"field": "coincide_estado", "headerName": "Coincide estado", "width": 140},
                            {"field": "reporta_sietel", "headerName": "Reporta", "width": 110},
                            {"field": "ultimo_periodo_sietel", "headerName": "Último período", "width": 130},
                            {"field": "coincide_reporte", "headerName": "Coincide reporte", "width": 140},
                            {"field": "pevas_sietel", "headerName": "PEVA", "minWidth": 130},
                            {"field": "estados_siger", "headerName": "Títulos SAI (SIGER)", "minWidth": 220},
                            {"field": "vigencia_siger", "headerName": "Vigencia título", "minWidth": 130},
                            {"field": "ucp_concnums", "headerName": "Código SIGER", "minWidth": 120},
                            {"field": "ruc_por_cedula_001", "headerName": "RUC = cédula + 001", "width": 150},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 15,
                                         "animateRows": True},
                        style={"height": "560px", "width": "100%"},
                    ),
                    excel_download_button(f"{PREFIX}-grid"),
                ],
            ),
        ],
    )


register_excel_download_callback(f"{PREFIX}-grid", "conciliacion_siger_sietel.xlsx")


def _nota(n: int, total: int, texto: str = "de los RUC en ambas fuentes") -> str:
    return f"{100 * n / total:.1f} % {texto}".replace(".", ",") if total else ""


@callback(
    Output(f"{PREFIX}-kpi-ambos", "children"),
    Output(f"{PREFIX}-kpi-ambos-note", "children"),
    Output(f"{PREFIX}-kpi-coincide", "children"),
    Output(f"{PREFIX}-kpi-coincide-note", "children"),
    Output(f"{PREFIX}-kpi-estado", "children"),
    Output(f"{PREFIX}-kpi-estado-note", "children"),
    Output(f"{PREFIX}-kpi-nombre", "children"),
    Output(f"{PREFIX}-kpi-nombre-note", "children"),
    Output(f"{PREFIX}-kpi-solo", "children"),
    Output(f"{PREFIX}-kpi-solo-note", "children"),
    Output(f"{PREFIX}-categoria-bar", "figure"),
    Output(f"{PREFIX}-estado-bar", "figure"),
    Output(f"{PREFIX}-grid", "rowData"),
    Output(f"{PREFIX}-message", "children"),
    Input(f"{PREFIX}-categoria", "value"),
    Input(f"{PREFIX}-estado-sietel", "value"),
    Input(f"{PREFIX}-estado-siger", "value"),
    Input(f"{PREFIX}-buscar", "value"),
)
def update_conciliacion(categorias, estados_sietel, estados_siger, buscar):
    try:
        df = get_conciliacion_siger(tuple(categorias or ()))
    except Exception as exc:
        vacio = empty_figure("Error al consultar PostgreSQL")
        return ("—", "", "—", "", "—", "", "—", "", "—", "", vacio, vacio, [],
                f"Error al consultar PostgreSQL: {exc}")

    if estados_sietel:
        df = df[df["estado_sietel"].isin(estados_sietel)]
    if estados_siger:
        df = df[df["estado_siger"].isin(estados_siger)]
    if buscar and buscar.strip():
        q = buscar.strip()
        df = df[
            df["ruc_limpio"].str.contains(q, regex=False, na=False)
            | df["nombre_sietel"].str.contains(q, case=False, regex=False, na=False)
            | df["nombre_siger"].str.contains(q, case=False, regex=False, na=False)
        ]

    if df.empty:
        vacio = empty_figure("Ningún RUC para estos filtros")
        return ("0", "", "0", "", "0", "", "0", "", "0", "", vacio, vacio, [],
                "0 RUC para los filtros seleccionados.")

    df = df.copy()
    df["vigencia_siger"] = pd.to_datetime(df["vigencia_siger"]).dt.date
    conteo = df["categoria"].value_counts()
    ambos = int((df["en_sietel"] & df["en_siger"]).sum())
    coincide = int(conteo.get("COINCIDE", 0))
    difiere_estado = int(conteo.get("DIFIERE_ESTADO", 0) + conteo.get("DIFIERE_NOMBRE_Y_ESTADO", 0))
    nombre = int(conteo.get("REVISAR_NOMBRE", 0) + conteo.get("DIFIERE_NOMBRE", 0)
                 + conteo.get("DIFIERE_NOMBRE_Y_ESTADO", 0))
    solo_sietel, solo_siger = int(conteo.get("SOLO_SIETEL", 0)), int(conteo.get("SOLO_SIGER", 0))

    # Barras por categoría, en el orden de _CATEGORIAS (más leve arriba).
    cats = [c for c in reversed(_CATEGORIAS) if c in conteo]
    categoria_fig = go.Figure(go.Bar(
        x=[int(conteo[c]) for c in cats], y=[_CATEGORIAS[c][0] for c in cats], orientation="h",
        marker_color=[_CATEGORIAS[c][1] for c in cats],
        hovertemplate="%{y}<br>%{x} RUC<extra></extra>",
    ))
    style_figure(categoria_fig, height=380, hovermode="closest")
    categoria_fig.update_xaxes(title="RUC")
    categoria_fig.update_yaxes(title="")

    en_ambos = df[df["en_sietel"] & df["en_siger"]]
    if not en_ambos.empty:
        cruce = en_ambos.groupby(["estado_siger", "estado_sietel"]).size().unstack(fill_value=0)
        cruce = cruce.loc[cruce.sum(axis=1).sort_values(ascending=False).index]
        estado_fig = go.Figure()
        for estado, (etiqueta, color) in _ESTADOS_SIETEL.items():
            if estado in cruce.columns:
                estado_fig.add_trace(go.Bar(
                    x=cruce.index, y=cruce[estado], name=f"SIETEL: {etiqueta}", marker_color=color,
                    hovertemplate="SIGER %{x}<br>" + etiqueta + ": %{y} RUC<extra></extra>",
                ))
        estado_fig.update_layout(barmode="stack", legend={"orientation": "h", "y": -0.35})
        style_figure(estado_fig, height=380, hovermode="closest")
        estado_fig.update_yaxes(title="RUC")
        estado_fig.update_xaxes(title="", tickangle=-30)
    else:
        estado_fig = empty_figure("Ningún RUC presente en ambas fuentes para estos filtros")

    mensaje = f"{len(df):,} RUC mostrados".replace(",", ".")
    fecha = df["fecha_calculo"].max()
    if pd.notna(fecha):
        mensaje += f" · calculado el {pd.to_datetime(fecha):%d/%m/%Y %H:%M}"

    return (
        format_number(ambos), f"de {format_number(len(df))} RUC mostrados",
        format_number(coincide), _nota(coincide, ambos),
        format_number(difiere_estado), _nota(difiere_estado, ambos),
        format_number(nombre), _nota(nombre, ambos),
        format_number(solo_sietel + solo_siger),
        f"{format_number(solo_sietel)} solo SIETEL · {format_number(solo_siger)} solo SIGER",
        categoria_fig, estado_fig, clean_records(df[_COLUMNAS]), mensaje,
    )
