"""dashboard/components/ui.py — Helpers de UI compartidos entre páginas."""
from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

PALETTE = {
    "navy": "#0b1f33",
    "blue": "#1464f4",
    "cyan": "#00a7c4",
    "teal": "#00a884",
    "orange": "#f28c28",
    "red": "#d64545",
    "muted": "#61758a",
    "grid": "#e6edf4",
}


def format_number(value: Any, decimals: int = 0, empty: str = "—") -> str:
    if value is None or pd.isna(value):
        return empty
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def format_signed(value: Any, decimals: int = 0, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "—"
    number = float(value)
    sign = "+" if number > 0 else ""
    return f"{sign}{number:,.{decimals}f}{suffix}"


def clean_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convierte NaN/NaT a None -- json.dumps (y por lo tanto Dash) no acepta NaN."""
    safe = df.astype(object).where(pd.notna(df), None)
    return safe.to_dict("records")


def kpi_card(title: str, value_id: str, note_id: str | None = None) -> html.Div:
    title_row: list[Any] = [html.Span(title, className="kpi-title-text")]
    if note_id:
        title_row.append(
            html.Div(
                className="kpi-info",
                children=[
                    html.Span("i", className="kpi-info-icon"),
                    # Mismo note_id de siempre -- los callbacks existentes
                    # (Output(note_id, "children")) no necesitan cambiar,
                    # solo cambia la presentación: tooltip al pasar el
                    # cursor, en vez de texto siempre visible debajo del
                    # valor (a pedido del usuario, 30-jul-2026).
                    html.Div("", id=note_id, className="kpi-info-tooltip"),
                ],
            )
        )
    children: list[Any] = [
        html.Div(title_row, className="kpi-title-row"),
        html.Div("—", id=value_id, className="kpi-value"),
    ]
    return html.Div(children, className="kpi-card")


def month_year_dropdown(id_: str, label: str, options: list[dict[str, Any]], value: int) -> html.Div:
    """
    Selector de PERÍODO MENSUAL -- solo mes y año, sin días (a pedido del
    usuario, 31-jul-2026: el dcc.DatePickerSingle con calendario completo
    sugería una precisión diaria que los datos no tienen -- son mensuales).
    El valor es directamente periodo_id (entero AAAAMM), no una fecha --
    quien llama ya no necesita resolve_period_id() para estos selectores.
    """
    return html.Div(
        className="filter-field",
        children=[
            html.Label(label),
            dcc.Dropdown(id=id_, options=options, value=value, clearable=False),
        ],
    )


def chart_card(title: str, graph_id: str, subtitle: str | None = None) -> html.Div:
    header: list[Any] = [html.H3(title, className="chart-title")]
    if subtitle:
        header.append(html.P(subtitle, className="chart-subtitle"))
    return html.Div(
        className="chart-card",
        children=[
            html.Div(header, className="chart-header"),
            dcc.Loading(dcc.Graph(id=graph_id, config={"displaylogo": False}), type="circle"),
        ],
    )


def page_header(title: str, subtitle: str) -> html.Div:
    return html.Div(
        className="page-header",
        children=[html.H1(title), html.P(subtitle)],
    )


def error_panel(message: str) -> html.Div:
    return html.Div(
        className="error-panel",
        children=[
            html.H3("No fue posible consultar PostgreSQL"),
            html.P(message),
            html.P("Revise el archivo .env y confirme que las vistas mart fueron creadas."),
        ],
    )


def empty_figure(message: str = "No hay datos para los filtros seleccionados") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"size": 15, "color": PALETTE["muted"]},
    )
    fig.update_layout(
        template="plotly_white",
        height=360,
        margin={"l": 30, "r": 20, "t": 20, "b": 35},
        xaxis={"visible": False},
        yaxis={"visible": False},
    )
    return fig


def compute_mapbox_view(
        lat_min: float, lat_max: float, lon_min: float, lon_max: float,
        default_zoom: float = 5.2,
) -> tuple[dict[str, float], float]:
    """
    Centro y zoom aproximados de un mapbox a partir de un rango de
    coordenadas -- Scattermapbox no tiene un "fit bounds" automático como
    Leaflet, así que se estima el zoom por el tamaño del rango (heurística
    simple, no exacta, pero suficiente para que el mapa quede centrado y a
    una escala razonable al elegir un territorio).
    """
    if not all(map(lambda v: v is not None and not pd.isna(v), (lat_min, lat_max, lon_min, lon_max))):
        return {"lat": -1.5, "lon": -78.5}, default_zoom

    center = {"lat": (lat_min + lat_max) / 2, "lon": (lon_min + lon_max) / 2}
    rango = max(lat_max - lat_min, lon_max - lon_min)
    if rango < 0.02:
        zoom = 13.0
    elif rango < 0.05:
        zoom = 12.0
    elif rango < 0.1:
        zoom = 11.0
    elif rango < 0.2:
        zoom = 10.0
    elif rango < 0.5:
        zoom = 9.0
    elif rango < 1:
        zoom = 8.0
    elif rango < 2:
        zoom = 7.0
    elif rango < 4:
        zoom = 6.3
    else:
        zoom = default_zoom
    return center, zoom


def mapbox_polygon_layers(geojson: dict, color: str) -> list[dict[str, Any]]:
    """Relleno semi-transparente + borde del territorio seleccionado, para
    layout.mapbox.layers. Dos capas separadas (fill + line) porque un solo
    layer de tipo 'fill' en Plotly no dibuja borde propio."""
    return [
        {"source": geojson, "type": "fill", "color": color, "opacity": 0.16, "below": "traces"},
        {"source": geojson, "type": "line", "color": color, "line": {"width": 1.5}, "below": "traces"},
    ]


def style_figure(fig: go.Figure, *, height: int = 380, hovermode: str = "x unified") -> go.Figure:
    fig.update_layout(
        template="plotly_white",
        height=height,
        hovermode=hovermode,
        margin={"l": 55, "r": 20, "t": 25, "b": 55},
        paper_bgcolor="white",
        plot_bgcolor="white",
        font={"family": "Inter, Segoe UI, Arial, sans-serif", "color": PALETTE["navy"]},
        legend={"orientation": "h", "y": 1.12, "x": 0},
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor=PALETTE["grid"], zerolinecolor=PALETTE["grid"])
    return fig
