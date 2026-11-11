import hashlib
import struct

import pytest
from PIL import Image

from fwtool import container, fatimg, fonts
from fwtool.strings import CharMap, StringError, relocate


def test_crc16_mcrf4xx_vector():
    assert container.crc16(b"123456789") == 0x6F91


def make_fw(payload=b"hello world" * 100):
    """Synthetic single-section AITS image: header(0x20) + MCR2 hdr + payload."""
    pay_off = 0x2000
    size = len(payload)
    span = 0x6000
    d = bytearray(0x20 + span)
    d[:4] = b"AITS"
    hdr = 0x20
    d[hdr:hdr + 4] = b"MCR2"
    struct.pack_into("<IIIIII", d, hdr + 4, 0x40000001, 12, span >> 12, pay_off >> 12, size, 0x100000)
    d[hdr + 0x1FC:hdr + 0x200] = b"MCR2"
    d[hdr + pay_off:hdr + pay_off + size] = payload
    return bytearray(d)


def test_container_parse_check_fix():
    d = make_fw()
    lay = container.parse(bytes(d))
    assert len(lay.sections) == 1 and lay.sections[0].load == 0x100000
    assert not all(ok for ok, _ in container.check(bytes(d), lay))
    container.fix(d, lay)
    assert all(ok for ok, _ in container.check(bytes(d), lay))
    # the device computes MD5("VDRAC999" + data[0x20:])
    assert d[0x10:0x20] == hashlib.md5(b"VDRAC999" + bytes(d[0x20:])).digest()
    # corrupting one payload byte must break both checks
    d[0x2020 + 5] ^= 1
    assert not any(ok for ok, _ in container.check(bytes(d), lay)[1:])


def test_charmap_roundtrip_and_escapes():
    cm = CharMap(["가", "나", "다"], ["x"], decode_only=[2])
    for text in ["", "abc", "가나 가", "a\\\\b", "\\x09 tab", "\\cA3FF"]:
        assert cm.decode(cm.encode(text, "k2"), "k2") == text
    assert cm.encode("a\\\\b", "k2") == b"a\\b"          # `\\` in text is one backslash byte
    # decode-only slot is never produced by encode
    with pytest.raises(StringError):
        cm.encode("다", "k2")
    # unknown 2-byte codes survive a roundtrip
    raw = bytes([0xA3, 0x40, 0x41])
    assert cm.encode(cm.decode(raw, "k2"), "k2") == raw


def _table(texts):
    payload = bytearray(b"\x00" * 16)
    table = 0
    pos, ents = 64, []
    payload += b"\x00" * 128
    for i, t in enumerate(texts):
        payload[pos:pos + len(t)] = t
        struct.pack_into("<I", payload, 4 * i, 0x1000 + pos)
        ents.append({"id": i, "ptr": 0x1000 + pos, "off": pos, "data": t})
        pos += len(t) + 1
    return payload, table, ents


def test_relocate_shorter_string_reuses_space():
    payload, table, ents = _table([b"one", b"two", b"three"])
    relocate(payload, table, ents, {1: b"tw"}, lambda o: 0x1000 + o)
    p = struct.unpack_from("<I", payload, 4)[0] - 0x1000
    assert payload[p:p + 3] == b"tw\x00"
    assert payload[ents[0]["off"]:ents[0]["off"] + 3] == b"one"
    assert payload[ents[2]["off"]:ents[2]["off"] + 5] == b"three"


def test_relocate_grows_string_into_space_freed_by_other_changes():
    payload, table, ents = _table([b"one", b"two", b"three"])
    # string 1 grows; string 2 is blanked, which frees its bytes
    relocate(payload, table, ents, {1: b"twenty", 2: b""}, lambda o: 0x1000 + o)
    p1 = struct.unpack_from("<I", payload, 4)[0] - 0x1000
    assert payload[p1:p1 + 7] == b"twenty\x00"
    assert payload[ents[0]["off"]:ents[0]["off"] + 3] == b"one"


def test_relocate_out_of_space():
    payload = bytearray(b"\x00" * 64)
    payload[32:36] = b"ab\x00\x00"
    struct.pack_into("<I", payload, 0, 32)
    ents = [{"id": 0, "ptr": 32, "off": 32, "data": b"ab"}]
    with pytest.raises(StringError):
        relocate(payload, 0, ents, {0: b"x" * 200}, lambda o: o)


def test_glyph_png_roundtrip(tmp_path):
    data = bytes([0b10100000, 0b01010000] * 8)       # 2 bytes per row, 8 rows
    im = fonts.bits_to_image(data, 2, 8)
    p = tmp_path / "g.png"
    im.save(p)
    assert fonts.image_to_bits(Image.open(p), 2, 8) == data
    with pytest.raises(fonts.FontError):
        fonts.image_to_bits(Image.new("1", (8, 8)), 2, 8)


def _fat12_image():
    """Tiny FAT12 volume with two root files, built by hand."""
    bps, spc, res, nfats, rootent, total, spf = 512, 1, 1, 2, 16, 64, 1
    img = bytearray(total * bps)
    img[0:3] = b"\xeb\x58\x90"
    struct.pack_into("<HBHBHHBH", img, 11, bps, spc, res, nfats, rootent, total, 0xF8, spf)
    root = (res + nfats * spf) * bps
    data = root + rootent * 32
    fat = [0xFF8, 0xFFF] + [0] * 60

    def add(i, name, cl, content):
        e = root + i * 32
        img[e:e + 11] = name
        img[e + 11] = 0x20
        struct.pack_into("<H", img, e + 26, cl)
        struct.pack_into("<I", img, e + 28, len(content))
        n = (len(content) + 511) // 512
        for j in range(n):
            fat[cl + j] = cl + j + 1
        fat[cl + n - 1] = 0xFFF
        img[data + (cl - 2) * 512:data + (cl - 2) * 512 + len(content)] = content
        return cl + n

    nxt = add(0, b"A       BIN", 2, b"A" * 700)
    add(1, b"B       BIN", nxt, b"B" * 100)
    f = fatimg.Fat(bytes(img))
    fb = f._fat_bytes(fat)
    for k in range(nfats):
        o = res * bps + k * spf * bps
        img[o:o + len(fb)] = fb
    return bytes(img)


def test_fat12_read_replace_relayout():
    img = _fat12_image()
    f = fatimg.Fat(img)
    assert f.fat12
    files = f.files()
    assert files == {"A.BIN": b"A" * 700, "B.BIN": b"B" * 100}
    assert f.write(files) == img                                  # unchanged -> identical
    same_clusters = dict(files, **{"A.BIN": b"X" * 650})          # same cluster count -> in place
    assert fatimg.Fat(f.write(same_clusters)).files() == same_clusters
    bigger = dict(files, **{"A.BIN": b"Y" * 2000})               # re-layout, FAT regenerated
    out = fatimg.Fat(f.write(bigger))
    assert out.files() == bigger
    with pytest.raises(fatimg.FatError):
        f.write({"NEW.BIN": b"1"})
    with pytest.raises(fatimg.FatError):
        f.write({"A.BIN": b"Z" * 100000})
