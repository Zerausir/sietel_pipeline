"""dashboard/components/territory_filters.py — Provincia → Cantón → Parroquia, selección única, sin Nivel.

Se usa en Evolución y Concentración con un prefijo distinto por página
(evo-, con-) para que los IDs de componentes no choquen -- Dash exige IDs
únicos en toda la app, incluidas todas las páginas registradas.

SIN "NIVEL GEOGRÁFICO" (29-sep-2026): el nivel se deduce de lo elegido.
Nada elegido = Nacional; solo Provincia = esa provincia; Provincia y
Cantón = ese cantón; los tres = esa parroquia. Cada selector se habilita
cuando su padre tiene valor, y "Todas"/"Todos" (vacío) sube un nivel.

SELECCIÓN ÚNICA, a propósito (a diferencia de Control): el IHH y la
participación de Concentración se calculan sobre UN mercado -- un
territorio de cualquier nivel --; juntar varios en un solo índice
describiría un mercado que no existe. Evolución usa el mismo filtro para
que la selección se comparta sin traducciones entre las dos páginas; para
ver varios territorios a la vez está su desglose "Cuentas por territorio".

SINCRONIZACIÓN ENTRE PÁGINAS: "shared-territory" (app.py, fuera de
dash.page_container) guarda {province, canton, parish}. Mismo mecanismo
ya probado en producción en node_territory_filters.py/filters_shared.py
(ver sus docstrings para el porqué completo):
  - el VALOR de los tres selectores se restaura por navegación real
    (Input("obtel-url", "pathname")) o por cambios del store -- nunca con
    una consulta en medio;
  - la escritura al store solo ocurre con un clic real en UN selector
    (len(dash.ctx.triggered) == 1), lo que descarta el disparo "fantasma"
    del montaje de la página, que llega con los tres a la vez;
  - cambiar un nivel limpia en el store los niveles de abajo, y la
    restauración los limpia en pantalla -- así la cascada nunca muestra un
    cantón de otra provincia.

"{prefix}-territory-id" se DERIVA de los tres valores (sin estado propio,
sin escribir el store compartido) y valida la cadena contra
mart.dim_territorio: un cantón que no pertenece a la provincia elegida
(el instante entre el clic y la limpieza) se ignora en vez de producir un
territorio inexistente.
"""
from __future__ import annotations

import dash
from dash import Input, Output, State, callback, dcc, html

from services.queries import get_territory_options, get_territorios_validos


def territorio_desde_seleccion(province: str | None, canton: str | None, parish: str | None) -> str:
    """territorio_id del nivel más profundo elegido que forma una cadena válida."""
    validos = get_territorios_validos()
    territorio = "NACIONAL|ECUADOR"
    if province and f"PROVINCIA|{province}" in validos:
        territorio = f"PROVINCIA|{province}"
        if canton and f"CANTON|{province}|{canton}" in validos:
            territorio = f"CANTON|{province}|{canton}"
            if parish and f"PARROQUIA|{province}|{canton}|{parish}" in validos:
                territorio = f"PARROQUIA|{province}|{canton}|{parish}"
    return territorio


def seleccion_desde_territorio(territorio_id: str | None) -> dict[str, str | None]:
    """Inversa de territorio_desde_seleccion(), para escribir el store compartido."""
    partes = (territorio_id or "").split("|")
    return {
        "province": partes[1] if len(partes) > 1 and partes[0] != "NACIONAL" else None,
        "canton": partes[2] if len(partes) > 2 else None,
        "parish": partes[3] if len(partes) > 3 else None,
    }


def territory_filter_layout(prefix: str) -> html.Div:
    def selector(etiqueta: str, sufijo: str, vacio: str) -> html.Div:
        return html.Div(
            className="filter-field",
            children=[
                html.Label(etiqueta),
                dcc.Dropdown(id=f"{prefix}-{sufijo}", options=[], value=None, placeholder=vacio, clearable=True),
            ],
        )

    return html.Div(
        className="territory-grid",
        children=[
            selector("Provincia", "province", "Todas (Nacional)"),
            selector("Cantón", "canton", "Todos"),
            selector("Parroquia", "parish", "Todas"),
            dcc.Store(id=f"{prefix}-territory-id", data="NACIONAL|ECUADOR"),
        ],
    )


def _opciones_canton(province: str | None) -> tuple[list[dict[str, str]], bool]:
    if not province:
        return [], True
    return get_territory_options("CANTON", province_code=province), False


def _opciones_parroquia(province: str | None, canton: str | None) -> tuple[list[dict[str, str]], bool]:
    if not province or not canton:
        return [], True
    return get_territory_options("PARROQUIA", province_code=province, canton_code=canton), False


def register_territory_callbacks(prefix: str) -> None:
    # --- Restauración: VALOR y OPCIONES de los tres selectores en la MISMA
    # respuesta. dcc.Dropdown descarta un valor que no está en sus opciones
    # -- si el cantón restaurado llegaba antes que las opciones de su
    # provincia, quedaba en null y ese cambio se escribía en el store
    # compartido (confirmado en navegador al pasar de Evolución a
    # Concentración, 29-sep-2026). Mismo principio que _preservar_valores()
    # en node_territory_filters.py: un valor nunca llega sin sus opciones.
    @callback(
        Output(f"{prefix}-province", "options"),
        Output(f"{prefix}-province", "value"),
        Output(f"{prefix}-canton", "options"),
        Output(f"{prefix}-canton", "value"),
        Output(f"{prefix}-canton", "disabled"),
        Output(f"{prefix}-parish", "options"),
        Output(f"{prefix}-parish", "value"),
        Output(f"{prefix}-parish", "disabled"),
        Input("obtel-url", "pathname"),
        Input("shared-territory", "data"),
    )
    def restaurar_territorio(_pathname, shared_data):
        shared_data = shared_data or {}
        province, canton, parish = shared_data.get("province"), shared_data.get("canton"), shared_data.get("parish")
        opciones_canton, canton_deshabilitado = _opciones_canton(province)
        opciones_parroquia, parroquia_deshabilitada = _opciones_parroquia(province, canton)
        return (
            get_territory_options("PROVINCIA"), province,
            opciones_canton, canton, canton_deshabilitado,
            opciones_parroquia, parish, parroquia_deshabilitada,
        )

    # --- Cascada por cambios del usuario: solo opciones y habilitación (el
    # valor lo limpia dcc.Dropdown al quedar fuera de las opciones).
    @callback(
        Output(f"{prefix}-canton", "options", allow_duplicate=True),
        Output(f"{prefix}-canton", "disabled", allow_duplicate=True),
        Input(f"{prefix}-province", "value"),
        prevent_initial_call=True,
    )
    def opciones_canton(province: str | None):
        return _opciones_canton(province)

    @callback(
        Output(f"{prefix}-parish", "options", allow_duplicate=True),
        Output(f"{prefix}-parish", "disabled", allow_duplicate=True),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        prevent_initial_call=True,
    )
    def opciones_parroquia(province: str | None, canton: str | None):
        return _opciones_parroquia(province, canton)

    # --- Escritura: solo un clic real en UN selector; limpia los de abajo.
    @callback(
        Output("shared-territory", "data", allow_duplicate=True),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
        State("shared-territory", "data"),
        prevent_initial_call=True,
    )
    def guardar_territorio(province, canton, parish, shared_data):
        if len(dash.ctx.triggered) != 1:
            return dash.no_update
        shared_data = dict(shared_data or {})
        # Los niveles SUPERIORES se toman de los selectores (Inputs), nunca
        # del store: al cambiar de provincia, dcc.Dropdown limpia solo el
        # cantón/parroquia que dejaron de estar en sus opciones, y ese
        # cambio llega aquí como un disparo único de "canton"/"parish"
        # cuando el store todavía tiene la provincia ANTERIOR -- tomarla de
        # ahí revertía la provincia recién elegida (confirmado en
        # navegador, 29-sep-2026).
        triggered_id = dash.ctx.triggered_id
        if triggered_id == f"{prefix}-province":
            nuevo = {"province": province, "canton": None, "parish": None}
        elif triggered_id == f"{prefix}-canton":
            nuevo = {"province": province, "canton": canton, "parish": None}
        elif triggered_id == f"{prefix}-parish":
            nuevo = {"province": province, "canton": canton, "parish": parish}
        else:
            return dash.no_update
        if all(shared_data.get(k) == v for k, v in nuevo.items()):
            return dash.no_update
        return nuevo

    # --- territorio_id derivado (no escribe el store compartido).
    @callback(
        Output(f"{prefix}-territory-id", "data"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
    )
    def resolver_territorio(province, canton, parish):
        return territorio_desde_seleccion(province, canton, parish)
