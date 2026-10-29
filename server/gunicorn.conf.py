"""Gunicorn configuration. See README "Server workers and threads"."""

import sys

from gunicorn_settings import connection_warning, read_worker_settings

try:
    workers, threads = read_worker_settings()
except ValueError as e:
    sys.exit(f"Invalid gunicorn setting: {e}")

_warning = connection_warning(workers)
if _warning:
    print(f"WARNING: {_warning}", file=sys.stderr)

bind = "0.0.0.0:5000"
# gthread workers suit Flask-SocketIO in threading mode. Sync workers can be
# killed by Gunicorn while handling long-lived websocket requests.
worker_class = "gthread"
# High timeout for long operations like large database restores.
timeout = 1800
