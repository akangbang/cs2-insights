from cs2_insights.ingest import MIN_DEMO_BYTES, check_demo

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
