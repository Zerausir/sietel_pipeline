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
        "CACHE_TYPE": "SimpleCache",
        "CACHE_DEFAULT_TIMEOUT": settings.cache_timeout,
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
    dentro_de_sai = (pathname or "").startswith("/sai/")
    if not dentro_de_sai:
        return [], "Observatorio de Telecomunicaciones"

    nav = [
        dcc.Link("← Panel", href="/", className="nav-link nav-back"),
        html.Div(className="topbar-sep"),
        dcc.Link("Evolución", href="/sai/evolucion", className="nav-link"),
        dcc.Link("IHH y participación", href="/sai/concentracion", className="nav-link"),
        dcc.Link("Mapa de nodos", href="/sai/mapa-nodos", className="nav-link"),
        dcc.Link("Discrepancias de geografía", href="/sai/discrepancias-geografia", className="nav-link"),
        dcc.Link("Control", href="/sai/control", className="nav-link"),
    ]
    return nav, "Servicio de Acceso a Internet — SAI"


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
            # Mismo principio que shared-territory -- vive fuera de
            # page_container para sobrevivir al cambio de pestaña.
            # Sincroniza Estado de operación y Prestador entre Evolución y
            # Concentración (31-jul-2026, a pedido del usuario). NO incluye
            # "Período de participación" -- ese filtro es exclusivo de
            # Concentración, no tiene equivalente en Evolución.
            dcc.Store(
                id="shared-filters",
                storage_type="memory",
                data={"opera_estados": [], "isp_nombres": []},
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
            html.Main(dash.page_container, className="page-container"),
            html.Footer(
                "Fuente: vistas analíticas del esquema mart en PostgreSQL.",
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
