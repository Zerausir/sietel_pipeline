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
    children: list[Any] = [
        html.Div(title, className="kpi-title"),
        html.Div("—", id=value_id, className="kpi-value"),
    ]
    if note_id:
        children.append(html.Div("", id=note_id, className="kpi-note"))
    return html.Div(children, className="kpi-card")


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
