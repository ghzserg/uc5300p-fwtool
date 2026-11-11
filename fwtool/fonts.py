"""Bitmap fonts (emWin-like GUI_FONT_PROP chains): export glyphs as PNG, import them back."""
import json
import os
import struct

from PIL import Image


class FontError(Exception):
    pass


class Font:
    def __init__(self, index, ysize, struct_off, props):
        self.index, self.ysize, self.struct_off, self.props = index, ysize, struct_off, props

    @property
    def kind(self):
        return "k2" if any(p["last"] >= 0xA340 for p in self.props) else "k0"

    @property
    def name(self):
        return f"font{self.index}_{self.ysize}px"


def read_fonts(payload, pairs_off, count, ram2off):
    fonts = []
    for i in range(count):
        font_ram = struct.unpack_from("<I", payload, pairs_off + 8 * i + 4)[0]
        fo = ram2off(font_ram)
        ysize = payload[fo + 24]
        poff = ram2off(struct.unpack_from("<I", payload, fo + 28)[0])
        props = []
        while poff is not None and 0 <= poff < len(payload):
            first, last, ci, nxt = struct.unpack_from("<HHII", payload, poff)
            ci_off = ram2off(ci)
            glyphs = []
            for k in range(last - first + 1):
                o = ci_off + 8 * k
                xs, xd, bpl, pad = payload[o:o + 4]
                ptr = ram2off(struct.unpack_from("<I", payload, o + 4)[0])
                ok = (1 <= bpl <= 8 and ptr is not None and 0 <= ptr and ptr + bpl * ysize <= len(payload)
                      and xs <= bpl * 8 and xd <= 64)
                glyphs.append({"code": first + k, "ci_off": o, "xs": xs, "xd": xd, "bpl": bpl,
                               "pad": pad, "ptr": ptr if ok else None})
            props.append({"first": first, "last": last, "ci_off": ci_off, "glyphs": glyphs})
            poff = ram2off(nxt) if nxt else None
        fonts.append(Font(i, ysize, fo, props))
    return fonts


def glyph_bytes(payload, f, g):
    return bytes(payload[g["ptr"]:g["ptr"] + g["bpl"] * f.ysize])


def bits_to_image(data, bpl, ysize):
    im = Image.new("1", (bpl * 8, ysize), 1)       # 1 = white
    px = im.load()
    for y in range(ysize):
        row = data[y * bpl:(y + 1) * bpl]
        for x in range(bpl * 8):
            if row[x >> 3] & (0x80 >> (x & 7)):
                px[x, y] = 0                       # ink = black
    return im


def image_to_bits(im, bpl, ysize):
    im = im.convert("1")
    if im.size != (bpl * 8, ysize):
        raise FontError(f"glyph image must be {bpl * 8}x{ysize}, got {im.size}")
    px = im.load()
    out = bytearray(bpl * ysize)
    for y in range(ysize):
        for x in range(bpl * 8):
            if px[x, y] == 0:
                out[y * bpl + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(out)


def export_font(payload, f, outdir):
    d = os.path.join(outdir, f.name)
    os.makedirs(os.path.join(d, "glyphs"), exist_ok=True)
    meta = {"index": f.index, "ysize": f.ysize, "kind": f.kind, "glyphs": {}}
    seen = set()
    for p in f.props:
        for g in p["glyphs"]:
            if g["ptr"] is None:
                continue
            key = "%04X" % g["code"]
            shared = g["ptr"] in seen
            seen.add(g["ptr"])
            meta["glyphs"][key] = {"xsize": g["xs"], "xdist": g["xd"], "bpl": g["bpl"],
                                   **({"shared_bitmap": True} if shared else {})}
            if not shared:
                bits_to_image(glyph_bytes(payload, f, g), g["bpl"], f.ysize).save(
                    os.path.join(d, "glyphs", key + ".png"))
    with open(os.path.join(d, "font.json"), "w") as fh:
        json.dump(meta, fh, indent=1)


def import_font(payload, f, indir):
    """Apply PNG/JSON edits from `indir` to payload. Returns number of changed glyphs."""
    d = os.path.join(indir, f.name)
    if not os.path.isdir(d):
        return 0
    with open(os.path.join(d, "font.json")) as fh:
        meta = json.load(fh)
    changed = 0
    for p in f.props:
        for g in p["glyphs"]:
            if g["ptr"] is None:
                continue
            key = "%04X" % g["code"]
            m = meta["glyphs"].get(key)
            if m is None:
                continue
            png = os.path.join(d, "glyphs", key + ".png")
            if os.path.exists(png) and not m.get("shared_bitmap"):
                new = image_to_bits(Image.open(png), g["bpl"], f.ysize)
                if new != glyph_bytes(payload, f, g):
                    payload[g["ptr"]:g["ptr"] + len(new)] = new
                    changed += 1
            xs, xd = int(m["xsize"]), int(m["xdist"])
            if not (0 <= xs <= g["bpl"] * 8):
                raise FontError(f"{f.name} {key}: xsize {xs} does not fit {g['bpl'] * 8} bits")
            if (xs, xd) != (g["xs"], g["xd"]):
                payload[g["ci_off"]] = xs
                payload[g["ci_off"] + 1] = xd
                changed += 1
    return changed
