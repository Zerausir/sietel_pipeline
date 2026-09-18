from __future__ import annotations

import dash
import dash_mantine_components as dmc
from dash import Dash, Input, Output, _dash_renderer, callback, dcc, html
from flask_login import current_user

from config import settings
from extensions import cache
from auth import init_auth

# Debe fijarse ANTES de instanciar Dash() -- dash-mantine-components 2.x
# (ver dashboard/requirements.txt) requiere React 18.2.0 explícitamente;
# sin esto los selectores de calendario (dmc.MonthPickerInput, ver
# components/ui.py:month_year_picker) no renderizan.
_dash_renderer._set_react_version("18.2.0")

app = Dash(
    __name__,
    use_pages=True,
    pages_folder="pages",
    suppress_callback_exceptions=True,
    title="OBTEL — Observatorio de Telecomunicaciones",
    update_title="Actualizando…",
    external_stylesheets=dmc.styles.ALL,
)
server = app.server
server.config["SECRET_KEY"] = settings.secret_key

# Debe llamarse antes de que Dash sirva cualquier página -- registra el
# blueprint de /login y /logout, y el before_request que bloquea todo lo
# demás sin sesión válida. Ver auth.py para el detalle de diseño.
init_auth(server)

cache.init_app(
    server,
    config={
        "CACHE_TYPE": settings.cache_type,
        "CACHE_DIR": settings.cache_dir,
        "CACHE_DEFAULT_TIMEOUT": settings.cache_timeout,
        # Techo de entradas simultáneas antes de que FileSystemCache empiece
        # a desalojar las más viejas -- generoso para el volumen real de
        # combinaciones de filtros de este dashboard, sin dejarlo sin límite.
        "CACHE_THRESHOLD": 5000,
    },
)


def navigation() -> html.Header:
    usuario_actual = (
        current_user.nombre_completo
        if current_user.is_authenticated
        else ""
    )
    # CORRECCIÓN (tras prueba real del usuario, 31-jul-2026): la primera
    # versión leía flask.request.path directamente aquí -- pero esta
    # función (parte de app.layout, una función) solo se evalúa en la
    # carga INICIAL completa del documento. La navegación interna de Dash
    # Pages (dcc.Link, incluida la del propio Panel) reutiliza esa misma
    # barra ya renderizada sin volver a pedirle nada a Flask -- por eso la
    # barra quedaba "congelada" en el estado de la primera carga (el
    # Panel, sin enlaces), aunque la URL visible cambiara a /sai/evolucion.
    #
    # La forma correcta: dejar la barra como placeholders con id fijo, y
    # que un callback (más abajo) los actualice reaccionando a
    # Input("obtel-url", "pathname") -- eso sí se dispara en cada
    # navegación, sea clic interno o carga completa.
    return html.Header(
        className="topbar",
        children=[
            dcc.Location(id="obtel-url", refresh=False),
            html.Div(
                className="brand",
                children=[
                    html.Div("OB", className="brand-mark"),
                    html.Div(
                        [
                            html.Div("OBTEL", className="brand-title"),
                            html.Div(
                                "Observatorio de Telecomunicaciones",
                                id="obtel-brand-subtitle",
                                className="brand-subtitle",
                            ),
                        ]
                    ),
                ],
            ),
            html.Nav(id="obtel-nav-links", className="nav-links", children=[]),
            html.Div(
                className="nav-user",
                children=[
                    html.Span(usuario_actual, className="nav-user-name"),
                    html.A("Salir", href="/logout", className="nav-link nav-logout"),
                ],
            ),
        ],
    )


# Estructura de navegación: grupos desplegables, más enlaces sueltos para
# grupos de un solo ítem (12-ago-2026 la versión de grupos; 18-sep-2026
# separación de "Calidad de datos"). CORREGIDO dos veces el mismo día:
# primero metía a Control dentro de "Calidad de datos" (error de
# categoría, ver abajo); la segunda corrección, al arreglar eso, dejó a
# Control y a Mapa de nodos como dos enlaces sueltos SEPARADOS en vez de
# agruparlos juntos bajo "Control e Infraestructura" como se pidió --
# confirmado con captura de pantalla en producción (18-sep-2026, cuatro
# ítems al mismo nivel en vez de tres). Queda así, definitivo:
# - Estadísticas: Evolución, IHH y participación -- SÍNTOMAS de mercado.
# - Control e Infraestructura: Control (síntomas de reporte) + Mapa de
#   nodos (exploración de infraestructura física) -- vuelven a ir
#   juntos, como estaban antes de esta sesión.
# - Calidad de datos: Discrepancias de geografía + Conflictos RUC/PEVA --
#   SOLO causas raíz accionables (colas con estado_revision), en palabras
#   del usuario: "para decirle qué debe resolver en los datos con
#   prioridad para mejorar lo que se observa en Control y en
#   Estadísticas". Mapa de nodos NO entra aquí -- es exploración, no una
#   cola con algo que resolver.
GRUPOS_NAV_SAI: list[tuple[str, list[tuple[str, str]]]] = [
    ("Estadísticas", [
        ("Evolución", "/sai/evolucion"),
        ("IHH y participación", "/sai/concentracion"),
    ]),
    ("Control e Infraestructura", [
        ("Control", "/sai/control"),
        ("Mapa de nodos", "/sai/mapa-nodos"),
    ]),
    ("Calidad de datos", [
        ("Discrepancias de geografía", "/sai/discrepancias-geografia"),
        ("Conflictos RUC/PEVA", "/sai/conflictos-ruc-peva"),
    ]),
]

# NUEVO (26-ago-2026): módulo SMA (Servicio Móvil Avanzado), sobre
# samm_pipeline/samm_db -- universo de datos y prefijo de ruta propios
# (/sma/), nunca mezclado con GRUPOS_NAV_SAI. Ver
# services/queries_sma.py para la fuente y sus advertencias.
GRUPOS_NAV_SMA: list[tuple[str, list[tuple[str, str]]]] = [
    ("Calidad de Servicio Móvil", [
        ("Calidad de Datos móviles", "/sma/datos"),
        ("Calidad de Voz", "/sma/voz"),
    ]),
]

# Mapa prefijo de ruta -> (grupos de navegación, subtítulo de la barra) --
# generaliza lo que antes era un solo "if dentro_de_sai" para admitir más
# de un módulo. Agregar un módulo nuevo en el futuro es una entrada más
# aquí, no reescribir actualizar_navegacion().
MODULOS: list[tuple[str, list[tuple[str, list[tuple[str, str]]]], str]] = [
    ("/sai/", GRUPOS_NAV_SAI, "Servicio de Acceso a Internet — SAI"),
    ("/sma/", GRUPOS_NAV_SMA, "Servicio Móvil Avanzado — SMA"),
]


def _flat_link(label: str, href: str, pathname: str) -> dcc.Link:
    """
    Enlace directo, sin desplegable -- mismo estilo visual que
    _grupo_menu() (clase "nav-link", mismo criterio de "active") para que
    no se note la diferencia estructural, pero sin el clic extra de abrir
    un menú de una sola opción. actualizar_navegacion() la usa
    automáticamente para cualquier grupo de GRUPOS_NAV_SAI/GRUPOS_NAV_SMA
    que quede con un único ítem -- no hace falta tocar esta función al
    agregar o quitar páginas de un grupo, ver el comentario sobre Mapa de
    nodos en GRUPOS_NAV_SAI (18-sep-2026).
    """
    return dcc.Link(
        label, href=href,
        className="nav-link" + (" active" if pathname == href else ""),
    )


def _grupo_menu(nombre_grupo: str, items: list[tuple[str, str]], pathname: str) -> dmc.Menu:
    """
    dmc.Menu, no un dropdown CSS/JS hecho a mano -- tres razones, no
    preferencia estética: (1) dash-mantine-components ya es dependencia
    del proyecto (calendario de períodos, steppers numéricos), no agrega
    una librería nueva; (2) dmc.MenuItem(href=...) navega igual que
    dcc.Link -- confirmado en el changelog de la librería, no es una
    integración improvisada; (3) el trigger por defecto es clic, no hover
    -- la propia documentación de Mantine advierte que un menú que solo
    se abre con hover no es accesible para quien navega con teclado.
    """
    activo_grupo = any(pathname == href for _, href in items)
    return dmc.Menu(
        [
            dmc.MenuTarget(
                html.Button(
                    [nombre_grupo, html.Span(" ▾", className="nav-menu-caret")],
                    className="nav-link nav-menu-trigger" + (" active" if activo_grupo else ""),
                )
            ),
            dmc.MenuDropdown(
                [
                    dmc.MenuItem(
                        label, href=href,
                        className="nav-menu-item" + (" active" if pathname == href else ""),
                    )
                    for label, href in items
                ],
                className="nav-menu-dropdown",
            ),
        ],
        trigger="click",
        position="bottom-start",
        shadow="md",
        withinPortal=True,
    )


@callback(
    Output("obtel-nav-links", "children"),
    Output("obtel-brand-subtitle", "children"),
    Input("obtel-url", "pathname"),
)
def actualizar_navegacion(pathname: str | None):
    """
    Se dispara en CADA cambio de ruta -- clic en dcc.Link, botón atrás/
    adelante del navegador, o carga completa -- a diferencia de leer
    flask.request en navigation(), que solo veía la ruta de la carga
    inicial. Único lugar donde se decide qué módulo está activo hoy
    (/sai/*); si se agregan más módulos en el futuro, esta es la función
    a extender.
    """
    pathname = pathname or ""
    for prefijo, grupos, subtitulo in MODULOS:
        if pathname.startswith(prefijo):
            nav = [
                dcc.Link("← Panel", href="/", className="nav-link nav-back"),
                html.Div(className="topbar-sep"),
                *[
                    _grupo_menu(nombre, items, pathname) if len(items) > 1
                    else _flat_link(items[0][0], items[0][1], pathname)
                    for nombre, items in grupos
                ],
            ]
            return nav, subtitulo

    return [], "Observatorio de Telecomunicaciones"


def serve_layout() -> html.Div:
    # Función, no un árbol fijo a nivel de módulo: navigation() lee
    # current_user en cada request, así el nombre en la barra siempre
    # corresponde a la sesión activa.
    return html.Div(
        className="app-shell",
        children=[
            navigation(),
            # Vive FUERA de dash.page_container -- Dash Pages solo reemplaza
            # el contenido de page_container al cambiar de pestaña, así que
            # este Store nunca se destruye ni se reinicia entre Evolución y
            # Concentración. Es lo que permite que el filtro geográfico
            # (Nivel/Provincia/Cantón/Parroquia) se mantenga sincronizado
            # entre ambas páginas -- ver components/territory_filters.py.
            dcc.Store(
                id="shared-territory",
                storage_type="memory",
                data={
                    "level": "NACIONAL",
                    "province": None,
                    "canton": None,
                    "parish": None,
                    "territory_id": "NACIONAL|ECUADOR",
                },
            ),
            # AMPLIADO A UNIVERSAL (20-ago-2026, a pedido del usuario) --
            # antes solo sincronizaba Estado de operación y Prestador entre
            # Evolución y Concentración; ahora es un solo estado compartido
            # entre los 5 módulos (Evolución, Concentración, Control, Mapa
            # de nodos, Discrepancias de geografía) -- ver
            # components/filters_shared.py:register_universal_opera_isp_sync().
            # Solo el VALOR elegido se sincroniza -- las OPCIONES siguen
            # siendo responsabilidad de cada página, porque dependen de su
            # propio universo geográfico (líneas vs. nodos) y de su propio
            # modelo de territorio (selección única vs. multi-select).
            dcc.Store(
                id="shared-filters",
                storage_type="memory",
                data={"opera_estados": [], "isp_nombres": []},
            ),
            # NUEVO (20-ago-2026, a pedido del usuario): Desde/Hasta (o
            # Historia Desde/Historia Hasta) sincronizado entre Evolución,
            # Concentración y Control -- los tres módulos que tienen ese
            # selector. Los mapas no participan (no tienen selector de
            # período). "Período de participación" de Concentración
            # queda deliberadamente FUERA -- es un concepto propio de esa
            # página (un mes puntual dentro del rango, no un rango en sí),
            # sin equivalente en Evolución/Control -- ver
            # components/ui.py:register_shared_period_sync().
            dcc.Store(
                id="shared-period",
                storage_type="memory",
                data={"start_period": None, "end_period": None},
            ),
            # Store propio para las páginas de nodos ISP (Mapa de Nodos,
            # Discrepancias de Geografía) -- geografía CONALI derivada de
            # coordenadas, universo distinto a shared-territory (geografía
            # de líneas reportadas). Se sincronizan solo entre ellas dos,
            # nunca con Evolución/Concentración -- ver
            # components/node_territory_filters.py.
            # Forma REDISEÑADA 11-ago-2026: listas de códigos (selección
            # múltiple e independiente por Provincia/Cantón/Parroquia), ya
            # no {level, province, canton, parish, territory_id} de un
            # solo valor por nivel.
            dcc.Store(
                id="nodo-shared-territory",
                storage_type="memory",
                data={"provincias": [], "cantones": [], "parroquias": []},
            ),
            # Store del módulo SMA (26-ago-2026) -- sincroniza Operadora/
            # CZO/territorio/Tecnología/Número/fechas SOLO entre
            # sma_datos.py y sma_voz.py (mismo criterio que
            # nodo-shared-territory: universo de datos propio, nunca
            # mezclado con SAI). Ver components/sma_filters.py.
            dcc.Store(
                id="sma-shared-filters",
                storage_type="memory",
                data={
                    "operadoras": [], "czos": [], "provincias": [], "cantones": [], "parroquias": [],
                    "tecnologias": [], "numero": None, "fecha_inicial": None, "fecha_final": None,
                },
            ),
            html.Main(dash.page_container, className="page-container"),
            html.Footer(
                children=[
                    html.Img(src="/assets/logo_gobierno.png", className="footer-logo",
                             alt="Gobierno del Ecuador"),
                    html.Div("Fuente: vistas analíticas del esquema mart en PostgreSQL."),
                ],
                className="footer",
            ),
        ],
    )


# dmc.MantineProvider es obligatorio para que CUALQUIER componente
# dash-mantine-components funcione (documentado por la propia librería) --
# envuelve serve_layout() en vez de reemplazarlo, así current_user se sigue
# leyendo en cada request (ver el comentario dentro de navigation()).
# theme alinea los componentes Mantine (el MonthPickerInput de los
# selectores de período) con la paleta navy/azul ya definida en
# assets/styles.css, en vez de dejar los colores por defecto de Mantine.
MANTINE_THEME = {
    "primaryColor": "blue",
    "colors": {
        # Mantine exige exactamente 10 tonos (índice 0 = más claro, 9 = más
        # oscuro). Interpolado a mano entre --blue (#1464f4) y --navy
        # (#0b1f33) de assets/styles.css -- misma paleta, no la de Mantine
        # por defecto.
        "blue": [
            "#eaf1fe", "#d3e2fd", "#a7c5fb", "#7aa8f9", "#4d8bf7",
            "#1464f4", "#0f50c3", "#0b1f33", "#0a1c2e", "#081824",
        ],
    },
    "fontFamily": "Inter, Segoe UI, Arial, sans-serif",
}


def serve_layout_with_theme() -> dmc.MantineProvider:
    return dmc.MantineProvider(serve_layout(), theme=MANTINE_THEME, id="obtel-mantine-provider")


app.layout = serve_layout_with_theme

if __name__ == "__main__":
    app.run(host=settings.app_host, port=settings.app_port, debug=settings.app_debug)
