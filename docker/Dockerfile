FROM apache/airflow:slim-3.2.2-python3.12

USER root

# Driver ODBC 18 de Microsoft (necesario para pyodbc). Se usa pyodbc en vez
# de pymssql porque el servidor SIETEL exige una negociación TLS que
# FreeTDS (usado por pymssql) rechaza durante el handshake -- confirmado
# con TDSDUMP, error "login packet rejected" -- mientras que el driver
# ODBC oficial de Microsoft (el mismo que usa SSMS) sí negocia
# correctamente. Ver docs/decisiones para el detalle del diagnóstico.
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
# que OpenSSL 3.x (incluido en Debian Bookworm) exige por defecto desde su
# migracion mayor. Sin este ajuste, la conexion falla con:
#   "SSL routines::unsafe legacy renegotiation disabled"
# Se habilita UnsafeLegacyRenegotiation solo para este contenedor, via un
# openssl.cnf propio que extiende (no reemplaza) la configuracion por
# defecto del sistema.
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