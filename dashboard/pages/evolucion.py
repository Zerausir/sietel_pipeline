"""dashboard/pages/evolucion.py — Serie histórica de líneas dedicadas."""
from __future__ import annotations

import dash
import dash_ag_grid as dag
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

from services.queries import obtener_evolucion, obtener_territorios

dash.register_page(__name__, path="/", name="Evolución")

TERRITORIO_NACIONAL = "NACIONAL|ECUADOR"


def _opciones_provincias() -> list[dict]:
    df = obtener_territorios("PROVINCIA")
    return [{"label": fila.nombre_geografico, "value": fila.territorio_id} for fila in df.itertuples()]


def layout():
    provincias = _opciones_provincias()
    return html.Div(
        className="evolucion-page",
        children=[
            html.Div(
                className="controles",
                children=[
                    html.Div(
                        [
                            html.Label("Ámbito"),
                            dcc.RadioItems(
                                id="evolucion-ambito",
                                options=[
                                    {"label": "Nacional", "value": TERRITORIO_NACIONAL},
                                    {"label": "Por provincia", "value": "PROVINCIA"},
                                ],
                                value=TERRITORIO_NACIONAL,
                                inline=True,
                            ),
                        ]
                    ),
                    html.Div(
                        id="evolucion-selector-provincia-contenedor",
                        style={"display": "none"},
                        children=[
                            html.Label("Provincia"),
                            dcc.Dropdown(
                                id="evolucion-provincia",
                                options=provincias,
                                value=provincias[0]["value"] if provincias else None,
                                clearable=False,
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(id="evolucion-kpis", className="kpi-row"),
            dcc.Loading(dcc.Graph(id="evolucion-grafica")),
            html.H3("Detalle mensual"),
            html.Div(id="evolucion-tabla-contenedor"),
        ],
    )


@callback(
    Output("evolucion-selector-provincia-contenedor", "style"),
    Input("evolucion-ambito", "value"),
)
def _mostrar_selector_provincia(ambito: str):
    return {"display": "block"} if ambito == "PROVINCIA" else {"display": "none"}


@callback(
    Output("evolucion-kpis", "children"),
    Output("evolucion-grafica", "figure"),
    Output("evolucion-tabla-contenedor", "children"),
    Input("evolucion-ambito", "value"),
    Input("evolucion-provincia", "value"),
)
def _actualizar_evolucion(ambito: str, provincia_id: str | None):
    territorio_id = provincia_id if (ambito == "PROVINCIA" and provincia_id) else TERRITORIO_NACIONAL
    df = obtener_evolucion(territorio_id)

    if df.empty:
        vacio = html.P("Sin datos para este territorio.")
        return [vacio], go.Figure(), vacio

    ultimo = df.iloc[-1]

    def _kpi(titulo: str, valor: str, sub: str | None = None):
        return html.Div(
            className="kpi-card",
            children=[
                html.Div(titulo, className="kpi-title"),
                html.Div(valor, className="kpi-value"),
                html.Div(sub, className="kpi-sub") if sub else None,
            ],
        )

    variacion = ultimo.variacion_mensual_porcentaje
    variacion_txt = f"{variacion:+.1f}%" if variacion is not None else "s/d"

    kpis = [
        _kpi("Líneas totales", f"{int(ultimo.total_lineas):,}".replace(",", "."), str(ultimo.periodo)[:7]),
        _kpi("Variación mensual", variacion_txt),
        _kpi("Prestadores con líneas", f"{int(ultimo.numero_prestadores_con_lineas):,}".replace(",", ".")),
        _kpi(
            "% de datos imputados",
            f"{ultimo.porcentaje_imputado:.1f}%" if ultimo.porcentaje_imputado is not None else "0.0%",
        ),
    ]

    figura = go.Figure()
    figura.add_trace(
        go.Scatter(
            x=df["periodo"], y=df["total_lineas"], mode="lines", name="Líneas totales",
            line={"color": "#2563eb", "width": 2},
        )
    )
    figura.update_layout(
        margin={"l": 40, "r": 20, "t": 20, "b": 40},
        yaxis_title="Líneas dedicadas",
        xaxis_title=None,
        template="plotly_white",
        height=380,
    )

    columnas = [
        {"field": "periodo", "headerName": "Período", "sort": "desc"},
        {"field": "total_lineas", "headerName": "Líneas totales", "type": "numericColumn"},
        {"field": "numero_prestadores_con_lineas", "headerName": "Prestadores"},
        {"field": "porcentaje_imputado", "headerName": "% imputado", "valueFormatter": {"function": "d3.format('.1f')(params.value) + '%'"}},
        {"field": "variacion_mensual_porcentaje", "headerName": "Var. mensual %"},
    ]
    tabla = dag.AgGrid(
        rowData=df.to_dict("records"),
        columnDefs=columnas,
        defaultColDef={"resizable": True, "sortable": True, "filter": True},
        dashGridOptions={"theme": "themeBalham", "pagination": True, "paginationPageSize": 12, "animateRows": True},
        columnSize="responsiveSizeToFit",
        style={"height": "420px"},
    )

    return kpis, figura, tabla
