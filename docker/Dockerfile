FROM apache/airflow:slim-3.3.0-python3.14
# Subido de 3.2.0 a 3.3.0 (23-jul-2026). Motivo: la UI se colgaba con
# sqlalchemy.exc.TimeoutError: QueuePool limit reached durante cargas
# historicas largas con el Grid abierto -- el pool ampliado (20+30) tambien
# se agoto, indicando una fuga de conexiones (no falta de tamano de pool),
# consistente con bugs de sesion/auth documentados en el changelog oficial
# de Airflow:
#   - 3.2.1: "Fix FAB auth_manager load_user causing PendingRollbackError"
#   - 3.2.1: "Fix OAuth session race condition causing false 401 errors during login"
#   - Discusion oficial de Airflow: bug identico (PendingRollbackError
#     envenenando el pool) confirmado arreglado en 3.1.5
# Ivan confirmo que en su entorno local (3.2.2) nunca vio este problema,
# consistente con que el fix ya estaba presente ahi. No hay una entrada de
# changelog que mencione el bug exacto (RevokedToken/QueuePool) por su
# nombre, asi que esto no esta garantizado al 100% -- monitorear tras el
# cambio antes de darlo por resuelto.
#
# Imagen alineada deliberadamente con la de samm_pipeline (mismo cambio
# aplicado ahi el mismo dia) para mantener ambas instancias en la misma
# version, evitando el problema de mantenimiento que motivo la alineacion
# original (3.2.0/python3.14 para ambas).

USER root

# Driver ODBC 18 de Microsoft (necesario para pyodbc). Se usa pyodbc en vez
# de pymssql porque el servidor SIETEL exige una negociación TLS que
# FreeTDS (usado por pymssql) rechaza durante el handshake -- confirmado
# con TDSDUMP, error "login packet rejected" -- mientras que el driver
# ODBC oficial de Microsoft (el mismo que usa SSMS) sí negocia
# correctamente. Ver docs/decisiones para el detalle del diagnóstico.
#
# NOTA DE VERIFICACION AL HACER BUILD: el repo de Microsoft se agrega para
# Debian 12 "bookworm" (linea de abajo). Si apache/airflow:slim-3.3.0-python3.14
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

# Dependencias de mart/ (dags/sietel_mart_pipeline.py) -- deliberadamente
# psycopg v3 (no psycopg2 de arriba) porque mart/*.py usa SQLAlchemy con el
# driver "postgresql+psycopg", igual que corre en VM2 para estos mismos
# scripts. Sin esto el DAG falla con ModuleNotFoundError apenas intenta
# importar detectar_conflictos_peva.py / construir_capa2.py / aplicar_capa3.py
# (confirmado 29-jul-2026: el volumen mart/ estaba montado pero las
# librerías nunca se instalaron en esta imagen).
RUN pip install --no-cache-dir \
    "SQLAlchemy==2.0.51" \
    "psycopg[binary]==3.3.4" \
    "python-dotenv==1.2.2"

# Geoprocesamiento de nodos ISP (06-ago-2026) -- mart/cargar_parroquias.py y
# mart/detectar_discrepancias_geografia_nodo.py. A diferencia de todo lo demás
# en mart/, esta es la primera dependencia de este Dockerfile que NO viene
# como wheel puro-Python -- geopandas trae GDAL/GEOS/PROJ por debajo. Los
# wheels manylinux de pip (via pyogrio, el motor de lectura por defecto desde
# geopandas>=0.14) incluyen esos binarios empaquetados -- no debería requerir
# paquetes de sistema (gdal-bin/libgdal-dev) adicionales en esta imagen base
# Debian. Si el build falla aquí, esa es la primera señal a investigar --
# no asumir automáticamente que hace falta apt-get sin confirmarlo con el
# log real del error.
RUN pip install --no-cache-dir \
    "geopandas==1.1.4"

ENTRYPOINT ["/usr/bin/dumb-init", "--", "/entrypoint"]