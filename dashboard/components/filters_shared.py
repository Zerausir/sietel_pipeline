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
"""
from __future__ import annotations

from typing import Callable

from dash import Input, Output, State, callback, dcc, html, no_update

from services.queries import get_operation_states, get_provider_options


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
    "{prefix}-isp-nombre" que esa página ya usa.

    `get_full_provider_options` es una función SIN argumentos que
    devuelve la lista COMPLETA (nacional, sin acotar por territorio ni
    tipo de geografía) de prestadores válidos para el universo de ESA
    página -- se usa solo para VALIDAR el valor restaurado, nunca las
    opciones que el dropdown de esa página muestra en este momento (que
    pueden estar acotadas por territorio, y en la primera carga todavía
    no haberse calculado -- la misma condición de carrera que ya se
    corrigió en node_territory_filters.py se evita aquí desde el diseño,
    no reapareció por descuido).

    Dos callbacks separados para el valor de Estado y de Prestador, más
    uno de escritura -- nunca un callback que lea Y escriba el mismo
    Store en la misma dirección (ver el docstring de
    register_shared_period_sync en components/ui.py para la explicación
    completa de por qué esto es obligatorio, no una preferencia de
    estilo).
    """

    @callback(
        Output(f"{prefix}-opera-estado", "value"),
        Input("shared-filters", "modified_timestamp"),
        State("shared-filters", "data"),
        State(f"{prefix}-opera-estado", "value"),
    )
    def restaurar_opera_estado(_ts, shared_data, valor_actual):
        if valor_actual:
            # Ya hay algo elegido en ESTA página -- no lo pisa. En la
            # práctica esto solo importa dentro de la misma carga (Dash
            # Pages destruye y reconstruye el árbol de cada página al
            # navegar, así que un valor "ya elegido" en una carga nueva
            # siempre es el [] por defecto del layout, nunca algo viejo).
            return no_update
        return (shared_data or {}).get("opera_estados", [])

    @callback(
        Output(f"{prefix}-isp-nombre", "value"),
        Input("shared-filters", "modified_timestamp"),
        State("shared-filters", "data"),
        State(f"{prefix}-isp-nombre", "value"),
    )
    def restaurar_isp_nombre(_ts, shared_data, valor_actual):
        if valor_actual:
            print(f"[DEBUG {prefix}] restaurar_isp_nombre: ya hay valor propio ({valor_actual!r}), no pisa", flush=True)
            return no_update
        deseados = (shared_data or {}).get("isp_nombres", [])
        # DIAGNÓSTICO TEMPORAL (20-ago-2026) -- Iván reporta que Estado de
        # operación sí persiste al cambiar de pestaña, pero Prestador no
        # (vuelve a "Todos"). Diferencia estructural real entre ambos
        # callbacks: restaurar_opera_estado es puramente sincrónico (solo
        # lee un diccionario ya en memoria); este SÍ depende de una
        # consulta real a PostgreSQL (get_full_provider_options) sin
        # ningún manejo de excepción -- si esa consulta falla o el store
        # llega vacío en este instante, el callback completo puede
        # fallar/no actualizar nada, dejando el valor en el [] por
        # defecto del layout ("Todos"). Este print + try/except aísla
        # exactamente cuál de los dos es. QUITAR una vez diagnosticado.
        try:
            opciones_completas = get_full_provider_options()
            valores_validos = {o["value"] for o in opciones_completas}
            resultado = [v for v in deseados if v in valores_validos]
            print(
                f"[DEBUG {prefix}] restaurar_isp_nombre: deseados={deseados!r} "
                f"opciones_completas_count={len(opciones_completas)} resultado={resultado!r}",
                flush=True,
            )
            return resultado
        except Exception as exc:
            print(f"[DEBUG {prefix}] restaurar_isp_nombre: EXCEPCION -> {type(exc).__name__}: {exc}", flush=True)
            raise

    @callback(
        Output("shared-filters", "data", allow_duplicate=True),
        Input(f"{prefix}-opera-estado", "value"),
        Input(f"{prefix}-isp-nombre", "value"),
        prevent_initial_call=True,
        # allow_duplicate=True: las 5 páginas registran esta misma salida
        # -- solo la página visible tiene sus Inputs "vivos" en un momento
        # dado, así que en la práctica nunca compiten entre sí.
    )
    def guardar_filtros(opera_estados: list[str] | None, isp_nombres: list[str] | None):
        # DIAGNÓSTICO TEMPORAL (20-ago-2026) -- ver restaurar_isp_nombre.
        # Si esto se dispara con isp_nombres=[] justo después de navegar a
        # una página nueva (ANTES de que restaurar_isp_nombre termine),
        # estaría borrando el valor compartido con el [] recién montado
        # de esta página -- exactamente el síntoma reportado. QUITAR una
        # vez diagnosticado.
        print(f"[DEBUG {prefix}] guardar_filtros: opera_estados={opera_estados!r} isp_nombres={isp_nombres!r}",
              flush=True)
        return {"opera_estados": opera_estados or [], "isp_nombres": isp_nombres or []}
