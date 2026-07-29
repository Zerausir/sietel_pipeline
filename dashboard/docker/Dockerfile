# Dashboard SIETEL -- servido con gunicorn, no con `python app.py`
# (el servidor de desarrollo de Flask/Dash no está pensado para producción:
# sin manejo real de concurrencia, y con el modo debug activo sería un
# riesgo de seguridad serio junto a Flask-Login -- ver dashboard/config.py).
FROM python:3.12-slim

WORKDIR /app

# Sin dependencias de compilación adicionales: psycopg[binary] y bcrypt ya
# traen ruedas precompiladas para esta imagen base.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El puerto real se controla por APP_PORT en el .env -- 8050 es el default
# de dashboard/config.py, y el que expone este Dockerfile por convención.
EXPOSE 8050

# --workers 2: suficiente para un equipo interno pequeño (Dirección de
# Mercados), no una app de tráfico público. Ajustar aquí si el uso crece.
# server (no app) porque app.py expone `server = app.server` -- el Flask
# WSGI subyacente que gunicorn necesita, no el objeto Dash en sí.
CMD ["gunicorn", "app:server", "--bind", "0.0.0.0:8050", "--workers", "2", "--timeout", "120"]
