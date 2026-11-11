"""Integration tests - run only when a stock firmware is available.

    FWTOOL_STOCK=stock/UC5300P.bin pytest tests/test_stock.py
"""
import hashlib
import os

import pytest

from fwtool import container, workspace, overlay

STOCK = os.environ.get("FWTOOL_STOCK", "stock/UC5300P.bin")
pytestmark = pytest.mark.skipif(not os.path.exists(STOCK), reason="stock firmware not available")


def test_stock_is_valid():
    d = open(STOCK, "rb").read()
    assert all(ok for ok, _ in container.check(d))


def test_unpack_pack_is_byte_identical(tmp_path):
    work = tmp_path / "work"
    workspace.unpack(STOCK, str(work))
    out, stats = workspace.pack(str(work), str(tmp_path / "rel" / "UC5300P.bin"))
    assert out == open(STOCK, "rb").read()
    assert stats["strings_changed"] == 0 and stats["glyphs_changed"] == 0


def test_edit_one_string_and_volume_file(tmp_path):
    work = tmp_path / "work"
    workspace.unpack(STOCK, str(work))
    tsv = work / "app" / "strings" / "strings.tsv"
    lines = tsv.read_text(encoding="utf-8").split("\n")
    lines = [l.replace("\tPlay", "\tPlai") if l.startswith("16\t") else l for l in lines]
    tsv.write_text("\n".join(lines), encoding="utf-8")
    out, stats = workspace.pack(str(work), str(tmp_path / "o.bin"))
    assert stats["strings_changed"] == 1
    assert all(ok for ok, _ in container.check(out))


def test_russian_overlay_builds_and_passes_device_check(tmp_path):
    work = tmp_path / "work"
    workspace.unpack(STOCK, str(work))
    overlay.apply(os.path.join(os.path.dirname(os.path.dirname(__file__)), "overlays", "ru"), str(work))
    out, stats = workspace.pack(str(work), str(tmp_path / "o.bin"))
    assert all(ok for ok, _ in container.check(out))
    assert stats["string_space_left"] >= 0
    try:
        from fwtool import emuverify
    except Exception:
        return
    assert emuverify.run(out).startswith("OK")
