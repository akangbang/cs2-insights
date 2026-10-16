"""Download queued Valve demos and load them into PostgreSQL.

Usage: python -m cs2_insights.fetch [--sync] [--limit N] [--keep]
  --sync   first queue new matches for every linked account (python -m cs2_insights.link sync)
  --keep   keep the downloaded .dem.bz2 files in data/demos (deleted after parsing by default)
Run it at least daily: Valve deletes demos after about 30 days.
"""

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv

from cs2_insights import db, link
from cs2_insights.ingest import ingest

ROOT = Path(__file__).resolve().parents[2]
BOT_SCRIPT = ROOT / "bot" / "fetch_demo_urls.js"
DEMO_DIR = ROOT / "data" / "demos"

# Maps share codes to {"demo_url": ...} or {"error": ...}.
UrlFetcher = Callable[[list[str]], dict[str, dict]]


def bot_demo_urls(codes: list[str]) -> dict[str, dict]:
    """Ask the Node bot for each share code's demo URL."""
    result = subprocess.run(
        ["node", str(BOT_SCRIPT), *codes], capture_output=True, text=True, timeout=60 + 30 * len(codes)
    )
    if result.returncode != 0 and not result.stdout.strip():
        raise RuntimeError(f"demo bot failed: {result.stderr.strip().splitlines()[-1:] or result.returncode}")
    answers = {}
    for line in result.stdout.splitlines():
        if line.strip():
            item = json.loads(line)
            answers[item["share_code"]] = item
    return answers


def download(url: str, dest_dir: Path, session: requests.Session | None = None) -> Path | None:
    """Stream a demo to disk. Returns None if Valve no longer has it (HTTP 404)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / url.rsplit("/", 1)[-1]
    partial = target.with_name(target.name + ".part")
    with (session or requests).get(url, stream=True, timeout=60) as response:
        if response.status_code == 404:
            return None
        response.raise_for_status()
        with open(partial, "wb") as out:
            for chunk in response.iter_content(chunk_size=1 << 20):
                out.write(chunk)
    partial.replace(target)
    return target


def _set_status(conn: psycopg.Connection, code: str, status: str, **fields) -> None:
    assignments = ", ".join(f"{name} = %s" for name in fields)
    conn.execute(
        f"UPDATE share_codes SET status = %s, {assignments + ', ' if assignments else ''}updated_at = now() "
        "WHERE share_code = %s",
        (status, *fields.values(), code),
    )
    conn.commit()


def process_queue(
    conn: psycopg.Connection,
    limit: int = 20,
    url_fetcher: UrlFetcher = bot_demo_urls,
    session: requests.Session | None = None,
    demo_dir: Path = DEMO_DIR,
    keep: bool = False,
) -> dict[str, int]:
    """Fetch, download and parse up to `limit` queued matches, oldest first. Returns counts by outcome."""
    rows = conn.execute(
        """SELECT share_code, match_id, demo_url FROM share_codes
           WHERE status IN ('queued', 'fetched') ORDER BY created_at, match_id LIMIT %s""",
        (limit,),
    ).fetchall()
    counts = {"parsed": 0, "expired": 0, "failed": 0}
    if not rows:
        return counts

    need_urls = [code for code, _, url in rows if not url]
    answers = url_fetcher(need_urls) if need_urls else {}

    for code, match_id, url in rows:
        try:
            if not url:
                answer = answers.get(code, {"error": "no answer from the demo bot"})
                if "demo_url" not in answer:
                    status = "expired" if "expired" in answer["error"] else "failed"
                    _set_status(conn, code, status, error=answer["error"])
                    counts[status] += 1
                    continue
                url = answer["demo_url"]
                _set_status(conn, code, "fetched", demo_url=url, error=None)

            path = download(url, demo_dir, session=session)
            if path is None:
                _set_status(conn, code, "expired", error="Valve no longer has this demo")
                counts["expired"] += 1
                continue
            try:
                ingest(path, conn, force=True, match_id=match_id, source="valve")
            finally:
                if not keep:
                    path.unlink(missing_ok=True)
            _set_status(conn, code, "parsed", error=None)
            counts["parsed"] += 1
        except Exception as error:  # one bad match shouldn't stop the rest
            conn.rollback()
            _set_status(conn, code, "failed", error=str(error)[:500])
            counts["failed"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Download queued Valve demos and load them.")
    parser.add_argument("--sync", action="store_true", help="queue new matches for linked accounts first")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--keep", action="store_true", help="keep downloaded demo files")
    opts = parser.parse_args(argv)

    with db.connect() as conn:
        db.init_schema(conn)
        if opts.sync:
            link.main(["sync"])
        counts = process_queue(conn, limit=opts.limit, keep=opts.keep)
    print(", ".join(f"{n} {status}" for status, n in counts.items()))
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
