import zstandard

from cs2_insights.ingest import MIN_DEMO_BYTES, check_demo, completeness_warning, explain_parse_error

BIG = MIN_DEMO_BYTES * 10


def test_real_demo_files_pass():
    assert check_demo("match.dem", b"PBDEMS2\x00rest", BIG) is None
    assert check_demo("faceit.dem.gz", b"\x1f\x8b\x08rest", BIG) is None
    assert check_demo("faceit.dem.zst", b"\x28\xb5\x2f\xfdrest", BIG) is None
    assert check_demo("valve.dem.bz2", b"BZh91AY", BIG) is None


def test_each_problem_gets_its_own_message():
    assert "isn't a demo file" in check_demo("clip.mp4", b"\x00", BIG)
    assert "is empty" in check_demo("match.dem", b"", 0)
    assert "CS:GO demo" in check_demo("old.dem", b"HL2DEMO\x00", BIG)
    assert "isn't a real .dem file" in check_demo("renamed.dem", b"PK\x03\x04", BIG)  # a zip renamed to .dem
    assert "isn't a real .gz file" in check_demo("faceit.dem.gz", b"PBDEMS2", BIG)
    assert "too small" in check_demo("match.dem", b"PBDEMS2\x00", 2_000)


def test_parse_errors_get_plain_reasons():
    assert "cut off or damaged" in explain_parse_error(EOFError("Compressed file ended before the end-of-stream marker was reached"))
    assert "cut off or damaged" in explain_parse_error(zstandard.ZstdError("bad frame"))
    assert "no finished rounds" in explain_parse_error(ValueError("No completed rounds found in x.dem."))
    assert "too big" in explain_parse_error(MemoryError())
    # What a short cut-off demo actually raises inside the parser:
    assert "download the match again" in explain_parse_error(TypeError("list indices must be integers or slices, not str"))


def test_unfinished_matches_are_flagged():
    assert completeness_warning(13, 7) is None
    assert completeness_warning(16, 12) is None  # won in overtime
    assert "stops at 3–1" in completeness_warning(3, 1)  # cut off
    assert completeness_warning(12, 12) is not None  # tied: overtime missing
