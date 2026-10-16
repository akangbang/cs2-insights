import bz2
import gzip

import zstandard

from cs2_insights.ingest import find_demos, plain_demo

CONTENT = b"PBDEMS2\x00 fake demo bytes"


def test_find_demos_filters_by_extension(tmp_path):
    for name in ["a.dem", "b.dem.bz2", "c.dem.gz", "d.dem.zst", "notes.txt", "e.zip"]:
        (tmp_path / name).write_bytes(b"x")
    assert [p.name for p in find_demos([tmp_path])] == ["a.dem", "b.dem.bz2", "c.dem.gz", "d.dem.zst"]


def test_plain_demo_decompresses_each_format(tmp_path):
    files = {
        "m.dem.bz2": bz2.compress(CONTENT),
        "m.dem.gz": gzip.compress(CONTENT),
        "m.dem.zst": zstandard.ZstdCompressor().compress(CONTENT),
    }
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
        with plain_demo(tmp_path / name) as demo:
            assert demo.name == "m.dem"
            assert demo.read_bytes() == CONTENT


def test_plain_demo_passes_through_uncompressed(tmp_path):
    path = tmp_path / "m.dem"
    path.write_bytes(CONTENT)
    with plain_demo(path) as demo:
        assert demo == path
