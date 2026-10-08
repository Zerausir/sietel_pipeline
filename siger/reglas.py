"""
Reglas de datos de SIGER_V3 (§3 de la instrucción) como funciones puras,
sin base de datos -- testeadas en tests/test_siger_reglas.py.

Todas recortan SOLO espacios, igual que LTRIM/RTRIM de SQL Server (no
tabuladores ni saltos de línea, que str.strip() sin argumentos sí quitaría).
"""
import math
import re
import unicodedata
from difflib import SequenceMatcher

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


# ── Conciliación SIGER ↔ OBTEL (08-oct-2026) ─────────────────────────────────

# Estado administrativo 'opera' de SIETEL -> clase. MISMO mapeo que
# mart.vw_prestadores_sin_reportar (sql/02_ddl_mart.sql, clasificacion_
# incumplimiento): si cambia allí, cambiarlo aquí.
OPERA_ACTIVO = {"Nuevo", "Opera Normalmente", "SI"}
OPERA_NO_OPERATIVO = {"Cancelación", "NO", "Opera Irregularmente"}


def clasificar_opera(opera) -> str:
    """'activo', 'no_operativo' o 'zona_gris' (cualquier otro valor, incluido NULL)."""
    if opera in OPERA_ACTIVO:
        return "activo"
    if opera in OPERA_NO_OPERATIVO:
        return "no_operativo"
    return "zona_gris"


# Formas societarias y palabras vacías que no distinguen a un prestador.
# Se comparan DESPUÉS de juntar letras sueltas ("S. A." -> "SA").
_PALABRAS_IGNORADAS = {
    "SA", "SAS", "CA", "CIA", "COMPANIA", "LTDA", "LIMITADA", "EP", "CLTDA", "BIC",
    "DE", "DEL", "LA", "LAS", "EL", "LOS", "Y",
}


def normalizar_nombre(nombre) -> str:
    """
    Nombre comparable: sin tildes ni Ñ (NFKD), en mayúsculas, sin puntuación,
    con las letras sueltas consecutivas juntadas ("S. A." -> "SA",
    "C. LTDA." -> "C LTDA" -> se ignora) y sin formas societarias ni
    palabras vacías. '' si no queda nada.
    """
    if not nombre:
        return ""
    texto = unicodedata.normalize("NFKD", str(nombre))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch)).upper()
    texto = re.sub(r"['’`´]", "", texto)  # BIONET'S -> BIONETS, no "BIONET S"
    tokens = re.sub(r"[^A-Z0-9]+", " ", texto).split()
    juntados, letras = [], ""
    for t in tokens:
        if len(t) == 1 and t.isalpha():
            letras += t
            continue
        if letras:
            juntados.append(letras)
            letras = ""
        juntados.append(t)
    if letras:
        juntados.append(letras)
    return " ".join(t for t in juntados if t not in _PALABRAS_IGNORADAS)


# Similitud asignada cuando las palabras de un nombre están TODAS en el otro
# ("TELEACCESS" / "TELEACCESS JR", "ECUNIVI" / "ECUNIVI UNIVISA", persona sin
# su segundo nombre): coincide, pero distinguible de un nombre idéntico.
SIMILITUD_CONTENIDO = 0.95


def _similitud_simple(a: str, b: str) -> float:
    ta, tb = a.split(), b.split()
    if not ta or not tb:
        return 0.0
    orden = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    jaccard = len(set(ta) & set(tb)) / len(set(ta) | set(tb))
    contenido = SIMILITUD_CONTENIDO if set(ta) <= set(tb) or set(tb) <= set(ta) else 0.0
    return max(orden, jaccard, contenido)


def similitud_nombre(nombres_a, nombres_b, separador: str = " | ") -> float:
    """
    Similitud 0..1 entre dos nombres (o listas de nombres unidas por
    `separador`, como las agrega el cruce): el máximo entre cada par, sobre
    nombres normalizados. Por par, el mayor entre la razón de SequenceMatcher
    con las palabras ordenadas (tolera "PEREZ JUAN" vs "JUAN PEREZ"), el
    índice de Jaccard de palabras y SIMILITUD_CONTENIDO si uno contiene al otro.
    """
    la = [normalizar_nombre(x) for x in str(nombres_a or "").split(separador)]
    lb = [normalizar_nombre(x) for x in str(nombres_b or "").split(separador)]
    return round(max((_similitud_simple(a, b) for a in la for b in lb), default=0.0), 3)


# ── Reglas de la conciliación (fijadas con el perfilamiento del 08-oct-2026) ──

# Umbrales de similitud_nombre: >= COINCIDE -> COINCIDE (iguales, errores de
# tipeo, uno contiene al otro); >= PARECIDO -> PARECIDO (revisar: variantes
# J/X, otro segundo apellido); menor -> DIFIERE.
UMBRAL_NOMBRE_COINCIDE = 0.90
UMBRAL_NOMBRE_PARECIDO = 0.50


def nivel_nombre(similitud) -> str | None:
    if similitud is None:
        return None
    if similitud >= UMBRAL_NOMBRE_COINCIDE:
        return "COINCIDE"
    return "PARECIDO" if similitud >= UMBRAL_NOMBRE_PARECIDO else "DIFIERE"


# Estado de operación en SIETEL para la conciliación. DISTINTO de
# clasificar_opera (incumplimiento de reporte, página Control): aquí
# "Opera Irregularmente" OPERA (decisión del usuario, 08-oct-2026) y
# cualquier otro valor ("Otro Estado", NULL) es indeterminado.
OPERA_OPERANDO = {"Nuevo", "Opera Normalmente", "SI", "Opera Irregularmente"}
OPERA_SIN_OPERAR = {"Cancelación", "NO"}


def estado_operacion_sietel(opera) -> str:
    """'OPERANDO', 'NO_OPERA' o 'INDETERMINADO' de un valor de opera."""
    if opera in OPERA_OPERANDO:
        return "OPERANDO"
    return "NO_OPERA" if opera in OPERA_SIN_OPERAR else "INDETERMINADO"


def estado_operacion_prestador(operas) -> str:
    """Estado de un RUC con varios PEVA: OPERANDO si alguno opera; si no,
    NO_OPERA si alguno no opera; si no, INDETERMINADO."""
    estados = {estado_operacion_sietel(o) for o in operas} or {"INDETERMINADO"}
    for e in ("OPERANDO", "NO_OPERA"):
        if e in estados:
            return e
    return "INDETERMINADO"


# En SIGER se conserva el THESTADO real del título (decisión del usuario):
# solo VIGENTE cuenta como habilitado. PRORROGADO POR RENOVACION, VENCIDO,
# PROCESO EXTINCION... se muestran tal cual y comparan como no vigentes.
ESTADO_SIGER_HABILITADO = "VIGENTE"


def coincide_estado(estado_sietel: str, estado_siger: str | None) -> bool | None:
    """SIETEL OPERANDO <-> SIGER VIGENTE. None si SIETEL es INDETERMINADO o
    falta un lado."""
    if estado_siger is None or estado_sietel not in ("OPERANDO", "NO_OPERA"):
        return None
    return (estado_sietel == "OPERANDO") == (estado_siger == ESTADO_SIGER_HABILITADO)


def categoria_conciliacion(en_sietel: bool, en_siger: bool, nivel: str | None,
                           estado_coincide: bool | None) -> str:
    """Una categoría por RUC, de la más grave a la más leve."""
    if not en_siger:
        return "SOLO_SIETEL"
    if not en_sietel:
        return "SOLO_SIGER"
    if nivel == "DIFIERE" and estado_coincide is False:
        return "DIFIERE_NOMBRE_Y_ESTADO"
    if nivel == "DIFIERE":
        return "DIFIERE_NOMBRE"
    if estado_coincide is False:
        return "DIFIERE_ESTADO"
    if nivel == "PARECIDO":
        return "REVISAR_NOMBRE"
    if estado_coincide is None:
        return "ESTADO_INDETERMINADO"
    return "COINCIDE"
