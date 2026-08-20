"""dashboard/components/filters_shared.py — Estado de operación y Prestador.

Responsabilidades separadas:

1. OPCIONES del dropdown de Prestador:
   cada página las determina según su propio universo geográfico.

2. VALOR seleccionado:
   Estado de operación y Prestador son filtros UNIVERSALES compartidos
   entre las cinco páginas:
       - Evolución
       - IHH y participación
       - Control
       - Mapa de nodos
       - Discrepancias de geografía

El valor seleccionado vive en el dcc.Store "shared-filters", definido en
app.py y fuera de dash.page_container.

IMPORTANTE:
Las opciones y el valor son conceptos distintos.

Las opciones pueden ser diferentes entre páginas porque:
- Evolución/Concentración trabajan sobre geografía de líneas.
- Mapa de nodos/Discrepancias trabajan sobre geografía CONALI.
- Control tiene su propio universo nacional.

El valor seleccionado, en cambio, debe viajar entre todas las páginas.

La restauración del valor NO consulta PostgreSQL.

Esto es deliberado:
el Store compartido ya contiene el valor que el usuario eligió. Hacer una
segunda consulta para validar ese mismo valor durante el montaje de una página
introduce una operación asíncrona innecesaria en medio de la cadena de
restauración.

La documentación oficial de Dash indica que dcc.Store es precisamente el
mecanismo para compartir estado entre callbacks y que los callbacks pueden
dispararse cuando componentes aparecen en layouts dinámicos.

La validación de que el valor puede mostrarse queda en manos del callback que
construye las opciones de cada página. Ese callback debe conservar siempre
dentro de "options" los valores actualmente seleccionados.
"""

from __future__ import annotations

from dash import Input, Output, State, callback, dcc, html, no_update

from services.queries import get_operation_states, get_provider_options


def sync_armado_store(prefix: str) -> dcc.Store:
    """
    Store de control de inicialización para cada página.

    Mientras este Store sea False, el callback que guarda los filtros no
    escribe en shared-filters.

    Esto evita que el [] inicial de un Dropdown recién montado sea interpretado
    como una selección real del usuario.

    Approach:
    Usar un Store booleano independiente por página como barrera entre la
    restauración inicial y el guardado de cambios del usuario.

    Reasoning:
    En Dash Pages los componentes de una página aparecen y desaparecen al
    navegar. Dash puede ejecutar callbacks cuando esos componentes aparecen
    en el layout. Por eso prevent_initial_call por sí solo no debe utilizarse
    como única barrera para este caso.

    Test Cases:
    - Store recién creado -> data=False.
    - Restauración terminada -> data=True.
    - Dropdown inicial [] mientras data=False -> shared-filters no cambia.
    - Usuario cambia Prestador con data=True -> shared-filters se actualiza.
    """
    return dcc.Store(
        id=f"{prefix}-sync-armado",
        data=False,
    )


def shared_filters_layout(prefix: str) -> html.Div:
    """
    Construye los filtros compartidos de Evolución y Concentración.

    Approach:
    Crear Estado y Prestador como componentes locales de la página, mientras
    su valor se sincroniza mediante shared-filters.

    Reasoning:
    Las dos páginas tienen el mismo modelo de territorio y por eso pueden
    compartir esta parte del layout.

    Test Cases:
    - layout("evo") -> IDs evo-opera-estado y evo-isp-nombre.
    - layout("con") -> IDs con-opera-estado y con-isp-nombre.
    - Ambos contienen sync-armado.
    """
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
    Registra los callbacks de OPCIONES de Prestador para Evolución/Concentración.

    El valor universal NO se restaura aquí.

    Este callback solo determina qué Prestadores puede mostrar la página
    según su territorio.

    MUY IMPORTANTE:
    Los valores que ya están seleccionados deben permanecer dentro de
    options aunque el filtro geográfico cambie.

    Esto sigue la recomendación de la documentación oficial de Dash para
    Dropdowns dinámicos: si un valor seleccionado desaparece de options,
    puede desaparecer de la lista visible aunque siga formando parte de
    value.

    Approach:
    Obtener las opciones normales según territorio y después añadir cualquier
    valor seleccionado que provenga del estado compartido.

    Reasoning:
    El valor universal no debe perder su representación visual solamente
    porque la consulta de opciones de la página esté temporalmente acotada.

    Test Cases:
    - Sin territorio -> [].
    - Territorio con Prestador seleccionado -> el Prestador permanece en options.
    - Cambio de territorio -> las nuevas opciones reemplazan las anteriores,
      pero los valores seleccionados se conservan.
    """

    @callback(
        Output(f"{prefix}-isp-nombre", "options"),
        Input(f"{prefix}-territory-id", "data"),
        State(f"{prefix}-isp-nombre", "value"),
        State("shared-filters", "data"),
    )
    def actualizar_opciones_isp(
            territory_id: str | None,
            valores_actuales: list[str] | None,
            shared_data: dict | None,
    ):
        if not territory_id:
            return []

        opciones = get_provider_options(territory_id)

        valores_actuales = valores_actuales or []
        valores_compartidos = (shared_data or {}).get("isp_nombres", []) or []

        valores_a_conservar = set(valores_actuales) | set(valores_compartidos)

        if not valores_a_conservar:
            return opciones

        existentes = {str(opcion["value"]) for opcion in opciones}

        for valor in valores_a_conservar:
            if str(valor) not in existentes:
                opciones.append(
                    {
                        "label": str(valor),
                        "value": valor,
                    }
                )

        return opciones


def register_universal_opera_isp_sync(
        prefix: str,
        get_full_provider_options=None,
) -> None:
    """
    Sincroniza el VALOR de Estado de operación y Prestador entre las cinco
    páginas.

    `get_full_provider_options` se conserva como argumento opcional para no
    romper las llamadas existentes en las páginas, pero YA NO se utiliza.

    El valor de shared-filters es la fuente de verdad.

    Approach:
    1. Al montar una página, restaurar directamente desde shared-filters.
    2. Marcar sync-armado=True únicamente después de que la restauración haya
       terminado.
    3. Mientras sync-armado=False, ignorar cualquier disparo inicial del
       Dropdown.
    4. Una vez armado, cualquier cambio real en Estado o Prestador actualiza
       shared-filters.

    Reasoning:
    El problema anterior hacía que la restauración de Prestador dependiera de
    una consulta PostgreSQL. Eso creaba una ventana en la cual el Dropdown
    recién montado podía emitir [] antes de que terminara la restauración.
    Aquí la restauración es únicamente una lectura del Store en memoria.

    Test Cases:
    1. shared-filters contiene ["CNT EP"]:
       -> entrar a cualquier módulo
       -> Prestador queda ["CNT EP"].

    2. entrar a una página:
       -> Dropdown aparece inicialmente []
       -> sync-armado=False
       -> [] NO sobrescribe shared-filters.

    3. restauración termina:
       -> Dropdown recibe el valor compartido
       -> sync-armado=True.

    4. usuario selecciona otro Prestador:
       -> shared-filters recibe el nuevo valor.

    5. usuario limpia Prestador:
       -> shared-filters recibe [].

    6. navegar repetidamente entre las cinco páginas:
       -> el valor continúa siendo el mismo.
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
    def restaurar_filtros(
            _timestamp,
            shared_data,
            opera_actual,
            isp_actual,
    ):
        shared_data = shared_data or {}

        estados_compartidos = shared_data.get("opera_estados", []) or []
        prestadores_compartidos = shared_data.get("isp_nombres", []) or []

        # Si la página ya trae una selección, no la reemplazamos.
        # En una página recién montada los valores serán [].
        opera_resultado = (
            no_update
            if opera_actual
            else estados_compartidos
        )

        isp_resultado = (
            no_update
            if isp_actual
            else prestadores_compartidos
        )

        # El candado se activa SOLO después de haber decidido los dos valores.
        return (
            opera_resultado,
            isp_resultado,
            True,
        )

    @callback(
        Output(
            "shared-filters",
            "data",
            allow_duplicate=True,
        ),
        Input(f"{prefix}-opera-estado", "value"),
        Input(f"{prefix}-isp-nombre", "value"),
        State(f"{prefix}-sync-armado", "data"),
        prevent_initial_call=True,
    )
    def guardar_filtros(
            opera_estados: list[str] | None,
            isp_nombres: list[str] | None,
            armado: bool,
    ):
        """
        Guarda una selección realizada en la página actual.

        Approach:
        Usar sync-armado como barrera contra el montaje inicial.

        Reasoning:
        Dash Pages puede montar un Dropdown con [] y disparar callbacks
        asociados a ese componente. Ese [] no representa una acción del
        usuario y jamás debe convertirse en el nuevo estado universal.

        Test Cases:
        - armado=False + [] -> no_update.
        - armado=False + ["CNT"] -> no_update.
        - armado=True + ["CNT"] -> guarda ["CNT"].
        - armado=True + [] -> guarda [].
        """
        if not armado:
            return no_update

        return {
            "opera_estados": opera_estados or [],
            "isp_nombres": isp_nombres or [],
        }
