"""dashboard/components/filters_shared.py — Estado de operación y Prestador, sincronizados.

Mismo patrón que components/territory_filters.py: la selección se
restaura desde -- y se guarda en -- el dcc.Store "shared-filters" que vive
en app.py, fuera de dash.page_container. Elegir un Estado de operación o
un Prestador en Evolución y luego entrar a Concentración mantiene la misma
selección (31-jul-2026, a pedido del usuario).

NO incluye "Período de participación" -- ese filtro es exclusivo de la
página de Concentración (con-current-period), sin equivalente en
Evolución, y se queda como estado local de esa página, no sincronizado.
"""
from __future__ import annotations

from dash import Input, Output, State, callback, dcc, html

from services.queries import get_operation_states, get_provider_options


def shared_filters_layout(prefix: str) -> html.Div:
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
    @callback(
        Output(f"{prefix}-opera-estado", "value"),
        Input("shared-filters", "data"),
    )
    def restore_opera_estado(shared_data):
        return (shared_data or {}).get("opera_estados", [])

    @callback(
        Output(f"{prefix}-isp-nombre", "options"),
        Output(f"{prefix}-isp-nombre", "value"),
        Input(f"{prefix}-territory-id", "data"),
        State("shared-filters", "data"),
    )
    def restore_isp_nombre(territory_id: str, shared_data):
        # Las OPCIONES dependen del territorio (un prestador presente en
        # Provincia X no necesariamente aparece en la lista de otra
        # provincia) -- eso NO se sincroniza, se recalcula por página. El
        # VALOR elegido sí se restaura desde el store compartido, si sigue
        # siendo una opción válida para el territorio actual.
        if not territory_id:
            return [], []
        options = get_provider_options(territory_id)
        deseados = (shared_data or {}).get("isp_nombres", [])
        valores_validos = {o["value"] for o in options}
        value = [v for v in deseados if v in valores_validos]
        return options, value

    @callback(
        Output("shared-filters", "data", allow_duplicate=True),
        Input(f"{prefix}-opera-estado", "value"),
        Input(f"{prefix}-isp-nombre", "value"),
        prevent_initial_call=True,
        # allow_duplicate=True: igual que en territory_filters.py, ambas
        # páginas registran esta misma salida -- solo la página visible
        # tiene sus Inputs "vivos", así que en la práctica nunca compiten.
    )
    def guardar_filtros(opera_estados: list[str] | None, isp_nombres: list[str] | None):
        return {"opera_estados": opera_estados or [], "isp_nombres": isp_nombres or []}
