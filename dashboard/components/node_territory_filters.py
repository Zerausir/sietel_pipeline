"""dashboard/components/node_territory_filters.py — Filtro geográfico de nodos ISP.

Mismo universo que antes -- mart.vw_dashboard_filtros_geograficos_nodo
(geografía CONALI derivada de coordenadas), NUNCA
get_territory_options()/mart.vw_dashboard_filtros_geograficos (geografía de
líneas reportadas). Confirmado con Iván 06-ago-2026 -- un nodo físico puede
servir a varias parroquias de líneas, no hay relación 1:1.

REDISEÑO (11-ago-2026, a pedido de Iván): se elimina el selector "Nivel
geográfico" -- Provincia, Cantón y Parroquia quedan siempre visibles, cada
uno de SELECCIÓN MÚLTIPLE e independiente entre sí (estilo segmentadores de
Power BI), no una jerarquía de un solo nivel a la vez como antes.

FILTRADO CRUZADO (13-ago-2026, a pedido de Iván): antes, Cantón se acotaba
a la Provincia elegida y Parroquia al Cantón/Provincia elegidos, pero NUNCA
al revés -- elegir una Parroquia sin tocar Provincia dejaba el selector de
Provincia mostrando las 26 opciones completas, no solo la que corresponde.
Ahora los tres niveles se acotan entre sí en cualquier dirección (ver
services.queries.opciones_geograficas_facetadas()).

DECISIÓN DE DISEÑO IMPORTANTE, no un descuido: el filtrado cruzado SOLO
acota las OPCIONES visibles de los otros dos selectores -- nunca borra un
VALOR que el usuario ya eligió, aunque ese valor deje de aparecer en la
lista visible del selector cruzado. Dos razones, no una sola:
  1. Borrar automáticamente una selección explícita del usuario porque
     OTRO campo cambió es una sorpresa desagradable -- Iván pidió "que se
     acoten las opciones", no "que se me borre lo que elegí".
  2. Es estructuralmente necesario: si Output(Provincia.value) dependiera
     de Input(Cantón.value) Y Output(Cantón.value) dependiera de
     Input(Provincia.value) al mismo tiempo, Dash detecta esto como una
     DEPENDENCIA CIRCULAR real en su grafo de callbacks (no en tiempo de
     ejecución -- en el grafo estático, sin importar qué tan inofensiva
     sea la lógica interna) y la aplicación no arrancaría. Por eso las
     opciones y el valor de cada selector viven en callbacks SEPARADOS:
     las opciones reaccionan a los hermanos (Input), el valor solo se
     restaura desde el store compartido -- ver
     register_node_territory_callbacks() más abajo.

NO comparte dcc.Store con territory_filters.py -- "shared-territory" es de
Evolución/Concentración (geografía de líneas). Las páginas de nodos usan su
propio store local ("nodo-shared-territory"), sincronizado solo entre ellas
(Mapa de Nodos y Discrepancias de Geografía). Su forma es
{provincias, cantones, parroquias} (listas), reflejando la selección
múltiple -- ver app.py para el valor inicial del Store.

CORRECCIÓN (21-ago-2026, confirmado por el usuario en producción -- la
sincronización entre Mapa de nodos y Discrepancias NO funcionaba): la
restauración de valor dependía de "nodo-shared-territory.modified_timestamp"
+ una consulta real a PostgreSQL (get_node_territory_hierarchy) para validar
el código restaurado, mientras que resolve_selection (el que escribe) solo
se protegía con prevent_initial_call=True. Es EXACTAMENTE el mismo patrón
que ya se confirmó roto para Estado/Prestador (ver
components/filters_shared.py): prevent_initial_call=True NO evita de forma
confiable el disparo "fantasma" del montaje de una página nueva en Dash
Pages -- ese disparo podía escribir el [] recién montado de los tres
dropdowns en nodo-shared-territory ANTES de que la consulta a la base
terminara de restaurar el valor real, sobrescribiéndolo. No se detectó
antes porque las pruebas anteriores solo verificaban la lógica de la
función aislada, no la carrera real entre los dos callbacks -- el mismo
punto ciego que tuvo el bug de Prestador hasta que se probó en un
navegador real.

Se corrige con el MISMO mecanismo ya probado en producción para Estado/
Prestador: restauración disparada por navegación real
(Input("obtel-url", "pathname")) + cambios del store, sin ninguna consulta
a PostgreSQL (ya no hace falta -- los códigos que llegan a
nodo-shared-territory siempre vinieron de una selección real hecha en
alguna de las dos páginas, ambas ya validadas contra
get_node_territory_hierarchy() en sus propios callbacks de opciones);
escritura quirúrgica vía dash.ctx.triggered_id, que modifica solo el campo
que realmente cambió -- nunca reconstruye los tres campos desde cero.
"""
from __future__ import annotations

import dash
from dash import Input, Output, State, callback, dcc, html

from services.queries import get_node_territory_hierarchy, opciones_geograficas_facetadas


def node_territory_filter_layout(prefix: str) -> html.Div:
    return html.Div(
        className="territory-grid",
        children=[
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Provincia"),
                    dcc.Dropdown(
                        id=f"{prefix}-province", options=[], value=[], multi=True, placeholder="Todas",
                    ),
                ],
            ),
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Cantón"),
                    dcc.Dropdown(
                        id=f"{prefix}-canton", options=[], value=[], multi=True, placeholder="Todos",
                    ),
                ],
            ),
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Parroquia"),
                    dcc.Dropdown(
                        id=f"{prefix}-parish", options=[], value=[], multi=True, placeholder="Todas",
                    ),
                ],
            ),
            dcc.Store(id=f"{prefix}-territory-selection", data={"provincias": [], "cantones": [], "parroquias": []}),
        ],
    )


def register_node_territory_callbacks(prefix: str) -> None:
    # --- Opciones: reaccionan a los DOS hermanos, filtrado cruzado real ---
    # SIN CAMBIOS respecto a la versión anterior.
    @callback(
        Output(f"{prefix}-province", "options"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
    )
    def opciones_provincia(cantones, parroquias):
        jerarquia = get_node_territory_hierarchy()
        return opciones_geograficas_facetadas(
            jerarquia, "codigo_provincia", "nombre_provincia",
            {"codigo_canton": cantones or [], "codigo_parroquia": parroquias or []},
        )

    @callback(
        Output(f"{prefix}-canton", "options"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-parish", "value"),
    )
    def opciones_canton(provincias, parroquias):
        jerarquia = get_node_territory_hierarchy()
        return opciones_geograficas_facetadas(
            jerarquia, "codigo_canton", "nombre_canton",
            {"codigo_provincia": provincias or [], "codigo_parroquia": parroquias or []},
        )

    @callback(
        Output(f"{prefix}-parish", "options"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
    )
    def opciones_parroquia(provincias, cantones):
        jerarquia = get_node_territory_hierarchy()
        return opciones_geograficas_facetadas(
            jerarquia, "codigo_parroquia", "nombre_parroquia",
            {"codigo_provincia": provincias or [], "codigo_canton": cantones or []},
        )

    # --- Valor: restauración por navegación + persistencia quirúrgica ---
    # (ver el docstring del módulo, sección "CORRECCIÓN 21-ago-2026", para
    # el porqué completo).
    @callback(
        Output(f"{prefix}-province", "value"),
        Output(f"{prefix}-canton", "value"),
        Output(f"{prefix}-parish", "value"),
        Input("obtel-url", "pathname"),
        Input("nodo-shared-territory", "data"),
    )
    def restaurar_territorio(_pathname, shared_data):
        shared_data = shared_data or {}
        return (
            shared_data.get("provincias", []) or [],
            shared_data.get("cantones", []) or [],
            shared_data.get("parroquias", []) or [],
        )

    @callback(
        Output(f"{prefix}-territory-selection", "data"),
        Output("nodo-shared-territory", "data", allow_duplicate=True),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
        State("nodo-shared-territory", "data"),
        prevent_initial_call=True,
    )
    def resolve_selection(provincias, cantones, parroquias, shared_data):
        # "{prefix}-territory-selection" (local, usado por las consultas
        # propias de ESTA página) siempre refleja el estado COMPLETO
        # actual de los tres dropdowns, sin importar cuál cambió.
        seleccion_local = {
            "provincias": provincias or [],
            "cantones": cantones or [],
            "parroquias": parroquias or [],
        }

        # "nodo-shared-territory" (compartido con la página hermana) se
        # actualiza de forma QUIRÚRGICA -- solo el campo que realmente
        # cambió, fusionado sobre lo que ya había -- nunca reconstruido
        # desde cero a partir de los tres dropdowns. Esto es lo que evita
        # que el disparo fantasma del montaje sobrescriba con [] los
        # otros dos campos que la página hermana ya había puesto ahí.
        shared_data = dict(shared_data or {})
        triggered_id = dash.ctx.triggered_id
        if triggered_id == f"{prefix}-province":
            shared_data["provincias"] = provincias or []
        elif triggered_id == f"{prefix}-canton":
            shared_data["cantones"] = cantones or []
        elif triggered_id == f"{prefix}-parish":
            shared_data["parroquias"] = parroquias or []
        else:
            return seleccion_local, dash.no_update

        return seleccion_local, shared_data
