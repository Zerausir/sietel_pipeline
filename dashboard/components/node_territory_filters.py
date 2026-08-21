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

SEGUNDA CORRECCIÓN (21-ago-2026, misma sesión -- la primera no bastó): el
usuario confirmó que seguía sin funcionar después de la corrección
anterior, y preguntó explícitamente si esto no debía replicar la misma
lógica ya probada en producción para Prestador
(components/filters_shared.py). Al comparar línea por línea se encontró
una omisión real, no cosmética: restaurar_territorio() (fija el VALOR) y
opciones_provincia()/opciones_canton()/opciones_parroquia() (fijan las
OPCIONES) se disparan por razones completamente independientes entre sí --
una por navegación/cambio del store compartido, las otras por cambios en
los hermanos LOCALES. Dash no garantiza cuál de las dos llega primero al
navegador.

TERCERA CORRECCIÓN (21-ago-2026, misma sesión -- simplificación real, no
otro parche): las dos correcciones anteriores agregaban mecanismos cada vez
más finos de Dash (prevent_initial_call="initial_duplicate", preservación
de opciones) para mantener sincronizado un store LOCAL intermedio
("{prefix}-territory-selection") que ni Estado ni Prestador necesitan --
esas consultas de datos ya leen el valor de sus dropdowns DIRECTAMENTE, sin
ningún paso intermedio. Ese intermediario era la causa raíz de toda la
complicación: cada vez que restaurar_territorio() fijaba el valor visible
del dropdown, resolve_selection() tenía que ALCANZAR a correr también para
traducir ese valor al store local que las consultas realmente leían -- un
paso adicional, con su propia ventana de tiempo para fallar.

Se elimina "{prefix}-territory-selection" por completo. mapa_nodos.py y
discrepancias_geografia.py ahora leen Provincia/Cantón/Parroquia
DIRECTAMENTE de "{prefix}-province"/"{prefix}-canton"/"{prefix}-parish"
(value), igual que ya leen Estado/Prestador. resolve_selection() vuelve a
prevent_initial_call=True simple (sin "initial_duplicate") porque ya no
necesita alcanzar a correr en el montaje -- su único trabajo ahora es
avisarle a la página hermana cuando el usuario cambia algo, nunca alimentar
una consulta de datos de esta misma página.
CUARTA CORRECCIÓN -- en realidad, funcionalidad nueva (21-ago-2026, a
pedido de Iván, estilo Power BI): elegir un Prestador TAMBIÉN acota
Provincia/Cantón/Parroquia a solo donde ese prestador tiene presencia real
-- ver services/queries.py:get_node_territorios_con_prestador()/
acotar_opciones_por_prestador(). Restricción ADICIONAL sobre el filtrado
cruzado ya existente entre los tres niveles y sobre la preservación de
valores compartidos, no un reemplazo de ninguno de los dos.
"""
from __future__ import annotations

import dash
from dash import Input, Output, State, callback, dcc, html

from services.queries import (
    acotar_opciones_por_prestador, get_node_territorios_con_prestador, get_node_territory_hierarchy,
    opciones_geograficas_facetadas,
)


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
        ],
    )


def register_node_territory_callbacks(prefix: str) -> None:
    def _preservar_valores(
            opciones: list[dict],
            jerarquia,
            columna_codigo: str,
            columna_nombre: str,
            valores_actuales: list[str] | None,
            valores_compartidos: list[str] | None,
    ) -> list[dict]:
        """
        Réplica EXACTA del patrón ya probado en producción para Prestador
        (components/filters_shared.py:actualizar_opciones_isp /
        pages/mapa_nodos.py:update_isp_options) -- unión de DOS conjuntos,
        no solo uno:

          1. valores_actuales (State sobre el propio valor del dropdown en
             este instante) -- cubre el caso de un cambio recién hecho por
             el usuario en ESTA MISMA página, que todavía no alcanzó a
             persistirse en nodo-shared-territory cuando este callback de
             opciones se ejecuta (hueco de tiempo real entre dos callbacks
             independientes, no hipotético).
          2. valores_compartidos (de nodo-shared-territory) -- cubre el
             caso de un valor que llegó de la página HERMANA por
             navegación, y que restaurar_territorio() puede aplicar antes,
             después, o al mismo tiempo que este callback recalcula
             opciones (los dos son independientes entre sí, Dash no
             garantiza el orden).

        CORRECCIÓN (21-ago-2026, misma sesión): la primera versión de este
        arreglo solo cubría el punto 2 -- se detectó la omisión al comparar
        línea por línea contra la solución de Prestador que el usuario ya
        confirmó funcionando en producción, a pedido explícito del usuario
        ("¿no es mejor implementar la lógica que yo ya creé?"). No es una
        diferencia cosmética: sin el punto 1, un cambio del usuario en
        Provincia mientras Cantón/Parroquia recalculan sus opciones podría,
        en el mismo hueco de tiempo, perder la representación visual de lo
        que el usuario acaba de elegir.
        """
        valores_a_conservar = set(valores_actuales or []) | set(valores_compartidos or [])
        existentes = {str(o["value"]) for o in opciones}
        faltantes = [str(v) for v in valores_a_conservar if str(v) not in existentes]
        if not faltantes:
            return opciones
        nombres_por_codigo = (
            jerarquia[[columna_codigo, columna_nombre]]
            .dropna()
            .drop_duplicates(subset=[columna_codigo])
            .astype(str)
            .set_index(columna_codigo)[columna_nombre]
        )
        for codigo in faltantes:
            nombre = nombres_por_codigo.get(codigo, codigo)
            opciones.append({"label": nombre, "value": codigo})
        return opciones

    # --- Opciones: reaccionan a los DOS hermanos, filtrado cruzado real --
    # -- AMPLIADO (21-ago-2026) para también conservar el valor propio Y el
    # compartido, ver _preservar_valores() más arriba -- Y para acotar por
    # Prestador elegido, ver acotar_opciones_por_prestador() en
    # services/queries.py.
    @callback(
        Output(f"{prefix}-province", "options"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
        Input(f"{prefix}-isp-nombre", "value"),
        Input("nodo-shared-territory", "data"),
        State(f"{prefix}-province", "value"),
    )
    def opciones_provincia(cantones, parroquias, isp_nombres, shared_data, valores_actuales):
        jerarquia = get_node_territory_hierarchy()
        opciones = opciones_geograficas_facetadas(
            jerarquia, "codigo_provincia", "nombre_provincia",
            {"codigo_canton": cantones or [], "codigo_parroquia": parroquias or []},
        )
        if isp_nombres:
            territorios = get_node_territorios_con_prestador(tuple(isp_nombres))
            opciones = acotar_opciones_por_prestador(opciones, "codigo_provincia", territorios)
        return _preservar_valores(
            opciones, jerarquia, "codigo_provincia", "nombre_provincia",
            valores_actuales, (shared_data or {}).get("provincias"),
        )

    @callback(
        Output(f"{prefix}-canton", "options"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-parish", "value"),
        Input(f"{prefix}-isp-nombre", "value"),
        Input("nodo-shared-territory", "data"),
        State(f"{prefix}-canton", "value"),
    )
    def opciones_canton(provincias, parroquias, isp_nombres, shared_data, valores_actuales):
        jerarquia = get_node_territory_hierarchy()
        opciones = opciones_geograficas_facetadas(
            jerarquia, "codigo_canton", "nombre_canton",
            {"codigo_provincia": provincias or [], "codigo_parroquia": parroquias or []},
        )
        if isp_nombres:
            territorios = get_node_territorios_con_prestador(tuple(isp_nombres))
            opciones = acotar_opciones_por_prestador(opciones, "codigo_canton", territorios)
        return _preservar_valores(
            opciones, jerarquia, "codigo_canton", "nombre_canton",
            valores_actuales, (shared_data or {}).get("cantones"),
        )

    @callback(
        Output(f"{prefix}-parish", "options"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-isp-nombre", "value"),
        Input("nodo-shared-territory", "data"),
        State(f"{prefix}-parish", "value"),
    )
    def opciones_parroquia(provincias, cantones, isp_nombres, shared_data, valores_actuales):
        jerarquia = get_node_territory_hierarchy()
        opciones = opciones_geograficas_facetadas(
            jerarquia, "codigo_parroquia", "nombre_parroquia",
            {"codigo_provincia": provincias or [], "codigo_canton": cantones or []},
        )
        if isp_nombres:
            territorios = get_node_territorios_con_prestador(tuple(isp_nombres))
            opciones = acotar_opciones_por_prestador(opciones, "codigo_parroquia", territorios)
        return _preservar_valores(
            opciones, jerarquia, "codigo_parroquia", "nombre_parroquia",
            valores_actuales, (shared_data or {}).get("parroquias"),
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
        Output("nodo-shared-territory", "data", allow_duplicate=True),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
        State("nodo-shared-territory", "data"),
        prevent_initial_call=True,
    )
    def resolve_selection(provincias, cantones, parroquias, shared_data):
        # Único trabajo de este callback: avisarle a la página hermana
        # cuando el usuario cambia algo AQUÍ. Ya no alimenta ninguna
        # consulta de datos de esta misma página (esas leen
        # "{prefix}-province"/"{prefix}-canton"/"{prefix}-parish" value
        # directamente) -- por eso no necesita correr en el montaje de la
        # página, prevent_initial_call=True simple basta.
        #
        # Escritura QUIRÚRGICA -- solo el campo que realmente cambió,
        # fusionado sobre lo que ya había -- nunca reconstruido desde cero
        # a partir de los tres dropdowns. Esto es lo que evita que un
        # disparo espurio sobrescriba con [] los otros dos campos que la
        # página hermana ya había puesto ahí.
        shared_data = dict(shared_data or {})
        triggered_id = dash.ctx.triggered_id
        if triggered_id == f"{prefix}-province":
            shared_data["provincias"] = provincias or []
        elif triggered_id == f"{prefix}-canton":
            shared_data["cantones"] = cantones or []
        elif triggered_id == f"{prefix}-parish":
            shared_data["parroquias"] = parroquias or []
        else:
            return dash.no_update

        return shared_data
