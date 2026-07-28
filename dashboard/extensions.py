"""
Instancias compartidas de extensiones Flask, creadas aquí (sin server aún
asociado) para poder importarlas tanto desde app.py como desde
services/queries.py sin import circular. app.py las asocia al server real
vía cache.init_app(server, ...).
"""
from __future__ import annotations

from flask_caching import Cache

cache = Cache()
