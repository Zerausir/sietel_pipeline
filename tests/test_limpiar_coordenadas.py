"""
Tests unitarios (sin base de datos) de la conversión de coordenadas de
mart/limpiar_coordenadas_nodo_isp.py.

Uso:
    python -m pytest tests/test_limpiar_coordenadas.py
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mart"))

from limpiar_coordenadas_nodo_isp import (  # noqa: E402
    convertir_dms_a_decimal,
    inferir_hemisferio_longitud_faltante,
)


@pytest.mark.parametrize(
    "texto, esperado",
    [
        # Decimales con signo explícito -- antes perdían el "-" (bug 28-sep-2026)
        ("-0.2150", -0.2150),
        ("-2.19", -2.19),
        ("-78.5", -78.5),
        ("0,5", 0.5),
        # DMS con letra de hemisferio
        ("0°12'S", -0.2),
        ("S 0 12", -0.2),
        ("78°30'O", -78.5),
        ("78°30'W", -78.5),
        ("0°30' N", 0.5),
        # Palabras completas: NORTE/ESTE no deben volverse negativas
        ("0.5 NORTE", 0.5),
        ("0.5 SUR", -0.5),
        ("78.5 OESTE", -78.5),
    ],
)
def test_convertir_dms_a_decimal(texto, esperado):
    valor, motivo = convertir_dms_a_decimal(texto)
    assert motivo is None
    assert valor == pytest.approx(esperado)


@pytest.mark.parametrize("texto", [None, "", "0", "-", "nan", "abc"])
def test_convertir_dms_invalidos(texto):
    valor, motivo = convertir_dms_a_decimal(texto)
    assert valor is None
    assert motivo is not None


def test_minutos_fuera_de_rango():
    valor, motivo = convertir_dms_a_decimal("0°75'S")
    assert valor is None
    assert motivo == "minutos_o_segundos_fuera_de_rango_0_60"


def test_infiere_signo_longitud_sin_letra():
    assert inferir_hemisferio_longitud_faltante("78.5", 78.5) == (-78.5, True)


def test_no_infiere_si_hay_letra_explicita():
    assert inferir_hemisferio_longitud_faltante("78.5 E", 78.5) == (78.5, False)


def test_no_toca_longitud_ya_negativa():
    lon, _ = convertir_dms_a_decimal("-78.5")
    assert inferir_hemisferio_longitud_faltante("-78.5", lon) == (-78.5, False)
