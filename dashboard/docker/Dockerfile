# Dashboard SIETEL -- servido con gunicorn, no con `python app.py`
# (el servidor de desarrollo de Flask/Dash no está pensado para producción:
# sin manejo real de concurrencia, y con el modo debug activo sería un
# riesgo de seguridad serio junto a Flask-Login -- ver dashboard/config.py).
FROM python:3.14-slim

WORKDIR /app

# Sin dependencias de compilación adicionales: psycopg[binary] y bcrypt ya
# traen ruedas precompiladas para esta imagen base.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El puerto real se controla por APP_PORT en el .env -- 8050 es el default
# de dashboard/config.py, y el que expone este Dockerfile por convención.
EXPOSE 8050

# CAMBIO (22-ago-2026, diagnóstico de latencia): --workers 2 con la clase
# "sync" por defecto significaba que CADA worker atendía UNA sola petición
# HTTP a la vez, bloqueado mientras esperaba la respuesta de PostgreSQL --
# con varios callbacks disparándose por cada interacción del usuario (hasta
# 9 consultas secuenciales en Evolución, 5 callbacks independientes en
# Control), esto era el cuello de botella real: la VM tiene recursos de
# sobra, pero solo 2 peticiones podían procesarse en paralelo sin importar
# cuánta CPU/RAM hubiera disponible.
#
# gthread (worker de hilos) es la corrección establecida de gunicorn para
# exactamente este patrón -- trabajo bloqueante de I/O (consultas SQL), sin
# necesitar gevent/eventlet (que exigen "monkey-patching" del proceso, con
# riesgo real de incompatibilidad silenciosa con psycopg). Con
# "--workers 4 --threads 4" hay hasta 16 peticiones atendidas en paralelo
# (4 procesos × 4 hilos cada uno) en vez de 2.
#
# CONFIRMADO en VM1 (22-ago-2026): max_connections=100, 24 en uso por el
# resto de sistemas (Airflow, samm_pipeline, etc.) ANTES de que este
# dashboard abra una sola conexión. pool_size/max_overflow se redujeron en
# services/database.py (de 5+10/3+5 a 3+5/2+2 por proceso) para que el
# techo teórico de este dashboard quede en ~48 conexiones en el peor caso
# (4 workers × 12 c/u) -- deja margen real sin tocar max_connections de
# PostgreSQL, que afectaría a todos lo que corre en esa instancia y exige
# reiniciar el servidor. Ver services/database.py para el detalle completo.
CMD ["gunicorn", "app:server", "--bind", "0.0.0.0:8050", \
     "--workers", "4", "--worker-class", "gthread", "--threads", "4", \
     "--timeout", "120"]