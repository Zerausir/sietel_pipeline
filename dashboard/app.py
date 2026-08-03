from __future__ import annotations

import dash
from dash import Dash, dcc, html
from flask import request
from flask_login import current_user

from config import settings
from extensions import cache
from auth import init_auth

app = Dash(
    __name__,
    use_pages=True,
    pages_folder="pages",
    suppress_callback_exceptions=True,
    title="OBTEL — Observatorio de Telecomunicaciones",
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
    # Navegación consciente de la ruta actual (31-jul-2026, a pedido del
    # usuario): en el Panel de opciones (path "/") no tiene sentido mostrar
    # los enlaces de un módulo que todavía no se eligió. Dentro de un
    # módulo (hoy, /sai/*) se muestra un enlace de regreso al Panel, más
    # los enlaces propios de ESE módulo. request.path funciona aquí porque
    # serve_layout() -- y por lo tanto navigation() -- se ejecuta dentro
    # del contexto de la request de Flask en cada carga de página.
    dentro_de_sai = request.path.startswith("/sai/")

    contenido_nav: list = []
    if dentro_de_sai:
        contenido_nav.append(dcc.Link("← Panel", href="/", className="nav-link nav-back"))
        contenido_nav.append(html.Div(className="topbar-sep"))
        contenido_nav.append(dcc.Link("Evolución", href="/sai/evolucion", className="nav-link"))
        contenido_nav.append(dcc.Link("IHH y participación", href="/sai/concentracion", className="nav-link"))

    return html.Header(
        className="topbar",
        children=[
            html.Div(
                className="brand",
                children=[
                    html.Div("OB", className="brand-mark"),
                    html.Div(
                        [
                            html.Div("OBTEL", className="brand-title"),
                            html.Div(
                                "Servicio de Acceso a Internet — SAI" if dentro_de_sai else "Observatorio de Telecomunicaciones",
                                className="brand-subtitle",
                            ),
                        ]
                    ),
                ],
            ),
            html.Nav(className="nav-links", children=contenido_nav),
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
