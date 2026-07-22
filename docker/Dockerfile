FROM apache/airflow:slim-3.2.0-python3.14
# Imagen alineada deliberadamente con la de samm_pipeline
# (Dockerfile.airflow: FROM apache/airflow:slim-3.2.0-python3.14) para usar
# la misma combinacion Airflow+Python+pyodbc que ya corre en produccion en
# VM2 con samm_pipeline, en vez de una combinacion (3.2.2/python3.12) sin
# historial de uso real en esta infraestructura. Instancias de Airflow
# siguen siendo independientes (docker-compose y metadata-db propios) --
# esto solo unifica la imagen base para reducir superficie de mantenimiento.

USER root

# Driver ODBC 18 de Microsoft (necesario para pyodbc). Se usa pyodbc en vez
# de pymssql porque el servidor SIETEL exige una negociación TLS que
# FreeTDS (usado por pymssql) rechaza durante el handshake -- confirmado
# con TDSDUMP, error "login packet rejected" -- mientras que el driver
# ODBC oficial de Microsoft (el mismo que usa SSMS) sí negocia
# correctamente. Ver docs/decisiones para el detalle del diagnóstico.
#
# NOTA DE VERIFICACION AL HACER BUILD: el repo de Microsoft se agrega para
# Debian 12 "bookworm" (linea de abajo). Si apache/airflow:slim-3.2.0-python3.14
# no es bookworm, el "apt-get update" posterior fallara -- esa falla es la
# señal de que hay que cambiar "debian/12" y "bookworm" por el codename
# correcto de esta imagen base.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        gnupg2 \
        unixodbc \
        unixodbc-dev \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,armhf,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# El SQL Server de SIETEL no soporta renegociacion TLS segura (RFC 5746),
# que OpenSSL 3.x exige por defecto. Sin este ajuste, la conexion falla con:
#   "SSL routines::unsafe legacy renegotiation disabled"
# Se habilita UnsafeLegacyRenegotiation solo para este contenedor, via un
# openssl.cnf propio que extiende (no reemplaza) la configuracion por
# defecto del sistema. Este contenedor es exclusivo de sietel_pipeline
# (instancia de Airflow independiente de samm_pipeline) -- este ajuste NO
# debe aplicarse nunca a un contenedor compartido con otro pipeline.
RUN { \
        echo "openssl_conf = openssl_init"; \
        echo ""; \
        echo "[openssl_init]"; \
        echo "ssl_conf = ssl_sect"; \
        echo ""; \
        echo "[ssl_sect]"; \
        echo "system_default = system_default_sect"; \
        echo ""; \
        echo "[system_default_sect]"; \
        echo "Options = UnsafeLegacyRenegotiation"; \
    } > /etc/ssl/openssl-legacy-renegotiation.cnf
ENV OPENSSL_CONF=/etc/ssl/openssl-legacy-renegotiation.cnf

USER airflow

RUN pip install --no-cache-dir \
    "asyncpg==0.31.0" \
    "pyodbc==5.3.0" \
    "psycopg2-binary==2.9.12"

ENTRYPOINT ["/usr/bin/dumb-init", "--", "/entrypoint"]