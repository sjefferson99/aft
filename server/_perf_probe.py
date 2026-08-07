"""TEMPORARY dev-only instrumentation for the Tier 1 performance baseline
(see docs/PERFORMANCE_board_updates.md). Not imported by app.py by default —
enabled only via PERF_PROBE=1 for measurement runs. Delete this file once
baseline/after measurements are captured and recorded in the doc.

Logs, per HTTP request: method, path, status, wall-clock ms, and SQL
statement count (via SQLAlchemy's before/after_cursor_execute events).
"""
import os
import time
import logging

logger = logging.getLogger("perf_probe")


def install(app, engine):
    if os.environ.get("PERF_PROBE") != "1":
        return

    from sqlalchemy import event

    state = {"count": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        state["count"] = state.get("count", 0) + 1

    @app.before_request
    def _perf_probe_start():
        from flask import g
        g._perf_probe_start = time.perf_counter()
        state["count"] = 0

    @app.after_request
    def _perf_probe_end(response):
        from flask import g, request
        start = getattr(g, "_perf_probe_start", None)
        if start is not None:
            elapsed_ms = (time.perf_counter() - start) * 1000
            query_count = state.get("count", 0)
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
