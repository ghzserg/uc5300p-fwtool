"""Overlays: data-only patches (e.g. a translation) applied to an unpacked work tree.

overlays/<name>/overlay.json   {"title": ..., "free_slot_start": 29}
overlays/<name>/strings.tsv    id <TAB> text [<TAB> reference]   (empty text = blank the string)
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

from . import fonts as fontmod, profile as prof_mod
from .strings import CharMap, detect_kind
from .workspace import App, load_charmap, read_tsv

TTF_CANDIDATES = [
    os.environ.get("FWTOOL_TTF", ""),
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/TTF/DejaVuSansCondensed.ttf",
]
# pixel size of the TrueType font for each device font height (cap height ~ 0.8 of the Latin glyphs)
DEFAULT_SIZES = {14: 11, 16: 14, 18: 15, 20: 17, 22: 18, 24: 21}


def _ttf():
    for p in TTF_CANDIDATES:
        if p and os.path.exists(p):
            return p
    raise SystemExit("DejaVu Sans Condensed TTF not found (install fonts-dejavu-extra or set FWTOOL_TTF)")


def read_overlay_tsv(path):
    rows = {}
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh):
            line = line.rstrip("\n")
            if n == 0 or not line:
                continue
            parts = line.split("\t")
            rows[int(parts[0])] = parts[1] if len(parts) > 1 else ""
    return rows


def render_glyph(ch, ysize, bpl, size, base, ttf):
    f = ImageFont.truetype(ttf, size)
    im = Image.new("1", (bpl * 8 + 8, ysize + 12), 0)
    dr = ImageDraw.Draw(im)
    dr.fontmode = "1"
    dr.text((4, base + 1), ch, font=f, fill=1, anchor="ls")
    cols = [x for x in range(im.width) if any(im.getpixel((x, y)) for y in range(ysize))]
    if not cols:
        return None, 0
    x0, x1 = cols[0], cols[-1]
    w = x1 - x0 + 1
    if w > bpl * 8:
        raise SystemExit(f"glyph {ch!r} too wide ({w}px) for {bpl * 8}px cell")
    out = Image.new("1", (bpl * 8, ysize), 1)          # white background, black ink
    for y in range(ysize):
        for x in range(w):
            if im.getpixel((x0 + x, y)):
                out.putpixel((x, y), 0)
    return out, w


def apply(overlay_dir, work, profile_name="uc5300p"):
    if not os.path.isfile(os.path.join(work, "manifest.json")):
        raise SystemExit(f"{work} is not an unpacked work tree - run `make unpack` "
                         f"(fwtool unpack <firmware> {work}) first")
    prof = prof_mod.load(profile_name)
    with open(os.path.join(overlay_dir, "overlay.json")) as fh:
        meta = json.load(fh)
    first_slot = meta.get("free_slot_start", 29)
    new_rows = read_overlay_tsv(os.path.join(overlay_dir, "strings.tsv"))
    tsv_path = os.path.join(work, "app", "strings", "strings.tsv")
    rows = read_tsv(tsv_path)
    orig = json.load(open(os.path.join(work, "app", "strings", "strings.orig.json")))
    cm_path = os.path.join(work, "app", "charmap.json")
    cj = json.load(open(cm_path))
    cm = CharMap(cj["k2"], cj["k0"], cj.get("decode_only", ()))
    k0_below = prof["strings"]["k0_below_id"]
    # glyph slots still needed by rows we do not touch
    used = set()
    for sid, (enc, text) in rows.items():
        if sid in new_rows:
            continue
        if enc in ("k2", "ascii") and str(sid) in orig:
            used |= cm.slots_used(bytes.fromhex(orig[str(sid)]["hex"]))
    letters = sorted({c for t in new_rows.values() for c in t if ord(c) >= 0x80})
    free = [s for s in range(first_slot, len(cm.maps["k2"]))
            if s not in used and ((0xA1A1 + s) & 0xFF) != 0 and s not in cm.decode_only]
    if len(letters) > len(free):
        raise SystemExit(f"need {len(letters)} glyph slots, only {len(free)} free")
    assign = dict(zip(letters, free))
    for ch, slot in assign.items():
        cj["k2"][slot] = ch
    json.dump(cj, open(cm_path, "w"), ensure_ascii=False, indent=0)
    # rewrite string rows
    for sid, text in new_rows.items():
        if sid not in rows:
            raise SystemExit(f"overlay refers to unknown string id {sid}")
        rows[sid] = ("k2", text)
    lines = ["id\tenc\ttext"] + [f"{sid}\t{enc}\t{text}" for sid, (enc, text) in sorted(rows.items())]
    with open(tsv_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    # glyphs for every font of the k2 family
    ttf = _ttf()
    sizes = {int(k): v for k, v in meta.get("font_sizes", {}).items()} or DEFAULT_SIZES
    fonts_dir = os.path.join(work, "app", "fonts")
    n = 0
    for d in sorted(os.listdir(fonts_dir)):
        fj = os.path.join(fonts_dir, d, "font.json")
        m = json.load(open(fj))
        if m["kind"] != "k2":
            continue
        ysize = m["ysize"]
        hmeta = m["glyphs"]["0048"]
        himg = Image.open(os.path.join(fonts_dir, d, "glyphs", "0048.png")).convert("1")
        rows_ink = [y for y in range(ysize) if any(himg.getpixel((x, y)) == 0 for x in range(himg.width))]
        base = rows_ink[-1]
        for ch, slot in assign.items():
            key = "%04X" % (0xA1A1 + slot)
            bpl = m["glyphs"][key]["bpl"]
            img, w = render_glyph(ch, ysize, bpl, sizes.get(ysize, round(ysize * 0.8)), base, ttf)
            img.save(os.path.join(fonts_dir, d, "glyphs", key + ".png"))
            m["glyphs"][key]["xsize"], m["glyphs"][key]["xdist"] = w, w + 1
            n += 1
        json.dump(m, open(fj, "w"), indent=1)
    print(f"overlay '{meta.get('title', os.path.basename(overlay_dir))}': {len(new_rows)} strings, "
          f"{len(letters)} new glyphs x fonts = {n} glyph images")
