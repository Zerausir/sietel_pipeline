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

from dash import Input, Output, State, callback, ctx, dcc, html, no_update

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
        Input("shared-filters", "data"),
        State(f"{prefix}-isp-nombre", "value"),
    )
    def actualizar_opciones_isp(
            territory_id,
            shared_data,
            valores_actuales,
    ):
        """
        Construye las opciones del Prestador y garantiza que cualquier Prestador
        seleccionado en shared-filters permanezca representable en el Dropdown.

        Approach:
        Las opciones normales provienen del territorio de la página. Después se
        agregan los valores seleccionados universalmente que todavía no estén
        presentes.

        Reasoning:
        Dash Dropdown necesita que los valores seleccionados sean representables
        dentro de options. Los cinco módulos no necesariamente tienen el mismo
        universo de Prestadores para un territorio dado.

        Test Cases:

        shared = {"isp_nombres": ["CNT EP"]}
        opciones SQL = ["CONECEL", "MOVISTAR"]
        resultado:
            ["CONECEL", "MOVISTAR", "CNT EP"]

        shared = {"isp_nombres": []}
        opciones SQL = ["CONECEL", "MOVISTAR"]
        resultado:
            ["CONECEL", "MOVISTAR"]
        """

        if not territory_id:
            opciones = []
        else:
            opciones = get_provider_options(territory_id)

        shared_data = shared_data or {}

        valores_compartidos = (
                shared_data.get("isp_nombres", [])
                or []
        )

        valores_actuales = valores_actuales or []

        valores_a_conservar = (
                set(valores_actuales)
                | set(valores_compartidos)
        )

        existentes = {
            str(opcion["value"])
            for opcion in opciones
        }

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
    Sincroniza Estado de operación y Prestador mediante shared-filters.

    Los cinco módulos participantes son:

        - Evolución
        - IHH y participación
        - Control
        - Mapa de nodos
        - Discrepancias de geografía

    shared-filters es la única fuente de verdad del VALOR seleccionado.

    Las OPTIONS de cada Dropdown siguen siendo locales a cada página.

    Approach:
    Separar completamente navegación/restauración de edición/persistencia.

    RESTAURACIÓN:
        obtel-url.pathname + shared-filters.data
            -> Dropdown.value

    PERSISTENCIA:
        Dropdown.value
            -> shared-filters.data

    No usamos sync-armado para determinar si una modificación corresponde al
    usuario. La navegación se detecta mediante dcc.Location(id="obtel-url"),
    que vive fuera de dash.page_container y cambia en cada navegación de
    Dash Pages.

    Reasoning:
    Un Store ubicado dentro de una página no es una señal fiable de
    navegación. Además, usar el mismo Store local como Input y Output del
    callback de restauración introduce una dependencia circular innecesaria.

    La URL, en cambio, es una señal explícita de navegación.

    Test Cases:

    1. Evolución selecciona ["CNT EP"]:
       shared-filters = {"isp_nombres": ["CNT EP"]}

    2. Navegar a /sai/concentracion:
       con-isp-nombre.value = ["CNT EP"]

    3. Navegar a /sai/mapa-nodos:
       mnodo-isp-nombre.value = ["CNT EP"]

    4. Navegar a /sai/discrepancias-geografia:
       dnodo-isp-nombre.value = ["CNT EP"]

    5. Control selecciona ["CONECEL"]:
       shared-filters = {"isp_nombres": ["CONECEL"]}

    6. Navegar a Evolución:
       evo-isp-nombre.value = ["CONECEL"]

    7. Usuario limpia Prestador:
       shared-filters["isp_nombres"] = []

    8. Navegar a cualquier módulo:
       Dropdown.value = []

    9. El Dropdown inicial de una página es []:
       nunca sobrescribe shared-filters por el simple hecho de montar
       la página, porque la restauración se produce mediante pathname.
    """

    # ------------------------------------------------------------------
    # RESTAURACIÓN DESDE shared-filters
    # ------------------------------------------------------------------

    @callback(
        Output(f"{prefix}-opera-estado", "value"),
        Output(f"{prefix}-isp-nombre", "value"),
        Input("obtel-url", "pathname"),
        Input("shared-filters", "data"),
    )
    def restaurar_filtros(
            pathname,
            shared_data,
    ):
        """
        Restaura el estado universal cuando:

        1. se navega a esta página, o
        2. cambia shared-filters.

        Este callback NUNCA escribe shared-filters.
        """

        shared_data = shared_data or {}

        estados_compartidos = (
                shared_data.get("opera_estados", [])
                or []
        )

        prestadores_compartidos = (
                shared_data.get("isp_nombres", [])
                or []
        )

        # No hacemos ninguna consulta SQL.
        #
        # shared-filters ya contiene exactamente el valor que debe mostrar
        # esta página.
        return (
            estados_compartidos,
            prestadores_compartidos,
        )

    # ------------------------------------------------------------------
    # PERSISTENCIA DEL CAMBIO HECHO POR EL USUARIO
    # ------------------------------------------------------------------

    @callback(
        Output(
            "shared-filters",
            "data",
            allow_duplicate=True,
        ),
        Input(f"{prefix}-opera-estado", "value"),
        Input(f"{prefix}-isp-nombre", "value"),
        State("shared-filters", "data"),
        prevent_initial_call=True,
    )
    def guardar_filtros(
            opera_estados,
            isp_nombres,
            shared_data,
    ):
        """
        Persiste únicamente el Dropdown que realmente cambió.

        Approach:
        ctx.triggered_id identifica si cambió Estado de operación o Prestador.

        Reasoning:
        No debemos reconstruir shared-filters a partir de los dos Dropdowns
        porque uno de ellos puede contener el estado recién restaurado desde
        shared-filters.

        Si el usuario cambia Prestador, solamente modificamos isp_nombres.

        Si cambia Estado, solamente modificamos opera_estados.

        Esto evita que un valor local viejo sobrescriba accidentalmente el
        otro filtro universal.

        Test Cases:

        Prestador:
            shared = {"opera_estados": ["ACTIVO"], "isp_nombres": ["CNT"]}
            usuario cambia Prestador a ["CONECEL"]
            ->
            {
                "opera_estados": ["ACTIVO"],
                "isp_nombres": ["CONECEL"]
            }

        Estado:
            shared = {"opera_estados": ["ACTIVO"], "isp_nombres": ["CNT"]}
            usuario cambia Estado a ["INACTIVO"]
            ->
            {
                "opera_estados": ["INACTIVO"],
                "isp_nombres": ["CNT"]
            }

        Limpiar Prestador:
            isp_nombres = []
            ->
            isp_nombres = []
        """

        shared_data = dict(shared_data or {})

        triggered_id = ctx.triggered_id

        if triggered_id == f"{prefix}-isp-nombre":
            shared_data["isp_nombres"] = isp_nombres or []

        elif triggered_id == f"{prefix}-opera-estado":
            shared_data["opera_estados"] = opera_estados or []

        else:
            return no_update

        return shared_data
