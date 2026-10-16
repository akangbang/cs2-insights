"""Parse demo files and load them into PostgreSQL (the .dem upload path).

Usage: python -m cs2_insights.ingest <file or folder> [...] [--force]
Accepts .dem plus the compressed forms Valve (.dem.bz2) and FACEIT (.dem.gz, .dem.zst) serve.
"""

import argparse
import bz2
import gzip
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import zstandard

from cs2_insights import db
from cs2_insights.demo import match_id_from_path, parse_demo

DEMO_SUFFIXES = (".dem", ".dem.bz2", ".dem.gz", ".dem.zst")
OPENERS = {".bz2": bz2.open, ".gz": gzip.open}


def find_demos(paths: list[Path]) -> list[Path]:
    found = []
    for path in paths:
        candidates = sorted(path.iterdir()) if path.is_dir() else [path]
        found += [p for p in candidates if p.name.lower().endswith(DEMO_SUFFIXES)]
    return found


@contextmanager
def plain_demo(path: Path) -> Iterator[Path]:
    """Yield a path to an uncompressed .dem, decompressing to a temp file if needed."""
    suffix = path.suffix.lower()
    if suffix == ".dem":
        yield path
        return
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / path.name[: -len(suffix)]
        with open(target, "wb") as out:
            if suffix == ".zst":
                with open(path, "rb") as src:
                    zstandard.ZstdDecompressor().copy_stream(src, out)
            else:
                with OPENERS[suffix](path, "rb") as src:
                    shutil.copyfileobj(src, out)
        yield target


def ingest(path: Path, conn, force: bool = False, match_id: str | None = None, source: str | None = None) -> str:
    """Parse and load one demo. Returns a one-line summary."""
    stem = Path(path.name[: -len(path.suffix)]) if path.suffix.lower() != ".dem" else path
    if not force and db.match_exists(conn, match_id or match_id_from_path(stem)):
        return f"skip   {path.name} (already loaded)"
    with plain_demo(path) as demo:
        parsed = parse_demo(demo, match_id=match_id, source=source)
    db.load_parsed(conn, parsed)
    m = parsed.match.iloc[0]
    return f"loaded {path.name}: {m['map']} {m['team_a_score']}-{m['team_b_score']}, {m['rounds']} rounds"


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("paths", nargs="+", type=Path)
    args.add_argument("--force", action="store_true", help="re-parse matches already loaded")
    opts = args.parse_args(argv)

    demos = find_demos(opts.paths)
    if not demos:
        print("No demo files found.")
        return 1
    failures = 0
    with db.connect() as conn:
        db.init_schema(conn)
        for demo in demos:
            try:
                print(ingest(demo, conn, opts.force))
            except Exception as error:  # one bad file shouldn't stop the batch
                failures += 1
                print(f"FAILED {demo.name}: {error}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
