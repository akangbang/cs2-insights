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


# How each accepted file type starts, so a wrong or broken file gets a clear message before parsing.
SIGNATURES = {
    ".dem": b"PBDEMS2",
    ".gz": b"\x1f\x8b",
    ".zst": b"\x28\xb5\x2f\xfd",
    ".bz2": b"BZh",
}
CSGO_SIGNATURE = b"HL2DEMO"
MIN_DEMO_BYTES = 100_000  # a real match demo is tens of megabytes; anything this small is cut off or empty


def check_demo(name: str, head: bytes, size: int) -> str | None:
    """A plain-language problem with an uploaded file, or None if it looks like a CS2 demo."""
    suffix = Path(name).suffix.lower()
    if suffix not in SIGNATURES:
        return f"{name} isn't a demo file. Upload a .dem from CS2, or a .dem.gz / .dem.zst from FACEIT."
    if size == 0:
        return f"{name} is empty. The download probably failed: try downloading the match again."
    if suffix == ".dem" and head.startswith(CSGO_SIGNATURE):
        return f"{name} is a CS:GO demo. LeanPeek reads CS2 demos only."
    if not head.startswith(SIGNATURES[suffix]):
        return f"{name} isn't a real {suffix} file, even though it's named like one. It may be renamed, or something else entirely."
    if size < MIN_DEMO_BYTES:
        return f"{name} is too small to be a whole match ({size / 1000:.0f} KB). The download was probably cut off."
    return None


WIN_SCORE = 13  # MR12: first to 13 wins regulation; overtime keeps going from there


def explain_parse_error(error: BaseException) -> str:
    """A plain-language reason a demo couldn't be read."""
    if isinstance(error, (EOFError, zstandard.ZstdError, OSError)) and not isinstance(error, FileNotFoundError):
        return "The compressed file is cut off or damaged, so it can't be unpacked. Download it again from FACEIT."
    if isinstance(error, ValueError) and "No completed rounds" in str(error):
        return "This demo has no finished rounds. It may be warmup only, a match abandoned at the start, or not a competitive match."
    if isinstance(error, MemoryError):
        return "This demo is too big to analyse here. Try a shorter match, or run LeanPeek on your own PC."
    return ("LeanPeek couldn't read this demo. It's most likely cut off or damaged: download the match again. "
            "If it keeps happening, the demo may come from a CS2 update LeanPeek doesn't support yet.")


def completeness_warning(team_a_score: int, team_b_score: int) -> str | None:
    """A warning when a demo doesn't contain a finished match, so a partial report isn't taken as the whole game."""
    if max(team_a_score, team_b_score) >= WIN_SCORE and team_a_score != team_b_score:
        return None
    return (f"This demo stops at {team_a_score}–{team_b_score}, before anyone won. The file may be cut off, or the match "
            "ended early (a surrender or an abandon). The report only covers the rounds in it.")


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
    if not force and db.match_is_current(conn, match_id or match_id_from_path(stem)):
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
        # Keep the Power BI tables in step with what was just loaded.
        from cs2_insights.analytics import refresh

        rows = refresh(conn)
        print(f"analytics refreshed: {rows['fact_player_match']} player-matches, {rows['fact_death']} deaths")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
