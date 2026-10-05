"""
Reglas de datos de SIGER_V3 (§3 de la instrucción) como funciones puras,
sin base de datos -- testeadas en tests/test_siger_reglas.py.

Todas recortan SOLO espacios, igual que LTRIM/RTRIM de SQL Server (no
tabuladores ni saltos de línea, que str.strip() sin argumentos sí quitaría).
"""
import math
import re

_TRECE_DIGITOS = re.compile(r"\d{13}")
_DIEZ_DIGITOS = re.compile(r"\d{10}")


def recortar(valor):
    """LTRIM(RTRIM(valor)) para texto; cualquier otro valor pasa tal cual."""
    return valor.strip(" ") if isinstance(valor, str) else valor


def contrato_key(tomo, foja) -> str:
    """
    Llave de contrato de un título: LTRIM(RTRIM(THTOMO)) + '-' +
    LTRIM(RTRIM(THFOJA)). Tomo y foja son SIEMPRE texto (ceros a la
    izquierda '010', sufijos '13708A', '08f02v'); nunca se convierten a
    número. Sin tomo ni foja -> '-' (títulos que no se enlazan con
    facturación). SUPUESTO: un NULL se trata igual que la cadena vacía (en
    SQL Server la concatenación con NULL daría NULL; aquí se prefiere '-').
    """
    return f"{recortar(tomo) or ''}-{recortar(foja) or ''}"


def resolver_ruc(ruc, ci_ruc) -> tuple[str | None, str]:
    """
    RUC resuelto del concesionario y su origen (§3.6):
      ruc de 13 dígitos                  -> (ruc, 'ruc')
      si no, ci_ruc de 13 dígitos        -> (ci_ruc, 'ci_ruc_13')
      si no, ci_ruc de 10 dígitos        -> (ci_ruc + '001', 'cedula_001')
                                             validada: 97,4 % de los casos con
                                             ambos datos cumplen ruc = cédula + '001'
      si no                              -> (None, 'sin_ruc')
    ruc es char(13) en SIGER: viene con relleno, por eso se recorta antes.
    """
    r = recortar(ruc) or ""
    c = recortar(ci_ruc) or ""
    if _TRECE_DIGITOS.fullmatch(r):
        return r, "ruc"
    if _TRECE_DIGITOS.fullmatch(c):
        return c, "ci_ruc_13"
    if _DIEZ_DIGITOS.fullmatch(c):
        return c + "001", "cedula_001"
    return None, "sin_ruc"


def contrato_facturacion(contrato) -> str | None:
    """Llave de contrato de una fila de facturación: CONTRATO recortado, NULL si vacío."""
    return recortar(contrato) or None


def tipo_enlace(contrato, claves_titulos: set[str]) -> str:
    """
    Clasifica cómo se enlaza una fila de facturación con los títulos:
      SIN_CONTRATO -- CONTRATO NULL o vacío (ej. TCS, Televisión Codificada Satelital)
      TOMO_FOJA    -- coincide con el contrato_key de algún título
      TRAMITE      -- formato de documento ('ARCOTEL-...'): requeriría
                      THNUMERO_TRAMITE, columna denegada -> no se enlaza
      SIN_MATCH    -- cualquier otro caso
    claves_titulos va en MAYÚSCULAS: la comparación ignora mayúsculas, igual
    que la intercalación de SIGER (Modern_Spanish_CI_AS), con la que se
    midieron los 2.729 contratos enlazados.
    """
    k = contrato_facturacion(contrato)
    if not k:
        return "SIN_CONTRATO"
    if k.upper() in claves_titulos:
        return "TOMO_FOJA"
    if k.upper().startswith("ARCOTEL-"):
        return "TRAMITE"
    return "SIN_MATCH"


def thsecuencial_a_bigint(valor) -> int:
    """THSECUENCIAL es float en SIGER: se convierte a entero y falla si no lo es."""
    if valor is None or isinstance(valor, bool):
        raise ValueError(f"THSECUENCIAL inválido: {valor!r}")
    v = float(valor)
    if not math.isfinite(v) or not v.is_integer():
        raise ValueError(f"THSECUENCIAL no es entero: {valor!r} -- se aborta la carga.")
    return int(v)
