"""
Hash MD5 por fila para certificar la réplica de SIGER_V3.

Mismo criterio que cargar_hechos_anio.calcular_hash_fila (valores unidos
por '|', NULL como 'NULL'), con una representación de texto explícita por
tipo para que el MISMO valor dé el MISMO hash venga de pyodbc (origen) o de
psycopg2 (destino):
  None      -> 'NULL'
  bool      -> '1' / '0'     (bit -> BOOLEAN; antes que int: bool es int)
  int       -> str           (int, y THSECUENCIAL ya convertido a bigint)
  float     -> repr          (float(53) -> DOUBLE PRECISION, ida y vuelta exacta)
  datetime  -> isoformat     (smalldatetime/datetime -> TIMESTAMP(6))
  str       -> tal cual      (sin recortar: la tabla cruda es copia fiel)
Solo se hashean las columnas de ORIGEN, nunca las derivadas (contrato_key,
ruc_resuelto, tipo_enlace...): el hash certifica la copia, no las reglas.
"""
import hashlib
from datetime import date, datetime
from decimal import Decimal


def valor_para_hash(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, str):
        return v
    raise TypeError(f"Tipo no soportado para el hash: {type(v).__name__} ({v!r})")


def digest_fila(valores) -> bytes:
    """MD5 (16 bytes) de una fila: secuencia de valores en el orden de las columnas de origen."""
    return hashlib.md5("|".join(valor_para_hash(v) for v in valores).encode("utf-8")).digest()
