"""dashboard/pages/inicio.py — Panel de opciones: selector de módulos.

Primera pantalla tras el login (path="/"). Dos módulos disponibles:
"Servicio de Acceso a Internet (SAI)" (prefijo /sai/, sietel_analitico) y,
desde el 26-ago-2026, "Servicio Móvil Avanzado (SMA)" (prefijo /sma/,
samm_pipeline/samm_db -- fuente de datos completamente distinta, ver
services/queries_sma.py). El diseño sigue el mismo patrón visual (tarjetas
de módulo, franja de estadísticas, píldora de acceso) que Zerausir/tablero,
adaptado a la paleta de OBTEL.
"""
from __future__ import annotations

from dash import dcc, html, register_page
from flask_login import current_user

register_page(__name__, path="/", name="Panel de opciones", order=0)


def layout():
    nombre = ""
    if current_user.is_authenticated:
        nombre = current_user.nombre_completo.split(" ")[0] if current_user.nombre_completo else ""

    saludo = f"Bienvenido, {nombre}" if nombre else "Bienvenido"

    return html.Div(
        className="panel-shell",
        children=[
            html.Div(
                className="panel-greeting",
                children=[
                    html.H1(saludo, className="panel-greeting-title"),
                    html.P("Selecciona un módulo para comenzar el análisis", className="panel-greeting-sub"),
                ],
            ),
            html.Div(
                className="panel-access-pill",
                children=["✓ Acceso verificado · Sesión activa"],
            ),
            html.Div("Módulos disponibles", className="section-label"),
            html.Div(
                className="modules-grid",
                children=[
                    dcc.Link(
                        href="/sai/evolucion",
                        className="mod-card",
                        children=[
                            html.Div("SAI", className="mod-card-icon blue"),
                            html.Span("Internet Fijo", className="mod-card-tag blue"),
                            html.Div("Servicio de Acceso a Internet — SAI", className="mod-card-name"),
                            html.P(
                                "Evolución del mercado, cumplimiento de reporte, e IHH y participación de "
                                "líneas dedicadas de internet fijo, calculados exclusivamente sobre datos "
                                "reportados.",
                                className="mod-card-desc",
                            ),
                            html.Div(["Abrir módulo →"], className="mod-card-arrow"),
                        ],
                    ),
                    dcc.Link(
                        href="/sma/datos",
                        className="mod-card",
                        children=[
                            html.Div("SMA", className="mod-card-icon teal"),
                            html.Span("Móvil", className="mod-card-tag teal"),
                            html.Div("Servicio Móvil Avanzado — SMA", className="mod-card-name"),
                            html.P(
                                "Calidad de datos móviles y de voz por operadora, con throughput y calidad de "
                                "llamada geolocalizados. Fuente: samm_pipeline.",
                                className="mod-card-desc",
                            ),
                            html.Div(["Abrir módulo →"], className="mod-card-arrow"),
                        ],
                    ),
                ],
            ),
            html.Div("Información del sistema", className="section-label"),
            html.Div(
                className="stats-row",
                children=[
                    html.Div(
                        className="stat-card",
                        children=[
                            html.Div("Módulos disponibles", className="stat-label"),
                            html.Div("2", className="stat-val"),
                            html.Div("Habilitado para tu perfil", className="stat-sub"),
                        ],
                    ),
                    html.Div(
                        className="stat-card",
                        children=[
                            html.Div("Cobertura", className="stat-label"),
                            html.Div("Nacional", className="stat-val"),
                            html.Div("Con desglose por provincia, cantón y parroquia", className="stat-sub"),
                        ],
                    ),
                    html.Div(
                        className="stat-card",
                        children=[
                            html.Div("Servicio activo", className="stat-label"),
                            html.Div("Líneas dedicadas", className="stat-val"),
                            html.Div("Internet fijo, módulo SAI", className="stat-sub"),
                        ],
                    ),
                ],
            ),
        ],
    )
