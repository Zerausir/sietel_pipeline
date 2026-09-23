"""dashboard/pages/prioridad_carga.py — A quién priorizar para cargar información, por peso en Estadísticas/Control.

SOLO LECTURA. Distinto de Conflictos RUC/PEVA y Discrepancias de
geografía (causas raíz de identidad) -- esta página no busca causas, mide
IMPACTO: de los prestadores que no están reportando hoy, ¿cuáles pesan
tanto que su ausencia distorsiona Evolución e IHH? El caso CNT es el
ejemplo real que motivó esto (hasta 90% de participación histórica,
ausente desde jul-2024) -- confirmado en pantalla filtrando Evolución por
ese prestador: la serie cae a cero en los meses sin su reporte.

DOS POBLACIONES, DOS LÓGICAS DE ORDEN (no se pueden mezclar en un solo
ranking -- ver discusión con el usuario, 23-sep-2026):
  - "Reporte detenido": SÍ tiene una magnitud real (total_lineas_historico,
    ya en mart.vw_prestadores_reporte_detenido) -- se ordena por peso,
    mayor a menor, SIN el umbral de materialidad (>100.000 cuentas) que
    usa el KPI "Universo consolidado" de Control. Aquí va la lista
    COMPLETA, nadie queda afuera por chico.
  - "Nunca han reportado": SIETEL no tiene ningún número de estos
    prestadores -- nunca llegó un reporte, no hay cuentas que pesar. No
    existe una forma honesta de ordenarlos por magnitud. Se ordenan por
    antigüedad de la obligación (fecha de permiso, el más viejo primero)
    -- el único criterio ordinal que sí existe para ellos. Acotado a
    clasificacion_incumplimiento == 'activo_sin_reportar' (opera con
    título vigente) -- no tiene sentido "priorizar la carga" de alguien
    cancelado/revocado (no_operativo) o en estado ambiguo (zona_gris) sin
    revisión manual previa.

DOMINANCIA (23-sep-2026): cualquier prestador (en cualquiera de las dos
listas) que alguna vez alcanzó >=30% de participación nacional -- mismo
umbral ya verificado con CNT en mart.fact_ihh_geografico -- se marca
aparte y sube al tope del heatmap sin importar su posición por peso puro.
Es la señal más fuerte de "esto rompe Estadísticas de verdad", no solo
"es grande".

HEATMAP: acotado a los ~25 prestadores de mayor peso (dominantes primero)
de "reporte detenido" -- un heatmap con los 500+ prestadores completos
sería ilegible, no es un límite de datos (la tabla de abajo sí trae a
todos). Fuente: tiene_reportado por (prestador_id, periodo_id) desde
mart.fact_lineas_geografia_mes, vía get_calendario_reportes() --
mismo patrón BOOL_OR ya usado en Control/Evolución. Los meses de la
"cola" (después de ultimo_periodo_reportado) no tienen fila en absoluto
en fact_lineas_geografia_mes (capa2 nunca extrapola hacia adelante) --
se completan aquí en Python como "no reportado" al armar la grilla
completa desde primer_periodo_reportado hasta el último período
disponible.

"Nunca han reportado" NO tiene heatmap -- no hay un solo período de datos
que marcar (ver arriba). Su "acción requerida" es una frase fija, no un
calendario.
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
    get_calendario_reportes, get_operation_states, get_periods, get_prestadores_dominantes_historicos,
    get_prestadores_nunca_reportaron_detalle, get_prestadores_reporte_detenido_detalle,
)

register_page(__name__, path="/sai/prioridad-carga", name="Prioridad de carga", order=8)
PREFIX = "prio"
TOP_HEATMAP = 25


def layout():
    try:
        get_periods()
    except Exception as exc:
        return html.Div([page_header("Prioridad de carga", ""), error_panel(str(exc))])

    return html.Div(
        children=[
            page_header(
                "Prioridad de carga",
                "A quién perseguir primero para cargar información, según cuánto pesa su ausencia en "
                "Evolución e IHH -- no por antigüedad de la falta. Solo lectura.",
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
                                    html.Label("Estado de operación"),
                                    dcc.Dropdown(
                                        id=f"{PREFIX}-opera-estado", options=get_operation_states(), value=[],
                                        multi=True, placeholder="Todos",
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            html.P(
                "Aplica a las dos secciones -- sin nada elegido, incluye TODOS los estados (Opera Normalmente, "
                "Cancelación, Nuevo, etc.), incluidos cancelados/revocados. Un prestador cancelado con mucho "
                "peso histórico puede seguir apareciendo con prioridad alta si no se excluye aquí a propósito -- "
                "esta página no lo excluye por defecto, deja la decisión al usuario, mismo criterio que Control.",
                className="chart-subtitle",
            ),

            html.H3("Reporte detenido — ordenado por peso histórico"),
            html.Section(
                className="kpi-grid three",
                children=[
                    kpi_card("Prestadores detenidos", f"{PREFIX}-kpi-total-detenido"),
                    kpi_card("Dominantes ausentes (≥30% histórico)", f"{PREFIX}-kpi-dominantes",
                             note_id=f"{PREFIX}-kpi-dominantes-note"),
                    kpi_card("Cuentas históricas en juego", f"{PREFIX}-kpi-cuentas-historicas",
                             note_id=f"{PREFIX}-kpi-cuentas-historicas-note"),
                ],
            ),
            html.Div(id=f"{PREFIX}-detenido-message", className="data-message"),

            html.Section(
                className="chart-card",
                style={"marginTop": "20px"},
                children=[
                    html.Div(
                        className="chart-header",
                        children=[
                            html.H3(f"Calendario de reportes — top {TOP_HEATMAP} por peso", className="chart-title"),
                            html.P(
                                "Verde = reportó ese mes. Rojo = no reportó (incluye huecos interiores rellenados "
                                "por LOCF y la cola de meses sin reporte). Dominantes primero, sin importar su "
                                "posición por peso puro -- acotado a los de mayor prioridad, la tabla de abajo "
                                "trae a todos sin excepción.",
                                className="chart-subtitle",
                            ),
                        ],
                    ),
                    dcc.Loading(dcc.Graph(id=f"{PREFIX}-heatmap", config={"displaylogo": False}), type="circle"),
                ],
            ),

            html.Section(
                className="table-card",
                style={"marginTop": "20px"},
                children=[
                    html.H3("Detalle completo — sin umbral de tamaño"),
                    dag.AgGrid(
                        id=f"{PREFIX}-detenido-grid",
                        columnDefs=[
                            {"field": "isp_nombre", "headerName": "Prestador", "minWidth": 240, "flex": 2},
                            {"field": "ruc_limpio", "headerName": "RUC", "minWidth": 150},
                            {"field": "dominante", "headerName": "Dominante histórico", "minWidth": 150},
                            {"field": "ultimo_periodo_reportado", "headerName": "Último reporte", "minWidth": 140},
                            {"field": "meses_desde_ultimo_reporte", "headerName": "Meses sin reportar",
                             "type": "numericColumn", "minWidth": 150},
                            {"field": "total_lineas_historico", "headerName": "Cuentas históricas (peso)",
                             "type": "numericColumn", "minWidth": 180},
                            {"field": "accion", "headerName": "Acción requerida", "minWidth": 260, "flex": 2},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 10,
                                         "animateRows": True},
                        columnSize="responsiveSizeToFit",
                        style={"height": "480px", "width": "100%"},
                    ),
                    excel_download_button(f"{PREFIX}-detenido-grid"),
                ],
            ),

            html.H3("Nunca han reportado — ordenado por antigüedad de la obligación", style={"marginTop": "32px"}),
            html.P(
                "Sin heatmap: SIETEL no tiene un solo dato de estos prestadores, no hay período que marcar. "
                "Sin peso: nunca llegó un reporte, no hay cuentas que pesar -- se ordenan por fecha de permiso, "
                "el más antiguo primero. Acotado a 'activo sin reportar' (título vigente) -- no incluye "
                "cancelados/revocados ni casos de estado ambiguo, que no son objetivo de carga.",
                className="chart-subtitle",
            ),
            html.Section(
                className="kpi-grid two",
                children=[
                    kpi_card("Activo sin reportar", f"{PREFIX}-kpi-nunca-total"),
                    kpi_card("Más antiguo (años en incumplimiento)", f"{PREFIX}-kpi-nunca-antiguedad"),
                ],
            ),
            html.Section(
                className="table-card",
                style={"marginTop": "20px"},
                children=[
                    dag.AgGrid(
                        id=f"{PREFIX}-nunca-grid",
                        columnDefs=[
                            {"field": "peva_codigo", "headerName": "PEVA", "minWidth": 110},
                            {"field": "isp_nombre", "headerName": "Prestador", "minWidth": 240, "flex": 2},
                            {"field": "isp_ruc", "headerName": "RUC", "minWidth": 150},
                            {"field": "fechapermiso", "headerName": "Fecha de permiso", "minWidth": 140},
                            {"field": "fuera_de_gracia", "headerName": "Fuera de año de gracia", "minWidth": 170},
                            {"field": "accion", "headerName": "Acción requerida", "minWidth": 300, "flex": 2},
                        ],
                        rowData=[],
                        defaultColDef={"sortable": True, "filter": True, "resizable": True},
                        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 10,
                                         "animateRows": True},
                        columnSize="responsiveSizeToFit",
                        style={"height": "420px", "width": "100%"},
                    ),
                    excel_download_button(f"{PREFIX}-nunca-grid"),
                ],
            ),
        ],
    )


register_excel_download_callback(f"{PREFIX}-detenido-grid", "prioridad_carga_reporte_detenido.xlsx")
register_excel_download_callback(f"{PREFIX}-nunca-grid", "prioridad_carga_nunca_reportaron.xlsx")


@callback(
    Output(f"{PREFIX}-kpi-total-detenido", "children"),
    Output(f"{PREFIX}-kpi-dominantes", "children"),
    Output(f"{PREFIX}-kpi-dominantes-note", "children"),
    Output(f"{PREFIX}-kpi-cuentas-historicas", "children"),
    Output(f"{PREFIX}-kpi-cuentas-historicas-note", "children"),
    Output(f"{PREFIX}-detenido-message", "children"),
    Output(f"{PREFIX}-heatmap", "figure"),
    Output(f"{PREFIX}-detenido-grid", "rowData"),
    Input(f"{PREFIX}-opera-estado", "value"),
)
def update_reporte_detenido(opera_estados):
    try:
        # Sin umbral de meses (1 = mínimo posible, lista completa) --
        # opera_estados sí se aplica, a diferencia del resto de la
        # página: es el filtro nuevo, "Todos" (lista vacía) por defecto.
        df = get_prestadores_reporte_detenido_detalle(1, opera_estados=tuple(opera_estados or ()))
    except Exception as exc:
        vacio = empty_figure("Error al consultar PostgreSQL")
        return "—", "—", "", "—", "", f"Error al consultar PostgreSQL: {exc}", vacio, []

    if df.empty:
        vacio = empty_figure("Ningún prestador con reporte detenido")
        return "0", "0", "", "0", "", "0 prestadores con reporte detenido.", vacio, []

    df = df.copy()
    df["total_lineas_historico"] = pd.to_numeric(df["total_lineas_historico"], errors="coerce").fillna(0)
    dominantes = get_prestadores_dominantes_historicos()
    df["es_dominante"] = df["prestador_id"].isin(dominantes)

    df = df.sort_values(["es_dominante", "total_lineas_historico"], ascending=[False, False])

    total = len(df)
    n_dominantes = int(df["es_dominante"].sum())
    cuentas_totales = int(df["total_lineas_historico"].sum())

    mensaje = f"{total:,} prestadores con reporte detenido, sin umbral de tamaño".replace(",", ".")

    # --- Heatmap: top N (dominantes primero) ---
    top = df.head(TOP_HEATMAP).copy()
    periods = get_periods()[["periodo_id", "anio_mes"]].sort_values("periodo_id")
    max_periodo_id = int(periods["periodo_id"].max())

    top["primer_periodo_reportado"] = pd.to_datetime(top["primer_periodo_reportado"])
    top["_inicio_periodo_id"] = (
            top["primer_periodo_reportado"].dt.year * 100 + top["primer_periodo_reportado"].dt.month
    )

    if top.empty:
        heatmap_fig = empty_figure("Ningún prestador para el heatmap")
    else:
        try:
            calendario = get_calendario_reportes(tuple(top["prestador_id"]))
        except Exception:
            calendario = pd.DataFrame(columns=["prestador_id", "periodo_id", "tiene_reportado"])

        filas_z: list[list[float]] = []
        etiquetas_y: list[str] = []
        for _, fila in top.iterrows():
            pid = fila["prestador_id"]
            inicio = int(fila["_inicio_periodo_id"])
            ventana = periods[(periods["periodo_id"] >= inicio) & (periods["periodo_id"] <= max_periodo_id)]
            sub_cal = calendario[calendario["prestador_id"] == pid][["periodo_id", "tiene_reportado"]]
            serie = ventana.merge(sub_cal, on="periodo_id", how="left")
            serie["tiene_reportado"] = serie["tiene_reportado"].fillna(False)
            fila_z = [1.0 if v else 0.0 for v in serie["tiene_reportado"]]
            # Alinea cada fila al eje X global (todos los períodos disponibles) --
            # NaN para los meses anteriores a que este prestador empezara a reportar.
            mapa = dict(zip(serie["periodo_id"], fila_z))
            fila_completa = [mapa.get(pid_periodo, float("nan")) for pid_periodo in periods["periodo_id"]]
            filas_z.append(fila_completa)
            marca = " ★" if fila["es_dominante"] else ""
            etiquetas_y.append(f"{fila['isp_nombre']}{marca}")

        heatmap_fig = go.Figure(go.Heatmap(
            z=filas_z, x=periods["anio_mes"], y=etiquetas_y,
            colorscale=[[0, PALETTE["red"]], [1, PALETTE["teal"]]],
            zmin=0, zmax=1, showscale=False,
            hovertemplate="%{y}<br>%{x}<br>%{z}<extra></extra>",
            xgap=1, ygap=2,
        ))
        style_figure(heatmap_fig, height=max(320, 28 * len(etiquetas_y) + 80), hovermode="closest")
        heatmap_fig.update_xaxes(title="Período", tickangle=-45)
        heatmap_fig.update_yaxes(title="", autorange="reversed")

    # --- Tabla completa ---
    df["dominante"] = df["es_dominante"].map({True: "★ Sí", False: "No"})
    df["accion"] = df.apply(
        lambda r: (
                f"Priorizar carga -- pesa {format_number(r['total_lineas_historico'])} cuentas históricas"
                + (", dominante nacional histórico" if r["es_dominante"] else "")
        ),
        axis=1,
    )
    columnas = [
        "isp_nombre", "ruc_limpio", "dominante", "ultimo_periodo_reportado",
        "meses_desde_ultimo_reporte", "total_lineas_historico", "accion",
    ]

    return (
        format_number(total),
        format_number(n_dominantes), "≥30% de participación nacional en algún momento de su historia",
        format_number(cuentas_totales), "Suma de cuentas históricas de todos los prestadores detenidos",
        mensaje, heatmap_fig, clean_records(df[columnas]),
    )


@callback(
    Output(f"{PREFIX}-kpi-nunca-total", "children"),
    Output(f"{PREFIX}-kpi-nunca-antiguedad", "children"),
    Output(f"{PREFIX}-nunca-grid", "rowData"),
    Input(f"{PREFIX}-opera-estado", "value"),
)
def update_nunca_reportaron(opera_estados):
    try:
        df = get_prestadores_nunca_reportaron_detalle(tuple(opera_estados or ()))
    except Exception:
        return "—", "—", []

    if df.empty:
        return "0", "—", []

    df = df.copy()
    df = df[df["clasificacion_incumplimiento"] == "activo_sin_reportar"]
    if df.empty:
        return "0", "—", []

    df["fechapermiso_dt"] = pd.to_datetime(df["fechapermiso"], errors="coerce")
    df = df.sort_values("fechapermiso_dt", na_position="last")

    total = len(df)
    mas_antiguo = df["fechapermiso_dt"].min()
    antiguedad_anios = (
        f"{(pd.Timestamp.now() - mas_antiguo).days / 365:.1f}" if pd.notna(mas_antiguo) else "—"
    )

    df["accion"] = df["fechapermiso"].apply(
        lambda f: (
            "Obtener primer reporte -- en incumplimiento desde un año después del permiso"
            if pd.notna(f) else "Obtener primer reporte -- sin fecha de permiso registrada"
        )
    )
    columnas = ["peva_codigo", "isp_nombre", "isp_ruc", "fechapermiso", "fuera_de_gracia", "accion"]

    return format_number(total), antiguedad_anios, clean_records(df[columnas])
