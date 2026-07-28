"""
gestionar_usuarios.py — Administración de auth.usuarios_dashboard.

Corre con credenciales administrativas propias (dueño del esquema auth o un
superusuario puntual), NUNCA con el rol de runtime `dashboard_auth` que usa
la app en producción -- ese rol solo puede leer/actualizar filas existentes,
no está pensado para altas/bajas administrativas.

No hay autorregistro en la app. Este script es la ÚNICA vía soportada para
crear, desactivar, reactivar o resetear la contraseña de un usuario.

Uso:
    python gestionar_usuarios.py crear --username jperez --nombre "Juan Pérez"
    python gestionar_usuarios.py listar
    python gestionar_usuarios.py desactivar --username jperez
    python gestionar_usuarios.py reactivar --username jperez
    python gestionar_usuarios.py resetear-password --username jperez
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

import bcrypt
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


def _conectar():
    host = os.environ.get("ADMIN_PG_HOST") or input("Host de PostgreSQL (VM1): ").strip()
    port = os.environ.get("ADMIN_PG_PORT", "5432")
    database = os.environ.get("ADMIN_PG_DATABASE") or input("Base de datos [sietel_analitico]: ").strip() or "sietel_analitico"
    user = os.environ.get("ADMIN_PG_USER") or input("Usuario administrativo: ").strip()
    password = os.environ.get("ADMIN_PG_PASSWORD") or getpass.getpass("Contraseña: ")

    url = URL.create(
        drivername="postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=int(port),
        database=database,
    )
    return create_engine(url, connect_args={"connect_timeout": 10})


def _pedir_password_nueva() -> bytes:
    while True:
        p1 = getpass.getpass("Nueva contraseña (mínimo 10 caracteres): ")
        if len(p1) < 10:
            print("Muy corta -- mínimo 10 caracteres. Intenta de nuevo.")
            continue
        p2 = getpass.getpass("Repite la contraseña: ")
        if p1 != p2:
            print("No coinciden. Intenta de nuevo.")
            continue
        return p1.encode("utf-8")


def crear(engine, username: str, nombre: str) -> int:
    with engine.connect() as conn:
        existe = conn.execute(
            text("SELECT 1 FROM auth.usuarios_dashboard WHERE username = :u"),
            {"u": username},
        ).one_or_none()
    if existe:
        print(f"Ya existe un usuario con username={username!r}.")
        return 1

    password_hash = bcrypt.hashpw(_pedir_password_nueva(), bcrypt.gensalt()).decode("utf-8")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO auth.usuarios_dashboard (username, password_hash, nombre_completo, activo)
                VALUES (:username, :password_hash, :nombre, true)
                """
            ),
            {"username": username, "password_hash": password_hash, "nombre": nombre},
        )
    print(f"Usuario {username!r} creado y activo.")
    return 0


def listar(engine) -> int:
    with engine.connect() as conn:
        filas = conn.execute(
            text(
                """
                SELECT username, nombre_completo, activo, ultimo_acceso, fecha_creacion
                FROM auth.usuarios_dashboard
                ORDER BY username
                """
            )
        ).mappings().all()

    if not filas:
        print("No hay usuarios registrados.")
        return 0

    for f in filas:
        estado = "ACTIVO" if f["activo"] else "INACTIVO"
        ultimo = f["ultimo_acceso"] or "nunca"
        print(f"  [{estado:8s}] {f['username']:20s} {f['nombre_completo']:30s} último acceso: {ultimo}")
    return 0


def _cambiar_estado(engine, username: str, activo: bool) -> int:
    with engine.begin() as conn:
        resultado = conn.execute(
            text(
                """
                UPDATE auth.usuarios_dashboard
                SET activo = :activo,
                    fecha_desactivado = CASE WHEN :activo THEN NULL ELSE now() END
                WHERE username = :username
                """
            ),
            {"activo": activo, "username": username},
        )
    if resultado.rowcount == 0:
        print(f"No existe un usuario con username={username!r}.")
        return 1
    print(f"Usuario {username!r} -> {'ACTIVO' if activo else 'INACTIVO'}.")
    return 0


def resetear_password(engine, username: str) -> int:
    with engine.connect() as conn:
        existe = conn.execute(
            text("SELECT 1 FROM auth.usuarios_dashboard WHERE username = :u"),
            {"u": username},
        ).one_or_none()
    if not existe:
        print(f"No existe un usuario con username={username!r}.")
        return 1

    password_hash = bcrypt.hashpw(_pedir_password_nueva(), bcrypt.gensalt()).decode("utf-8")
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE auth.usuarios_dashboard SET password_hash = :h WHERE username = :u"),
            {"h": password_hash, "u": username},
        )
    print(f"Contraseña de {username!r} actualizada.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Administración de usuarios del dashboard SIETEL.")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_crear = sub.add_parser("crear")
    p_crear.add_argument("--username", required=True)
    p_crear.add_argument("--nombre", required=True, help="Nombre completo, ej. \"Juan Pérez\"")

    sub.add_parser("listar")

    p_desactivar = sub.add_parser("desactivar")
    p_desactivar.add_argument("--username", required=True)

    p_reactivar = sub.add_parser("reactivar")
    p_reactivar.add_argument("--username", required=True)

    p_reset = sub.add_parser("resetear-password")
    p_reset.add_argument("--username", required=True)

    args = parser.parse_args()
    engine = _conectar()

    if args.comando == "crear":
        return crear(engine, args.username, args.nombre)
    if args.comando == "listar":
        return listar(engine)
    if args.comando == "desactivar":
        return _cambiar_estado(engine, args.username, activo=False)
    if args.comando == "reactivar":
        return _cambiar_estado(engine, args.username, activo=True)
    if args.comando == "resetear-password":
        return resetear_password(engine, args.username)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
