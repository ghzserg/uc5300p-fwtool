"""Firmware container: AITS header, MCR2 sections, CRC16, keyed MD5, flash volumes."""
import hashlib
import struct
from dataclasses import dataclass, field

MAGIC = b"AITS"
MCR2 = b"MCR2"
HASH_KEY = b"VDRAC999"      # 8-byte prefix the device feeds into MD5 (see docs/FORMAT.md)
SECTOR = 512
FILE_BIAS = 0x20             # flash offset N is stored at file offset N + 0x20
HDR_PAD = 0x1000             # CRC16 lives at (payload flash offset - 0x1000)

_TAB = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0x8408 if _c & 1 else _c >> 1
    _TAB.append(_c)


def crc16(data: bytes, init: int = 0xFFFF) -> int:
    """CRC-16/MCRF4XX (poly 0x1021 reflected, init 0xFFFF, no xorout) - used by the AIT boot loader."""
    c = init
    for b in data:
        c = (c >> 8) ^ _TAB[(c ^ b) & 0xFF]
    return c


def header_md5(data: bytes) -> bytes:
    """MD5(HASH_KEY + data[0x20:]) - stored in data[0x10:0x20]."""
    return hashlib.md5(HASH_KEY + data[FILE_BIAS:]).digest()


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


@dataclass
class Section:
    index: int
    pos: int            # file offset of the MCR2 header
    flags: int
    shift: int
    span: int           # bytes occupied (header + payload + padding)
    payload_off: int    # file offset of payload
    size: int           # payload size
    load: int           # RAM load address
    crc_off: int        # file offset of stored CRC16

    @property
    def payload_end(self):
        return self.payload_off + self.size

    @property
    def end(self):
        return self.pos + self.span

    def ram(self, file_off):
        return self.load + (file_off - self.payload_off)

    def off(self, ram):
        return self.payload_off + (ram - self.load)


@dataclass
class Volume:
    index: int
    offset: int
    size: int
    vtype: int


@dataclass
class Layout:
    sections: list = field(default_factory=list)
    volumes: list = field(default_factory=list)
    total: int = 0


def parse(data: bytes) -> Layout:
    if data[:4] != MAGIC:
        raise ValueError("not an AITS firmware (bad magic)")
    lay = Layout(total=len(data))
    pos = FILE_BIAS
    idx = 1
    while data[pos:pos + 4] == MCR2 and data[pos + 0x1FC:pos + 0x200] == MCR2:
        flags, shift, span_u, pay_u, size, load = struct.unpack_from("<IIIIII", data, pos + 4)
        payload_off = (pay_u << shift) + FILE_BIAS
        sec = Section(idx, pos, flags, shift, span_u << shift, payload_off, size, load,
                      payload_off - HDR_PAD)
        lay.sections.append(sec)
        pos = sec.end
        idx += 1
    if not lay.sections:
        raise ValueError("no MCR2 sections found")
    first = lay.sections[0]
    o = first.pos + 0xC0
    vi = 1
    while o + 16 <= first.pos + 0x1F0:
        start, nsec, vtype, _ = struct.unpack_from("<IIII", data, o)
        if start == 0 and nsec == 0:
            break
        lay.volumes.append(Volume(vi, start * SECTOR + FILE_BIAS, nsec * SECTOR, vtype))
        vi += 1
        o += 16
    return lay


def check(data: bytes, lay: Layout = None):
    """Return list of (ok, message) checks identical to what the device performs."""
    lay = lay or parse(data)
    res = [(data[:4] == MAGIC, "magic AITS"),
           (header_md5(data) == data[0x10:0x20], "header MD5 (key+data[0x20:])")]
    for s in lay.sections:
        calc = crc16(data[s.payload_off:s.payload_end])
        stored = struct.unpack_from("<H", data, s.crc_off)[0]
        res.append((calc == stored, f"section {s.index} CRC16 calc={calc:04x} stored={stored:04x}"))
    return res


def fix(data: bytearray, lay: Layout = None) -> bytearray:
    """Recompute all section CRC16s and the header MD5 in place."""
    lay = lay or parse(bytes(data))
    for s in lay.sections:
        struct.pack_into("<H", data, s.crc_off, crc16(bytes(data[s.payload_off:s.payload_end])))
    data[0x10:0x20] = header_md5(bytes(data))
    return data
