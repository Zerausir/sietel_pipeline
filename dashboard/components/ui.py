"""dashboard/components/ui.py — Helpers de UI compartidos entre páginas."""
from __future__ import annotations

from typing import Any

import dash_mantine_components as dmc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html, no_update

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

# Paleta Okabe-Ito (Okabe & Ito, 2008) -- estándar de facto para paletas
# categóricas seguras ante daltonismo (protanopia/deuteranopia/tritanopia),
# citada consistentemente en guías de accesibilidad de datos 2025-2026
# (IBM Carbon, ColorBrewer, UK Government Analysis Function). SOLO para
# gráficos con 3+ categorías simultáneas donde el color ES el dato (ej.
# "Composición por velocidad", 7 rangos) -- los gráficos de 1-2 series de
# este dashboard ya usan PALETTE (navy/blue/teal/red con significado fijo
# positivo/negativo, que no se debe tocar). Más de 8 categorías en un
# mismo gráfico deja de ser seguro incluso con esta paleta -- dividir el
# gráfico, no agregar un noveno color.
OKABE_ITO = [
    "#E69F00",  # naranja
    "#56B4E9",  # celeste
    "#009E73",  # verde azulado
    "#F0E442",  # amarillo
    "#0072B2",  # azul
    "#D55E00",  # bermellón
    "#CC79A7",  # púrpura rosado
    "#000000",  # negro -- último recurso si hace falta una 8va categoría
]


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


def kpi_card(title: str, value_id: str, note_id: str | None = None, sparkline_id: str | None = None) -> html.Div:
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
    if sparkline_id:
        # Solo para KPI que NO tienen ya un gráfico completo de tendencia
        # en la misma página -- si ya existe uno (ej. "Cuentas reportadas"
        # con su línea debajo, "IHH" con la suya), agregar un sparkline
        # sería tinta redundante mostrando el mismo dato dos veces (Tufte,
        # "erase redundant data-ink"). Un número aislado sin ningún
        # gráfico en la página sí es un hueco real de contexto -- ver
        # register de cada página para el criterio aplicado en cada caso.
        children.append(
            dcc.Graph(
                id=sparkline_id,
                config={"staticPlot": True, "displayModeBar": False},
                className="kpi-sparkline",
            )
        )
    return html.Div(children, className="kpi-card")


def transformar_signed_log(valores: pd.Series) -> pd.Series:
    """
    sign(v) * log10(1 + |v|) -- para graficar series de variación % con
    outliers extremos (un mes de +28.000% que aplasta visualmente todo lo
    demás contra el cero) sin perder el signo (positivo/negativo). Un eje
    logarítmico normal de Plotly (yaxis type="log") NO sirve aquí --
    descarta silenciosamente los valores negativos, y esta serie los tiene
    (meses con caída). Usada por primera vez en Control (13-ago-2026,
    "Variación en el tiempo"), extraída aquí para no triplicar la misma
    lógica cuando Evolución la necesitó también.
    """
    return np.sign(valores) * np.log10(1 + valores.abs())


def signed_log_tickvals(valores_transformados: pd.Series) -> tuple[list[float], list[str]]:
    """
    tickvals/ticktext para un eje con transformar_signed_log() ya aplicado
    -- las marcas del eje deben mostrar el PORCENTAJE REAL ("+300%"), no
    el valor transformado ("2.48"), o nadie que no lea el subtítulo sabe
    qué significa el número. Genera marcas "redondas" (10, 30, 100, 300,
    1.000...) acotadas al rango real de los datos, en ambos signos.
    """
    validos = valores_transformados.dropna()
    if validos.empty:
        return [0.0], ["0%"]
    transformada_min, transformada_max = float(validos.min()), float(validos.max())
    candidatos_pct = [10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000]
    tickvals: list[float] = [0.0]
    ticktext: list[str] = ["0%"]
    for pct in candidatos_pct:
        t = float(np.log10(1 + pct))
        if t <= transformada_max + 0.05:
            tickvals.append(t)
            ticktext.append(f"+{pct:,}%".replace(",", "."))
        if -t >= transformada_min - 0.05:
            tickvals.append(-t)
            ticktext.append(f"-{pct:,}%".replace(",", "."))
    orden = sorted(range(len(tickvals)), key=lambda i: tickvals[i])
    return [tickvals[i] for i in orden], [ticktext[i] for i in orden]


def build_sparkline_figure(
        values: list[float] | Any, color: str, height: int = 34,
) -> go.Figure:
    """
    Mini-gráfico de tendencia dentro de una tarjeta KPI (sparkline) --
    sin ejes, sin cuadrícula, sin leyenda: el único propósito es responder
    "¿este número es parte de una subida, una caída, o es estable?" de un
    vistazo, no permitir lectura precisa (esa vive en el gráfico completo
    de abajo, cuando existe, o en la tabla de detalle). Punto final
    marcado con un círculo -- convención estándar de sparkline para anclar
    dónde está el valor "ahora" dentro de la serie.
    """
    valores_validos = [v for v in values if v is not None and not pd.isna(v)]
    if len(valores_validos) < 2:
        fig = go.Figure()
        fig.update_layout(
            height=height, margin={"l": 0, "r": 0, "t": 0, "b": 0},
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
        )
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        return fig

    x = list(range(len(values)))
    hex_color = color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=values, mode="lines", line={"color": color, "width": 1.8},
        fill="tozeroy", fillcolor=f"rgba({r}, {g}, {b}, 0.12)",
        hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=[x[-1]], y=[values[-1]], mode="markers", marker={"color": color, "size": 5},
        hoverinfo="skip",
    ))
    fig.update_layout(
        height=height, margin={"l": 0, "r": 0, "t": 2, "b": 2},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", showlegend=False,
    )
    fig.update_xaxes(visible=False, showgrid=False, zeroline=False)
    fig.update_yaxes(visible=False, showgrid=False, zeroline=False)
    return fig


def _periodo_id_to_iso(periodo_id: int) -> str:
    """periodo_id en mart.dim_periodo es SIEMPRE anio*100+mes (ver
    sql/02_ddl_mart.sql, INSERT de dim_periodo) -- la conversión es
    aritmética directa, no requiere consultar la tabla. Se ancla al día 01
    porque MonthPickerInput exige una fecha ISO completa como value/minDate/
    maxDate, aunque en el calendario no se muestre ni se pueda elegir día."""
    anio, mes = divmod(int(periodo_id), 100)
    return f"{anio:04d}-{mes:02d}-01"


def _iso_to_periodo_id(iso_value: str) -> int:
    anio, mes = (int(parte) for parte in iso_value.split("-")[:2])
    return anio * 100 + mes


def month_year_picker(id_: str, label: str, value: int, min_period: int, max_period: int) -> html.Div:
    """
    Selector de PERÍODO MENSUAL con calendario de meses (dash-mantine-
    components MonthPickerInput): cuadrícula de 12 meses por año,
    navegación año a año con flechas -- SIN nivel de día.

    Reemplaza la lista plana de ~180 opciones (dcc.Dropdown) que obligaba a
    hacer scroll desde 2011-01 hasta el período más reciente (a pedido del
    usuario, 11-ago-2026). No es un regreso al dcc.DatePickerSingle
    descartado el 31-jul-2026 -- aquel exponía un calendario de DÍAS, que
    sugería una precisión que los datos mensuales no tienen; este solo
    navega por año y mes, igual que la lista que reemplaza.

    Contrato externo: `id_` sigue siendo el id que leen las demás
    callbacks de la página, pero ahora vía la propiedad "data" de un
    dcc.Store (no "value" de un dcc.Dropdown) -- quien lo consuma debe usar
    Input(id_, "data") / State(id_, "data"). Ver
    register_month_year_picker_callback() para el callback que traduce la
    fecha elegida a periodo_id (entero AAAAMM) y alimenta ese Store.
    """
    return html.Div(
        className="filter-field",
        children=[
            html.Label(label),
            dmc.MonthPickerInput(
                id=f"{id_}-picker",
                value=_periodo_id_to_iso(value),
                minDate=_periodo_id_to_iso(min_period),
                maxDate=_periodo_id_to_iso(max_period),
                valueFormat="MMMM YYYY",
                clearable=False,
                className="month-year-picker",
            ),
            dcc.Store(id=id_, data=value),
        ],
    )


def register_month_year_picker_callback(id_: str) -> None:
    """Registrar UNA VEZ por cada selector creado con month_year_picker()
    -- mismo patrón que register_shared_filters_callbacks() /
    register_territory_callbacks(): función que registra un @callback,
    llamada a nivel de módulo en cada página que la usa."""

    @callback(
        Output(id_, "data"),
        Input(f"{id_}-picker", "value"),
    )
    def _sincronizar_periodo(iso_value: str | None):
        if not iso_value:
            # clearable=False debería impedir esto en la práctica; se deja
            # como defensa explícita en vez de asumir que nunca ocurre.
            return no_update
        return _iso_to_periodo_id(iso_value)


def filters_summary_bar(id_: str) -> html.Div:
    """
    Resumen visual ("breadcrumb") de los filtros activos, estilo el panel
    de filtros de Power BI -- evita que el usuario tenga que revisar los
    6+ selectores de arriba para saber qué está mirando en los gráficos.
    Se actualiza vía register_filters_summary_callback(); esta función
    solo crea el contenedor vacío que la callback rellena.
    """
    return html.Div(id=id_, className="filters-summary")


def _filter_chip(label: str, value: str) -> html.Span:
    return html.Span(
        className="filter-chip",
        children=[html.Span(f"{label}: ", className="filter-chip-label"), value],
    )


NIVEL_LABELS = {"NACIONAL": "Nacional", "PROVINCIA": "Provincia", "CANTON": "Cantón", "PARROQUIA": "Parroquia"}


def register_filters_summary_callback(prefix: str) -> None:
    """
    Registrar UNA VEZ por página -- arma la barra de chips a partir de los
    Inputs de territorio (components/territory_filters.py), período
    (month_year_picker) y estado/prestador (components/filters_shared.py)
    de esa misma página. Lee las ETIQUETAS desde la propiedad "options" de
    cada Dropdown ya montado -- no vuelve a consultar PostgreSQL para
    territorio ni prestador; para período sí usa get_periods(), pero esa
    consulta ya está cacheada 15 min (services/queries.py).

    Alcance deliberadamente limitado a los filtros COMUNES a ambas páginas
    (territorio, rango de período, estado, prestador). "Período de
    participación" y "Prestador para evolución" -- exclusivos de
    Concentración -- no están en este resumen; ya son visibles en su propio
    selector, a un clic de los KPIs que afectan.
    """
    from services.queries import get_periods  # import perezoso: evita ciclo de imports con services.queries

    @callback(
        Output(f"{prefix}-filters-summary", "children"),
        Input(f"{prefix}-level", "value"),
        Input(f"{prefix}-province", "value"),
        Input(f"{prefix}-province", "options"),
        Input(f"{prefix}-canton", "value"),
        Input(f"{prefix}-canton", "options"),
        Input(f"{prefix}-parish", "value"),
        Input(f"{prefix}-parish", "options"),
        Input(f"{prefix}-start-period", "data"),
        Input(f"{prefix}-end-period", "data"),
        Input(f"{prefix}-opera-estado", "value"),
        Input(f"{prefix}-isp-nombre", "value"),
        Input(f"{prefix}-isp-nombre", "options"),
    )
    def _actualizar_resumen(
            level: str | None,
            province: str | None, province_opts: list[dict[str, str]] | None,
            canton: str | None, canton_opts: list[dict[str, str]] | None,
            parish: str | None, parish_opts: list[dict[str, str]] | None,
            start_period: int | None, end_period: int | None,
            opera_estados: list[str] | None,
            isp_nombres: list[str] | None, isp_opts: list[dict[str, str]] | None,
    ):
        def _etiqueta(valor: str | None, opciones: list[dict[str, str]] | None) -> str:
            return next((o["label"] for o in (opciones or []) if o["value"] == valor), valor or "")

        if not level or level == "NACIONAL":
            territorio_label = "Nacional"
        else:
            partes = [NIVEL_LABELS.get(level, level)]
            if province:
                partes.append(_etiqueta(province, province_opts))
            if canton and level in {"CANTON", "PARROQUIA"}:
                partes.append(_etiqueta(canton, canton_opts))
            if parish and level == "PARROQUIA":
                partes.append(_etiqueta(parish, parish_opts))
            territorio_label = " › ".join(p for p in partes if p)

        chips = [_filter_chip("Territorio", territorio_label)]

        if start_period and end_period:
            periods = get_periods()

            def _periodo_label(periodo_id: int) -> str:
                fila = periods[periods["periodo_id"] == int(periodo_id)]
                return str(fila.iloc[0]["anio_mes"]) if not fila.empty else str(periodo_id)

            inicio, fin = sorted((int(start_period), int(end_period)))
            chips.append(_filter_chip("Período", f"{_periodo_label(inicio)} – {_periodo_label(fin)}"))

        chips.append(_filter_chip("Estado", ", ".join(opera_estados) if opera_estados else "Todos"))

        if isp_nombres:
            etiquetas = [_etiqueta(v, isp_opts) for v in isp_nombres]
            texto_isp = ", ".join(etiquetas[:2])
            if len(etiquetas) > 2:
                texto_isp += f" y {len(etiquetas) - 2} más"
        else:
            texto_isp = "Todos"
        chips.append(_filter_chip("Prestador", texto_isp))

        return chips


def numeric_stepper(id_: str, label: str, value: int, min_value: int = 1, step: int = 1) -> html.Div:
    """
    Selector numérico con botones +/- (pages/control.py) -- dmc.NumberInput,
    NO dcc.Input(type="number").

    CORRECCIÓN (11-ago-2026): dcc.Input(type="number") usa el spinner nativo
    del navegador -- reportado en producción que el valor desaparece del
    recuadro al usar las flechas +/-. Es un problema conocido de ese tipo de
    input en Dash cuando el valor viaja de ida y vuelta por un callback
    Python sin `debounce`: el DOM y el estado controlado de React pueden
    desincronizarse a media pulsación. dmc.NumberInput evita esto por
    diseño -- ya es dependencia de la app (calendarios de período), no es
    una librería nueva.
    """
    return html.Div(
        className="filter-field",
        style={"maxWidth": "220px"},
        children=[
            html.Label(label),
            dmc.NumberInput(id=id_, value=value, min=min_value, step=step, clampBehavior="strict"),
        ],
    )


def excel_download_button(grid_id: str) -> html.Div:
    """
    Botón "Descargar Excel" para un dash_ag_grid.AgGrid -- exporta
    exactamente lo que el usuario tiene en pantalla (rowData actual del
    grid, ya filtrado/ordenado por los selectores de la página), no una
    consulta nueva a PostgreSQL. Ver register_excel_download_callback().
    """
    return html.Div(
        className="excel-download-row",
        children=[
            html.Button(
                "⬇ Descargar Excel", id=f"{grid_id}-download-btn", n_clicks=0, className="btn-secondary",
            ),
            dcc.Download(id=f"{grid_id}-download"),
        ],
    )


def register_excel_download_callback(grid_id: str, filename: str) -> None:
    """
    Registrar UNA VEZ por grid -- toma el rowData actual del AgGrid
    (State, no Input: solo se dispara al hacer clic) y lo manda como .xlsx
    vía dcc.send_data_frame. filename debe terminar en .xlsx.
    """

    @callback(
        Output(f"{grid_id}-download", "data"),
        Input(f"{grid_id}-download-btn", "n_clicks"),
        State(grid_id, "rowData"),
        prevent_initial_call=True,
    )
    def _descargar(n_clicks, row_data):
        if not row_data:
            return no_update
        df = pd.DataFrame(row_data)
        return dcc.send_data_frame(df.to_excel, filename, index=False, engine="openpyxl")


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
        children=[
            html.Div(
                className="page-header-title-row",
                children=[
                    html.Span(className="page-header-tab"),
                    html.H1(title),
                ],
            ),
            html.P(subtitle),
        ],
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
