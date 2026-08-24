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
# Nota para Iván: esto multiplica el techo de conexiones simultáneas a
# PostgreSQL (cada proceso worker tiene su propio pool de SQLAlchemy --
# pool_size=5 + max_overflow=10 para mart, 3+5 para auth, ver
# services/database.py -- con 4 procesos, hasta ~92 conexiones en el peor
# caso si los 4 workers saturan a la vez). Vale confirmar que
# max_connections de PostgreSQL en VM1 lo tolera antes de desplegar esto en
# producción -- no lo pude verificar desde aquí. Si hace falta, ajustar
# --workers/--threads hacia abajo, o pool_size/max_overflow en
# services/database.py hacia abajo, es más seguro que dejarlo sin revisar.
CMD ["gunicorn", "app:server", "--bind", "0.0.0.0:8050", \
     "--workers", "4", "--worker-class", "gthread", "--threads", "4", \
     "--timeout", "120"]