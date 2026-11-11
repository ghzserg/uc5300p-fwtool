"""UI string table: decode to editable text, encode back, relocate changed strings."""
import re
import struct

_TOKEN = re.compile(r"\\(\\|x[0-9A-Fa-f]{2}|c[0-9A-Fa-f]{4})")


class StringError(Exception):
    pass


class CharMap:
    """slot -> char lists for the two glyph families of the device."""

    def __init__(self, k2, k0, decode_only=()):
        self.maps = {"k2": list(k2), "k0": list(k0)}
        self.decode_only = set(decode_only)

    def _inv(self, kind):
        inv = {}
        for i, ch in enumerate(self.maps[kind]):
            if ch and ch not in inv and not (kind == "k2" and i in self.decode_only):
                inv[ch] = i
        return inv

    def decode(self, b: bytes, kind: str) -> str:
        m = self.maps[kind] if kind in self.maps else []
        out, i = [], 0
        while i < len(b):
            c = b[i]
            if c >= 0xA1 and i + 1 < len(b) and kind != "ascii":
                code = (c << 8) | b[i + 1]
                slot = code - 0xA1A1
                ch = m[slot] if 0 <= slot < len(m) else ""
                out.append(ch if ch else "\\c%04X" % code)
                i += 2
                continue
            if 0x20 <= c < 0x7F:
                out.append("\\\\" if c == 0x5C else chr(c))
            else:
                out.append("\\x%02X" % c)
            i += 1
        return "".join(out)

    def encode(self, text: str, kind: str) -> bytes:
        inv = self._inv(kind) if kind in self.maps else {}
        out, pos = bytearray(), 0
        while pos < len(text):
            m = _TOKEN.match(text, pos)
            if m:
                t = m.group(1)
                if t == "\\":
                    out.append(0x5C)
                elif t[0] == "x":
                    out.append(int(t[1:], 16))
                else:
                    code = int(t[1:], 16)
                    out += bytes([code >> 8, code & 0xFF])
                pos = m.end()
                continue
            ch = text[pos]
            if ord(ch) < 0x80:
                out.append(ord(ch))
            elif ch in inv:
                code = 0xA1A1 + inv[ch]
                out += bytes([code >> 8, code & 0xFF])
            else:
                raise StringError(f"character {ch!r} (U+{ord(ch):04X}) has no glyph slot in the "
                                  f"'{kind}' charmap; run `fwtool charmap-assign` or edit charmap.json")
            pos += 1
        return bytes(out)

    def slots_used(self, b: bytes):
        used, i = set(), 0
        while i < len(b):
            if b[i] >= 0xA1 and i + 1 < len(b):
                used.add(((b[i] << 8) | b[i + 1]) - 0xA1A1)
                i += 2
            else:
                i += 1
        return used


def detect_kind(b: bytes, sid: int, k0_below_id: int) -> str:
    leads, i = [], 0
    while i < len(b):
        if b[i] >= 0xA1 and i + 1 < len(b):
            leads.append(b[i])
            i += 2
        else:
            i += 1
    if not leads:
        return "ascii"
    if sid < k0_below_id and all(l == 0xA1 for l in leads):
        return "k0"
    return "k2"


def read_table(payload: bytes, table_off: int, count: int, ram2off):
    """Return list of dicts {id, ptr, off, data} (ptr = RAM address)."""
    ents = []
    for i in range(count):
        ptr = struct.unpack_from("<I", payload, table_off + 4 * i)[0]
        off = ram2off(ptr)
        if off is None or not (0 <= off < len(payload)):
            ents.append({"id": i, "ptr": ptr, "off": None, "data": None})
            continue
        end = payload.index(b"\x00", off)
        ents.append({"id": i, "ptr": ptr, "off": off, "data": bytes(payload[off:end])})
    return ents


def relocate(payload: bytearray, table_off: int, ents, new: dict, off2ram):
    """Apply {id: new bytes}. Frees the old text of changed strings and re-allocates (first fit)."""
    changed = {i: b for i, b in new.items() if ents[i]["data"] != b}
    if not changed:
        return 0
    keep_ptr_offs = {e["off"] for e in ents if e["off"] is not None and e["id"] not in changed}
    free = set()
    for i in changed:
        e = ents[i]
        a, b = e["off"], e["off"] + len(e["data"]) + 1
        if any(a <= p < b for p in keep_ptr_offs):      # still referenced by an unchanged id
            continue
        free.add((a, b))
    free = sorted(free)
    merged = []
    for a, b in free:
        if merged and merged[-1][1] >= a:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    space = [list(r) for r in merged]
    for a, b in merged:
        payload[a:b] = b"\x00" * (b - a)
    uniq = sorted(set(changed.values()), key=lambda x: -len(x))
    addr = {}
    for data in uniq:
        need = len(data) + 1
        for r in space:
            if r[1] - r[0] >= need:
                addr[data] = r[0]
                r[0] += need
                break
        else:
            raise StringError(f"no space for {len(data)}-byte string; free space left "
                              f"{sum(r[1] - r[0] for r in space)} bytes in the string area. "
                              "Shorten strings, or blank unused ones (empty text) to free space - see overlays/ru for an example.")
    for data, a in addr.items():
        payload[a:a + len(data)] = data
        payload[a + len(data)] = 0
    for i, data in changed.items():
        struct.pack_into("<I", payload, table_off + 4 * i, off2ram(addr[data]))
    return sum(r[1] - r[0] for r in space)
