"""dashboard/components/sma_filters.py — Filtro compartido del módulo SMA.

Mismo espíritu que components/filters_shared.py y
components/node_territory_filters.py, pero para un universo de datos
NUEVO e independiente (samm_pipeline / samm_db) -- sincronizado SOLO
entre las dos páginas de este módulo ("sma-shared-filters" en app.py),
nunca con SAI (geografía y fuente de datos distintas).

Filtrado cruzado de Provincia/Cantón/Parroquia por TEXTO (no por código
INEC) -- ver la advertencia en services/queries_sma.py sobre por qué: el
panel de campos de Power BI no muestra columnas de código administrativo
para estas vistas.

Se aplica el patrón YA corregido en producción para nodos/Estado-Prestador
desde el principio, en vez de repetir las tres iteraciones de esa
depuración: restauración de VALOR disparada por navegación real
(Input("obtel-url", "pathname")) + el store compartido, escritura
quirúrgica vía dash.ctx.triggered_id, sin ningún store intermedio ni
consulta de validación adicional.
"""
from __future__ import annotations

import dash
from dash import Input, Output, State, callback, dcc, html

from services.queries_sma import (
    get_sma_czo_options, get_sma_operator_options, get_sma_technology_options, opciones_geograficas_sma,
)


def sma_filter_layout(prefix: str) -> html.Div:
    return html.Div(
        className="filter-panel",
        children=[
            html.Div(
                className="territory-grid",
                children=[
                    html.Div(
                        className="filter-field",
                        children=[
                            html.Label("Operadora"),
                            dcc.Dropdown(id=f"{prefix}-operadora", options=[], value=[], multi=True,
                                         placeholder="Todas"),
                        ],
                    ),
                    html.Div(
                        className="filter-field",
                        children=[
                            html.Label("CZO"),
                            dcc.Dropdown(id=f"{prefix}-czo", options=[], value=[], multi=True,
                                         placeholder="Todos"),
                        ],
                    ),
                    html.Div(
                        className="filter-field",
                        children=[
                            html.Label("Número"),
                            dcc.Input(id=f"{prefix}-numero", type="text", placeholder="Coincidencia exacta",
                                      debounce=True, className="filter-text-input"),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="territory-grid",
                children=[
                    html.Div(
                        className="filter-field",
                        children=[
                            html.Label("Provincia"),
                            dcc.Dropdown(id=f"{prefix}-provincia", options=[], value=[], multi=True,
                                         placeholder="Todas"),
                        ],
                    ),
                    html.Div(
                        className="filter-field",
                        children=[
                            html.Label("Cantón"),
                            dcc.Dropdown(id=f"{prefix}-canton", options=[], value=[], multi=True,
                                         placeholder="Todos"),
                        ],
                    ),
                    html.Div(
                        className="filter-field",
                        children=[
                            html.Label("Parroquia"),
                            dcc.Dropdown(id=f"{prefix}-parroquia", options=[], value=[], multi=True,
                                         placeholder="Todas"),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="territory-grid",
                children=[
                    html.Div(
                        className="filter-field",
                        children=[
                            html.Label("Tecnología"),
                            dcc.Dropdown(id=f"{prefix}-tecnologia", options=[], value=[], multi=True,
                                         placeholder="Todas"),
                        ],
                    ),
                    html.Div(
                        className="filter-field",
                        children=[
                            html.Label("Fecha Inicial"),
                            dcc.DatePickerSingle(id=f"{prefix}-fecha-inicial", display_format="DD/MM/YYYY"),
                        ],
                    ),
                    html.Div(
                        className="filter-field",
                        children=[
                            html.Label("Fecha Final"),
                            dcc.DatePickerSingle(id=f"{prefix}-fecha-final", display_format="DD/MM/YYYY"),
                        ],
                    ),
                ],
            ),
        ],
    )


def register_sma_filter_callbacks(prefix: str) -> None:
    @callback(Output(f"{prefix}-operadora", "options"), Input(f"{prefix}-operadora", "id"))
    def opciones_operadora(_):
        return get_sma_operator_options()

    @callback(Output(f"{prefix}-czo", "options"), Input(f"{prefix}-czo", "id"))
    def opciones_czo(_):
        return get_sma_czo_options()

    @callback(Output(f"{prefix}-tecnologia", "options"), Input(f"{prefix}-tecnologia", "id"))
    def opciones_tecnologia(_):
        return get_sma_technology_options()

    # --- Territorio: filtrado cruzado por texto entre los tres niveles ---
    @callback(
        Output(f"{prefix}-provincia", "options"),
        Input(f"{prefix}-canton", "value"),
    )
    def opciones_provincia(_cantones):
        return opciones_geograficas_sma("PROVINCIA")

    @callback(
        Output(f"{prefix}-canton", "options"),
        Input(f"{prefix}-provincia", "value"),
    )
    def opciones_canton(provincias):
        return opciones_geograficas_sma("CANTON", provincias=tuple(provincias or ()))

    @callback(
        Output(f"{prefix}-parroquia", "options"),
        Input(f"{prefix}-provincia", "value"),
        Input(f"{prefix}-canton", "value"),
    )
    def opciones_parroquia(provincias, cantones):
        return opciones_geograficas_sma(
            "PARROQUIA", provincias=tuple(provincias or ()), cantones=tuple(cantones or ()),
        )

    # --- Restauración de valor por navegación + escritura quirúrgica ---
    @callback(
        Output(f"{prefix}-operadora", "value"),
        Output(f"{prefix}-czo", "value"),
        Output(f"{prefix}-provincia", "value"),
        Output(f"{prefix}-canton", "value"),
        Output(f"{prefix}-parroquia", "value"),
        Output(f"{prefix}-tecnologia", "value"),
        Output(f"{prefix}-numero", "value"),
        Output(f"{prefix}-fecha-inicial", "date"),
        Output(f"{prefix}-fecha-final", "date"),
        Input("obtel-url", "pathname"),
        Input("sma-shared-filters", "data"),
    )
    def restaurar_filtros(_pathname, shared_data):
        d = shared_data or {}
        return (
            d.get("operadoras", []) or [], d.get("czos", []) or [],
            d.get("provincias", []) or [], d.get("cantones", []) or [], d.get("parroquias", []) or [],
            d.get("tecnologias", []) or [], d.get("numero"), d.get("fecha_inicial"), d.get("fecha_final"),
        )

    @callback(
        Output("sma-shared-filters", "data", allow_duplicate=True),
        Input(f"{prefix}-operadora", "value"),
        Input(f"{prefix}-czo", "value"),
        Input(f"{prefix}-provincia", "value"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parroquia", "value"),
        Input(f"{prefix}-tecnologia", "value"),
        Input(f"{prefix}-numero", "value"),
        Input(f"{prefix}-fecha-inicial", "date"),
        Input(f"{prefix}-fecha-final", "date"),
        State("sma-shared-filters", "data"),
        prevent_initial_call=True,
    )
    def resolve_selection(operadoras, czos, provincias, cantones, parroquias, tecnologias,
                          numero, fecha_inicial, fecha_final, shared_data):
        shared_data = dict(shared_data or {})

        # GUARDIA (31-ago-2026) -- mismo defecto latente encontrado en
        # components/node_territory_filters.py (ver ese archivo para el
        # porqué completo, citando la documentación oficial de Dash):
        # sma-shared-filters (el Output) vive fuera de page_container desde
        # el arranque; estos ocho campos (los Inputs) se insertan recién al
        # navegar entre sma_datos.py y sma_voz.py -- prevent_initial_call=True
        # no evita ese disparo fantasma sin este guardia.
        if len(dash.ctx.triggered) != 1:
            return dash.no_update

        triggered = dash.ctx.triggered_id
        campos_lista = {
            f"{prefix}-operadora": ("operadoras", operadoras),
            f"{prefix}-czo": ("czos", czos),
            f"{prefix}-provincia": ("provincias", provincias),
            f"{prefix}-canton": ("cantones", cantones),
            f"{prefix}-parroquia": ("parroquias", parroquias),
            f"{prefix}-tecnologia": ("tecnologias", tecnologias),
        }
        campos_escalares = {
            f"{prefix}-numero": ("numero", numero),
            f"{prefix}-fecha-inicial": ("fecha_inicial", fecha_inicial),
            f"{prefix}-fecha-final": ("fecha_final", fecha_final),
        }
        if triggered in campos_lista:
            clave, valor = campos_lista[triggered]
            shared_data[clave] = valor or []
        elif triggered in campos_escalares:
            # Escalares: se guardan tal cual, incluido None -- el usuario
            # puede limpiar el campo deliberadamente (a diferencia de un
            # Dropdown multi vacío, que Dash entrega como None pero
            # semánticamente equivale a "sin filtro", no a "borrar algo").
            clave, valor = campos_escalares[triggered]
            shared_data[clave] = valor
        else:
            return dash.no_update
        return shared_data
