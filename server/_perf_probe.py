"""Dev-only instrumentation for the board performance measurement harness
(see docs/PERFORMANCE_board_updates.md and perf-tests/README.md). Not
imported by app.py by default — enabled only via PERF_PROBE=1.

Logs, per HTTP request: method, path, status, wall-clock ms, and SQL
statement count (via SQLAlchemy's before_cursor_execute event).
"""
import os
import time
import logging

logger = logging.getLogger("perf_probe")


def install(app, engine):
    if os.environ.get("PERF_PROBE") != "1":
        return

    from sqlalchemy import event
    from flask import g, has_request_context

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        # Per-request counter via flask.g, not a shared closure variable —
        # the server runs multiple gunicorn worker threads (see
        # server/startup.sh), so a single shared counter would race across
        # concurrent requests. Background scheduler threads (card_scheduler,
        # backup_scheduler, etc.) also issue queries on this same engine
        # outside any request context; has_request_context() guards against
        # those so the probe only counts request-bound queries.
        if has_request_context():
            g._perf_probe_query_count = getattr(g, "_perf_probe_query_count", 0) + 1

    @app.before_request
    def _perf_probe_start():
        g._perf_probe_start = time.perf_counter()
        g._perf_probe_query_count = 0

    @app.after_request
    def _perf_probe_end(response):
        from flask import request
        start = getattr(g, "_perf_probe_start", None)
        if start is not None:
            elapsed_ms = (time.perf_counter() - start) * 1000
            query_count = getattr(g, "_perf_probe_query_count", 0)
            content_length = response.calculate_content_length()
            logger.warning(
                "PERF_PROBE %s %s status=%s ms=%.1f queries=%d bytes=%s",
                request.method,
                request.path,
                response.status_code,
                elapsed_ms,
                query_count,
                content_length,
            )
        return response

    logger.warning("PERF_PROBE instrumentation enabled")
