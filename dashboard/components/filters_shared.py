"""dashboard/components/filters_shared.py — Estado de operación y Prestador.

Dos responsabilidades separadas a propósito, nunca en el mismo callback:

1. OPCIONES del dropdown de Prestador -- depende del universo geográfico
   propio de cada página (líneas vs. nodos) y de su propio modelo de
   territorio (selección única con Nivel vs. multi-select independiente).
   No se puede generalizar entre las 5 páginas sin forzarlas a compartir
   un modelo de territorio que deliberadamente no comparten -- cada página
   sigue resolviendo esto por su cuenta (Evolución/Concentración vía
   shared_filters_layout()+actualizar_opciones_isp() aquí mismo; Control
   con una lista nacional fija; Mapa de nodos/Discrepancias con su propio
   callback ya existente en cada página).

2. VALOR elegido -- SÍ se sincroniza de forma universal entre los 5
   módulos (Evolución, Concentración, Control, Mapa de nodos,
   Discrepancias de geografía), a través de register_universal_opera_isp_sync()
   (20-ago-2026, ampliado desde el alcance anterior -- antes solo viajaba
   entre Evolución y Concentración). El mismo dcc.Store "shared-filters"
   de siempre (definido en app.py), con más páginas leyendo/escribiendo.

CORRECCIÓN (20-ago-2026, confirmado con logging de producción): Estado de
operación persistía correctamente al cambiar de página, pero Prestador
volvía a "Todos". Causa real: al navegar a una página nueva, Dash dispara
guardar_filtros() con el valor [] recién montado del layout ANTES de que
la restauración termine su consulta a PostgreSQL (get_full_provider_
options) -- ese disparo "fantasma" del montaje podía llegar DESPUÉS del
resultado correcto de la restauración y pisarlo. Estado de operación casi
nunca lo sufría porque su parte de la restauración es puramente
sincrónica (solo lee un diccionario ya en memoria); Prestador, que sí
depende de una consulta real, sí. La solución: un Store "armado" por
página que solo se pone en True cuando restaurar_filtros() ya corrió --
guardar_filtros() se queda callado (no_update) hasta entonces, sin
importar cuántas veces se dispare de más el disparo fantasma ni en qué
orden llegue.
"""
from __future__ import annotations

from typing import Callable

from dash import Input, Output, State, callback, dcc, html, no_update

from services.queries import get_operation_states, get_provider_options


def sync_armado_store(prefix: str) -> dcc.Store:
    """
    Un Store booleano por página, en False hasta que TANTO
    restaurar_opera_estado como restaurar_isp_nombre hayan corrido al
    menos una vez -- ver el docstring del módulo para el porqué completo.
    Debe incluirse en el layout() de cada página que llame a
    register_universal_opera_isp_sync() (shared_filters_layout() ya lo
    incluye para Evolución/Concentración; Control, Mapa de nodos y
    Discrepancias lo agregan a mano en su propio layout()).
    """
    return dcc.Store(id=f"{prefix}-sync-armado", data=False)


def shared_filters_layout(prefix: str) -> html.Div:
    """Usado únicamente por Evolución y Concentración -- Control, Mapa de
    nodos y Discrepancias construyen sus propios dropdowns de Estado/
    Prestador directamente en su layout(), con los mismos ids por
    convención ("{prefix}-opera-estado"/"{prefix}-isp-nombre"), porque sus
    opciones de Prestador se calculan distinto (ver docstring del módulo)."""
    return html.Div(
        className="territory-grid",
        children=[
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Estado de operación"),
                    dcc.Dropdown(
                        id=f"{prefix}-opera-estado",
                        options=get_operation_states(),
                        value=[],
                        multi=True,
                        placeholder="Todos",
                    ),
                ],
            ),
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Prestador"),
                    dcc.Dropdown(
                        id=f"{prefix}-isp-nombre",
                        options=[],
                        value=[],
                        multi=True,
                        placeholder="Todos",
                    ),
                ],
            ),
            sync_armado_store(prefix),
        ],
    )


def register_shared_filters_callbacks(prefix: str) -> None:
    """
    Exclusivo de Evolución/Concentración -- calcula las OPCIONES de
    Prestador reaccionando a "{prefix}-territory-id" (modelo de territorio
    de selección única con Nivel, ver components/territory_filters.py).

    CORRECCIÓN (20-ago-2026): antes esta función también restauraba el
    VALOR desde el store compartido, acoplado a este mismo territory_id --
    eso impedía generalizar la sincronización de valor a Control/Mapa de
    nodos/Discrepancias, que no tienen "{prefix}-territory-id" en absoluto.
    Esa responsabilidad se separó a register_universal_opera_isp_sync(),
    que valida el valor restaurado contra la lista NACIONAL completa de
    prestadores (no contra las opciones ya acotadas por territorio de esta
    página) -- llamar a ambas funciones para Evolución/Concentración.
    """

    @callback(
        Output(f"{prefix}-isp-nombre", "options"),
        Input(f"{prefix}-territory-id", "data"),
    )
    def actualizar_opciones_isp(territory_id: str | None):
        if not territory_id:
            return []
        return get_provider_options(territory_id)


def register_universal_opera_isp_sync(prefix: str, get_full_provider_options: Callable[[], list[dict]]) -> None:
    """
    Sincroniza el VALOR (no las opciones) de Estado de operación y
    Prestador entre los 5 módulos del dashboard -- Evolución,
    Concentración, Control, Mapa de nodos, Discrepancias de geografía
    (20-ago-2026, a pedido del usuario: "quiero que Estado/Prestador sea
    un solo estado universal compartido entre los 5 módulos"). Se llama
    UNA VEZ por página, con los ids "{prefix}-opera-estado"/
    "{prefix}-isp-nombre" que esa página ya usa -- y esa página DEBE
    incluir sync_armado_store(prefix) en su layout() (ver docstring de esa
    función).

    `get_full_provider_options` es una función SIN argumentos que
    devuelve la lista COMPLETA (nacional, sin acotar por territorio ni
    tipo de geografía) de prestadores válidos para el universo de ESA
    página -- se usa solo para VALIDAR el valor restaurado, nunca las
    opciones que el dropdown de esa página muestra en este momento (que
    pueden estar acotadas por territorio, y en la primera carga todavía
    no haberse calculado -- la misma condición de carrera que ya se
    corrigió en node_territory_filters.py se evita aquí desde el diseño,
    no reapareció por descuido).

    CORRECCIÓN (20-ago-2026, confirmado con logging real de producción):
    la primera versión tenía DOS callbacks de restauración separados
    (uno por campo), cada uno escribiendo a "{prefix}-sync-armado" con
    allow_duplicate=True -- pero Dash exige prevent_initial_call=True en
    cualquier callback con una salida allow_duplicate, y el valor especial
    prevent_initial_call="initial_duplicate" está reportado como roto por
    callback individual (se comporta como True igual, bloqueando el
    disparo inicial que la restauración necesita -- ver
    github.com/plotly/dash/issues/2974). Eso habría dejado la
    restauración completamente muerta, un problema peor que el que se
    quería corregir.

    La solución real: UN SOLO callback que restaura los dos campos Y
    arma el candado, sin ninguna salida duplicada en ningún lado. Se
    ejecuta de principio a fin en el servidor antes de devolver nada --
    aunque get_full_provider_options() tarde un round-trip real a
    PostgreSQL, esa espera ocurre DENTRO de la misma llamada a la función,
    nunca en un callback aparte -- así que cuando el candado pasa a True,
    los dos valores YA están aplicados, sin ninguna ventana intermedia
    donde uno esté listo y el otro no.

    guardar_filtros() sigue exactamente igual que antes: se queda callado
    (no_update) mientras el candado no esté armado -- así, cualquier
    disparo "fantasma" del montaje de la página (el [] por defecto del
    layout, ANTES de que este callback termine) nunca llega a pisar nada
    en el store compartido, sin importar cuántas veces se dispare de
    más ni en qué orden.
    """

    @callback(
        Output(f"{prefix}-opera-estado", "value"),
        Output(f"{prefix}-isp-nombre", "value"),
        Output(f"{prefix}-sync-armado", "data"),
        Input("shared-filters", "modified_timestamp"),
        State("shared-filters", "data"),
        State(f"{prefix}-opera-estado", "value"),
        State(f"{prefix}-isp-nombre", "value"),
    )
    def restaurar_filtros(_ts, shared_data, opera_actual, isp_actual):
        shared_data = shared_data or {}

        opera_resultado = no_update if opera_actual else shared_data.get("opera_estados", [])

        if isp_actual:
            isp_resultado = no_update
        else:
            deseados = shared_data.get("isp_nombres", [])
            opciones_completas = get_full_provider_options()
            valores_validos = {o["value"] for o in opciones_completas}
            isp_resultado = [v for v in deseados if v in valores_validos]

        return opera_resultado, isp_resultado, True

    @callback(
        Output("shared-filters", "data", allow_duplicate=True),
        Input(f"{prefix}-opera-estado", "value"),
        Input(f"{prefix}-isp-nombre", "value"),
        State(f"{prefix}-sync-armado", "data"),
        prevent_initial_call=True,
        # allow_duplicate=True: las 5 páginas registran esta misma salida
        # -- solo la página visible tiene sus Inputs "vivos" en un momento
        # dado, así que en la práctica nunca compiten entre sí. Esta SÍ
        # necesita allow_duplicate (5 callbacks distintos, cada uno de una
        # página, apuntan al mismo "shared-filters.data"), pero como es la
        # ÚNICA salida a ese destino en cada uno de estos 5 callbacks
        # (nunca dos salidas al mismo lugar EN EL MISMO callback), no cae
        # en el bug de "initial_duplicate" -- prevent_initial_call=True
        # normal es suficiente y correcto aquí.
    )
    def guardar_filtros(opera_estados: list[str] | None, isp_nombres: list[str] | None, armado: bool):
        if not armado:
            # Todavía no terminó de correr restaurar_filtros() en esta
            # página -- cualquier valor que se vea aquí puede ser el []
            # recién montado del layout, no una elección real. Ver
            # docstring de esta función.
            return no_update
        return {"opera_estados": opera_estados or [], "isp_nombres": isp_nombres or []}
