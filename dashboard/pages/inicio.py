"""Página provisional -- reemplazar cuando pages/evolucion.py esté listo."""
import dash
from dash import html

dash.register_page(__name__, path="/", name="Inicio")


def layout():
    return html.Div(
        className="placeholder-page",
        children=[
            html.H2("Dashboard SIETEL — en construcción"),
            html.P(
                "El login y la conexión a la base analítica ya están funcionando. "
                "Las páginas de Evolución e IHH/Participación están pendientes de reconstrucción."
            ),
        ],
    )
