"""
Autenticación del dashboard SIETEL vía Flask-Login + bcrypt.

Decisiones de diseño (ver discusión de validación profesional):
- La tabla de usuarios vive en auth.usuarios_dashboard (VM1), NO en una
  base local -- de lo contrario reintroduce el mismo problema que motivó
  mover Capa 2/3 fuera de la laptop.
- Conexión de auth separada de la conexión de lectura de mart (rol
  dashboard_auth vs dashboard_lector) -- ver sql/03_ddl_auth.sql.
- Sin autorregistro. Altas/bajas/reset de contraseña solo vía
  dashboard/scripts/gestionar_usuarios.py, corrido por un administrador.
- El guard de sesión se aplica en un @server.before_request de Flask, NO
  en un callback de Dash -- así ninguna página (ni su JS) se sirve sin
  sesión válida, en vez de dejar pasar el layout y bloquear solo los datos.
- /login es una ruta Flask plana con HTML simple, no una página de Dash
  registrada con use_pages -- evita cargar el bundle completo de Dash
  antes de autenticar.
"""
from __future__ import annotations

import logging
from datetime import datetime

import bcrypt
from flask import Blueprint, redirect, render_template, request, session, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from sqlalchemy import text

from services.database import get_auth_engine

logger = logging.getLogger(__name__)

login_manager = LoginManager()
login_manager.login_view = "auth.login"

auth_bp = Blueprint("auth", __name__, template_folder="templates")


class Usuario(UserMixin):
    def __init__(self, id_: int, username: str, nombre_completo: str, activo: bool):
        self.id = str(id_)
        self.username = username
        self.nombre_completo = nombre_completo
        self.activo = activo

    @property
    def is_active(self) -> bool:  # sobreescribe UserMixin: respeta la columna "activo"
        return self.activo


def _obtener_usuario_por_id(user_id: str) -> Usuario | None:
    with get_auth_engine().connect() as conn:
        fila = conn.execute(
            text(
                """
                SELECT id, username, nombre_completo, activo
                FROM auth.usuarios_dashboard
                WHERE id = :id
                """
            ),
            {"id": int(user_id)},
        ).mappings().one_or_none()

    if fila is None:
        return None
    return Usuario(fila["id"], fila["username"], fila["nombre_completo"], fila["activo"])


def _obtener_usuario_por_username(username: str):
    with get_auth_engine().connect() as conn:
        return conn.execute(
            text(
                """
                SELECT id, username, password_hash, nombre_completo, activo
                FROM auth.usuarios_dashboard
                WHERE username = :username
                """
            ),
            {"username": username},
        ).mappings().one_or_none()


def _registrar_acceso(user_id: int) -> None:
    with get_auth_engine().begin() as conn:
        conn.execute(
            text(
                """
                UPDATE auth.usuarios_dashboard
                SET ultimo_acceso = :ahora
                WHERE id = :id
                """
            ),
            {"ahora": datetime.now(), "id": user_id},
        )


@login_manager.user_loader
def load_user(user_id: str):
    return _obtener_usuario_por_id(user_id)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect("/")

    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").encode("utf-8")

        fila = _obtener_usuario_por_username(username)

        # Deliberadamente el mismo mensaje de error tanto si el usuario no
        # existe como si la contraseña es incorrecta o el usuario está
        # inactivo -- no revelar cuál de las tres cosas falló.
        if (
            fila is not None
            and fila["activo"]
            and bcrypt.checkpw(password, fila["password_hash"].encode("utf-8"))
        ):
            usuario = Usuario(fila["id"], fila["username"], fila["nombre_completo"], fila["activo"])
            login_user(usuario)
            _registrar_acceso(fila["id"])
            siguiente = request.args.get("next") or "/"
            return redirect(siguiente)

        logger.info("Intento de login fallido para username=%r", username)
        error = "Usuario o contraseña incorrectos."

    return render_template("login.html", error=error)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("auth.login"))


def init_auth(server) -> None:
    """Llamar una sola vez desde app.py, después de crear `server = app.server`."""
    login_manager.init_app(server)
    server.register_blueprint(auth_bp)

    @server.before_request
    def _requerir_sesion():
        rutas_publicas = {"/login", "/logout"}
        # Rutas internas de Dash: assets estáticos y los endpoints del
        # dash-renderer (layout, dependencias, actualización de componentes,
        # suites de componentes). Sin esto, el before_request bloquearía las
        # llamadas internas de Dash aun con sesión válida, porque empiezan
        # con "/_dash-" y no calzan con las rutas públicas.
        es_interno_dash = request.path.startswith("/assets") or request.path.startswith("/_dash-")
        if request.path in rutas_publicas or es_interno_dash:
            return None
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))
        return None
