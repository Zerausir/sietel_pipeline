"""dashboard/pages/sma_voz.py — Módulo SMA: Calidad de Voz (PAUSADA).

DELIBERADAMENTE sin consultas a samm_db (26-ago-2026): la primera versión
de esta página asumía nombres de columna de grafana_voice_geo_view
tomados solo del panel de campos de Power BI -- Iván señaló que ese
supuesto no era confiable para Datos móviles, y no hay razón para creer
que sí lo sea aquí. A diferencia de Calidad de Datos móviles (ver
sma_datos.py / services/queries_sma.py), no se compartieron las medidas
DAX reales de Voz (Total Llamadas, Llamadas Caídas/Bloqueadas/
Establecidas/Fallidas, % No establecidas, % Caídas,
AqmSessionEndAqmCallQuality) -- sin esas medidas, cualquier consulta
aquí sería otra vez un supuesto, no un hecho verificado.

Reactivar: compartir las capturas de "Herramientas de medición" de esas
medidas (mismo formato que se usó para Calidad de Datos), y esta página
se reescribe con la misma lógica exacta, sin adivinar.
"""
from __future__ import annotations

from dash import html, register_page

from components.ui import page_header

register_page(__name__, path="/sma/voz", name="Calidad de Voz", order=11)


def layout():
    return html.Div(
        children=[
            page_header(
                "Calidad de Voz",
                "Pendiente de habilitar.",
            ),
            html.Div(
                className="pending-panel",
                children=[
                    html.H3("Módulo pendiente de datos verificados"),
                    html.P(
                        "Esta página está pausada a propósito: no se cuenta todavía con las medidas DAX "
                        "reales de grafana_voice_geo_view (Total Llamadas, Caídas, Bloqueadas, Establecidas, "
                        "Fallidas, % No establecidas, % Caídas, calidad de llamada). Calidad de Datos móviles "
                        "sí quedó reescrita con la lógica exacta de sus medidas DAX."
                    ),
                    html.P(
                        "Compartir el mismo tipo de captura de \"Herramientas de medición\" que se usó para "
                        "Datos habilita esta página sin necesidad de suponer nombres de columna."
                    ),
                ],
            ),
        ]
    )
