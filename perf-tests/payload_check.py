"""Check payload sizes and gzip compression potential for the board JSON
endpoint and key static assets, and whether nginx is actually serving
gzip today (vs. what it could achieve).

Usage:
    python perf-tests/payload_check.py --board-id 1
"""
import argparse
import gzip
import json
import subprocess
from pathlib import Path

import requests

from seed_board import ensure_admin_and_login, BASE_URL

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_ASSETS = [
    REPO_ROOT / "www" / "js" / "board.js",
    REPO_ROOT / "www" / "css" / "board.css",
]


def _wire_bytes_via_curl(url, cookie_header=None):
    """Measure actual bytes transferred over the wire using curl's
    %{size_download}, with --compressed so curl requests gzip but reports
    the RAW (still-compressed) download size — unlike `requests`, which
    transparently decompresses and hides the real transfer size, and unlike
    Content-Length, which nginx omits here because gzip'd responses are
    sent chunked (no upfront total size is known).
    """
    headers = ["-H", "Accept-Encoding: gzip"]
    if cookie_header:
        headers += ["-H", f"Cookie: {cookie_header}"]
    result = subprocess.run(
        ["curl", "-s", *headers, "-w", "\n__SIZE__:%{size_download}", url],
        capture_output=True, timeout=30, check=False,
    )
    stdout = result.stdout
    marker = b"\n__SIZE__:"
    idx = stdout.rfind(marker)
    if idx == -1:
        return None
    try:
        return int(stdout[idx + len(marker):].strip())
    except ValueError:
        return None


def _served_encoding(url, session=None):
    """GET a URL with Accept-Encoding: gzip and report both the actual
    wire size (compressed, via curl) and what `requests` sees decompressed.
    """
    getter = session.get if session else requests.get
    resp = getter(url, headers={"Accept-Encoding": "gzip"})

    cookie_header = None
    if session is not None:
        cookie_header = "; ".join(f"{c.name}={c.value}" for c in session.cookies)

    wire_bytes = _wire_bytes_via_curl(url, cookie_header=cookie_header)

    return {
        "url": url,
        "status": resp.status_code,
        "content_encoding_header": resp.headers.get("Content-Encoding"),
        "served_bytes_over_wire": wire_bytes,
        "decompressed_bytes": len(resp.content),
    }


def check(board_id):
    session = ensure_admin_and_login()

    board_url = f"{BASE_URL}/api/boards/{board_id}/cards?archived=false"
    served = _served_encoding(board_url, session=session)
    board_json_bytes = session.get(board_url).content

    gz_board = gzip.compress(board_json_bytes, compresslevel=9)

    result = {
        "board_endpoint": {
            **served,
            "uncompressed_bytes": len(board_json_bytes),
            "gzip9_bytes": len(gz_board),
            "gzip9_ratio": round(len(board_json_bytes) / len(gz_board), 1) if gz_board else None,
            "currently_gzipped_by_server": served["content_encoding_header"] == "gzip",
        },
        "static_assets": [],
    }

    for asset_path in STATIC_ASSETS:
        if not asset_path.exists():
            continue
        rel = asset_path.relative_to(REPO_ROOT)
        url = f"{BASE_URL}/{rel.as_posix().replace('www/', '', 1)}"
        served = _served_encoding(url)
        raw_bytes = asset_path.read_bytes()
        gz_bytes = gzip.compress(raw_bytes, compresslevel=9)
        result["static_assets"].append({
            "path": str(rel),
            **served,
            "uncompressed_bytes": len(raw_bytes),
            "gzip9_bytes": len(gz_bytes),
            "gzip9_ratio": round(len(raw_bytes) / len(gz_bytes), 1) if gz_bytes else None,
            "currently_gzipped_by_server": served["content_encoding_header"] == "gzip",
        })

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-id", type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(check(args.board_id), indent=2))


if __name__ == "__main__":
    main()
