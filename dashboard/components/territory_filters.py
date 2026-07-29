"""dashboard/components/territory_filters.py — Filtro geográfico en cascada.

Se usa en ambas páginas (Evolución, Concentración) con un prefijo distinto
por página (evo-, con-) para que los IDs de componentes no choquen -- Dash
exige IDs únicos en toda la app, incluidas todas las páginas registradas.
"""
from __future__ import annotations

from dash import Input, Output, State, callback, dcc, html, no_update

from services.queries import get_territory_options

LEVEL_OPTIONS = [
    {"label": "Nacional", "value": "NACIONAL"},
    {"label": "Provincia", "value": "PROVINCIA"},
    {"label": "Cantón", "value": "CANTON"},
    {"label": "Parroquia", "value": "PARROQUIA"},
]


def territory_filter_layout(prefix: str) -> html.Div:
    return html.Div(
        className="territory-grid",
        children=[
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Nivel geográfico"),
                    dcc.Dropdown(
                        id=f"{prefix}-level",
                        options=LEVEL_OPTIONS,
                        value="NACIONAL",
                        clearable=False,
                    ),
                ],
            ),
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Provincia"),
                    dcc.Dropdown(id=f"{prefix}-province", disabled=True, clearable=False),
                ],
            ),
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Cantón"),
                    dcc.Dropdown(id=f"{prefix}-canton", disabled=True, clearable=False),
                ],
            ),
            html.Div(
                className="filter-field",
                children=[
                    html.Label("Parroquia"),
                    dcc.Dropdown(id=f"{prefix}-parish", disabled=True, clearable=False),
                ],
            ),
            dcc.Store(id=f"{prefix}-territory-id", data="NACIONAL|ECUADOR"),
        ],
    )


def register_territory_callbacks(prefix: str) -> None:
    @callback(
        Output(f"{prefix}-province", "options"),
        Output(f"{prefix}-province", "value"),
        Output(f"{prefix}-province", "disabled"),
        Input(f"{prefix}-level", "value"),
    )
    def update_provinces(level: str):
        enabled = level in {"PROVINCIA", "CANTON", "PARROQUIA"}
        if not enabled:
            return [], None, True
        options = get_territory_options("PROVINCIA")
        value = options[0]["value"] if options else None
        return options, value, False

    @callback(
        Output(f"{prefix}-canton", "options"),
        Output(f"{prefix}-canton", "value"),
        Output(f"{prefix}-canton", "disabled"),
        Input(f"{prefix}-level", "value"),
        Input(f"{prefix}-province", "value"),
    )
    def update_cantons(level: str, province: str | None):
        enabled = level in {"CANTON", "PARROQUIA"} and bool(province)
        if not enabled:
            return [], None, True
        options = get_territory_options("CANTON", province_code=province)
        value = options[0]["value"] if options else None
        return options, value, False

    @callback(
        Output(f"{prefix}-parish", "options"),
        Output(f"{prefix}-parish", "value"),
        Output(f"{prefix}-parish", "disabled"),
        Input(f"{prefix}-level", "value"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
    )
    def update_parishes(level: str, province: str | None, canton: str | None):
        enabled = level == "PARROQUIA" and bool(province) and bool(canton)
        if not enabled:
            return [], None, True
        options = get_territory_options("PARROQUIA", province_code=province, canton_code=canton)
        value = options[0]["value"] if options else None
        return options, value, False

    @callback(
        Output(f"{prefix}-territory-id", "data"),
        Input(f"{prefix}-level", "value"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-parish", "value"),
        State(f"{prefix}-territory-id", "data"),
    )
    def resolve_territory(
        level: str,
        province: str | None,
        canton: str | None,
        parish: str | None,
        current: str,
    ):
        if level == "NACIONAL":
            return "NACIONAL|ECUADOR"
        if level == "PROVINCIA" and province:
            return f"PROVINCIA|{province}"
        if level == "CANTON" and province and canton:
            return f"CANTON|{province}|{canton}"
        if level == "PARROQUIA" and province and canton and parish:
            return f"PARROQUIA|{province}|{canton}|{parish}"
        return current or no_update
