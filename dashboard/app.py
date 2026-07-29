from __future__ import annotations

import dash
from dash import Dash, dcc, html
from flask_login import current_user

from config import settings
from extensions import cache
from auth import init_auth

app = Dash(
    __name__,
    use_pages=True,
    pages_folder="pages",
    suppress_callback_exceptions=True,
    title="Líneas dedicadas | SIETEL",
    update_title="Actualizando…",
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
    return html.Header(
        className="topbar",
        children=[
            html.Div(
                className="brand",
                children=[
                    html.Div("SI", className="brand-mark"),
                    html.Div(
                        [
                            html.Div("SIETEL Analítico", className="brand-title"),
                            html.Div("Líneas dedicadas", className="brand-subtitle"),
                        ]
                    ),
                ],
            ),
            html.Nav(
                className="nav-links",
                children=[
                    dcc.Link("Evolución", href="/", className="nav-link"),
                    dcc.Link("IHH y participación", href="/concentracion", className="nav-link"),
                ],
            ),
            html.Div(
                className="nav-user",
                children=[
                    html.Span(usuario_actual, className="nav-user-name"),
                    html.A("Salir", href="/logout", className="nav-link nav-logout"),
                ],
            ),
        ],
    )


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
            html.Main(dash.page_container, className="page-container"),
            html.Footer(
                "Fuente: vistas analíticas del esquema mart en PostgreSQL.",
                className="footer",
            ),
        ],
    )


app.layout = serve_layout

if __name__ == "__main__":
    app.run(host=settings.app_host, port=settings.app_port, debug=settings.app_debug)
