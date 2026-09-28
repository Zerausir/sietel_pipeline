"""
Tests unitarios (sin base de datos) de reglas puras del pipeline y del
dashboard que afectan la calidad de los datos o la seguridad:

  - mart/detectar_conflictos_peva.py: clasificar() (categorías A/B/C).
  - scripts/cargar_dimensiones.py: _cambio_relevante() (SCD2, claves con
    mayúsculas distintas entre SQL Server y Postgres -- bug 07-ago-2026).
  - dashboard/auth.py: _destino_seguro() (open redirect -- 28-sep-2026).

Uso:
    python -m pytest tests/
"""
import os
import sys

import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
for carpeta in ("mart", "scripts"):
    sys.path.insert(0, os.path.join(RAIZ, carpeta))

from cargar_dimensiones import COLUMNAS_VERSIONABLES_PERMISO, _cambio_relevante  # noqa: E402
from detectar_conflictos_peva import clasificar  # noqa: E402


def _importar_destino_seguro():
    """
    scripts/ y dashboard/ tienen cada uno su propio módulo "config" -- en un
    mismo proceso solo puede estar cargado uno con ese nombre. Se importa
    dashboard/auth.py con el "config" del dashboard y luego se restaura el
    de scripts/, para que ninguna de las dos importaciones pise a la otra.
    """
    config_scripts = sys.modules.pop("config", None)
    sys.path.insert(0, os.path.join(RAIZ, "dashboard"))
    os.environ.setdefault("SECRET_KEY", "solo-para-tests")  # dashboard/config.py la exige
    try:
        from auth import _destino_seguro as f
    finally:
        sys.path.pop(0)
        sys.modules.pop("config", None)
        if config_scripts is not None:
            sys.modules["config"] = config_scripts
    return f


_destino_seguro = _importar_destino_seguro()


def _par(nombre_a, nombre_b, opera_a, opera_b):
    return {"isp_nombre_a": nombre_a, "isp_nombre_b": nombre_b,
            "opera_a": opera_a, "opera_b": opera_b, "peva_a": "P1", "peva_b": "P2"}


# ── clasificar() ─────────────────────────────────────────────────────────────

def test_a_mismo_nombre_un_lado_legado():
    r = clasificar(_par("ACME S.A.", "acme s.a. ", "SI", "Opera Normalmente"), coexisten=True)
    assert r["categoria"] == "A_DUPLICADO_MIGRACION_CODIFICACION"
    assert r["peva_legado_descartado"] == "P1"
    assert r["estado_revision_inicial"] == "CONFIRMADO_AUTOMATICO"


def test_a_legado_en_el_lado_b():
    r = clasificar(_par("ACME", "ACME", "Opera Normalmente", "-"), coexisten=False)
    assert r["peva_legado_descartado"] == "P2"


def test_b_mismo_titular_sin_coexistencia_se_cierra_solo():
    r = clasificar(_par("ACME", "ACME", "Opera Normalmente", "Cancelación"), coexisten=False)
    assert r["categoria"] == "B_SECUENCIA_MISMO_TITULAR"
    assert r["accion_recomendada"] == "SIN_CONFLICTO_NO_COEXISTEN"
    assert r["estado_revision_inicial"] == "CONFIRMADO_AUTOMATICO"


def test_b_mismo_titular_con_coexistencia_va_a_revision():
    r = clasificar(_par("ACME", "ACME", "Opera Normalmente", "Cancelación"), coexisten=True)
    assert r["accion_recomendada"] == "REVISION_MANUAL_SIETEL"
    assert r["estado_revision_inicial"] == "PENDIENTE"
    assert r["revisado_por_inicial"] is None


def test_b_por_marca_de_cancelacion_en_el_nombre():
    r = clasificar(_par("SKYWEB", "SKYWEB cancelado 2011", "Opera Normalmente", "Opera Normalmente"),
                   coexisten=False)
    assert r["categoria"] == "B_SECUENCIA_MISMO_TITULAR"


def test_ambos_legado_no_es_a():
    r = clasificar(_par("ACME", "ACME", "SI", "NO"), coexisten=False)
    assert r["categoria"] == "B_SECUENCIA_MISMO_TITULAR"


def test_c_nombres_distintos():
    r = clasificar(_par("ACME", "OTRA EMPRESA", "SI", "Opera Normalmente"), coexisten=False)
    assert r["categoria"] == "C_NOMBRES_DISTINTOS_MISMO_RUC"
    assert r["estado_revision_inicial"] == "PENDIENTE"


# ── _cambio_relevante() ──────────────────────────────────────────────────────

def test_sin_cambio_aunque_las_claves_difieran_en_mayusculas():
    origen = {"nombreComercial": "X", "opera": "Opera Normalmente", "Resolucion": "R1", "isp_codigo": "I1"}
    vigente = {"nombrecomercial": "X", "opera": "Opera Normalmente", "resolucion": "R1", "isp_codigo": "I1"}
    assert _cambio_relevante(origen, vigente, COLUMNAS_VERSIONABLES_PERMISO) is False


def test_cambio_de_isp_versiona():
    origen = {"nombreComercial": "X", "opera": "Opera Normalmente", "Resolucion": "R1", "isp_codigo": "I2"}
    vigente = {"nombrecomercial": "X", "opera": "Opera Normalmente", "resolucion": "R1", "isp_codigo": "I1"}
    assert _cambio_relevante(origen, vigente, COLUMNAS_VERSIONABLES_PERMISO) is True


def test_cambio_en_columna_no_versionable_no_versiona():
    origen = {"nombreComercial": "X", "opera": "A", "Resolucion": "R1", "isp_codigo": "I1", "fechaPermiso": 2}
    vigente = {"nombrecomercial": "X", "opera": "A", "resolucion": "R1", "isp_codigo": "I1", "fechapermiso": 1}
    assert _cambio_relevante(origen, vigente, COLUMNAS_VERSIONABLES_PERMISO) is False


# ── _destino_seguro() ────────────────────────────────────────────────────────

@pytest.mark.parametrize("destino", ["/", "/sai/control", "/sai/evolucion?x=1"])
def test_destinos_internos_se_respetan(destino):
    assert _destino_seguro(destino) == destino


@pytest.mark.parametrize(
    "destino",
    [None, "", "https://evil.com", "//evil.com", "/\\evil.com", "evil.com", "javascript:alert(1)"],
)
def test_destinos_externos_van_al_inicio(destino):
    assert _destino_seguro(destino) == "/"
