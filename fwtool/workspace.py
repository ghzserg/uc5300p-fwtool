"""unpack: firmware -> editable work tree.   pack: work tree -> firmware."""
import hashlib
import json
import os
import shutil

from . import __version__, container, fatimg, fonts as fontmod, profile as prof_mod
from .strings import CharMap, StringError, detect_kind, read_table, relocate

SEC_NAMES = {1: "boot", 2: "stage2", 3: "app"}


def _w(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def _r(path):
    with open(path, "rb") as fh:
        return fh.read()


class App:
    """Helper that knows where things live inside the application section payload."""

    def __init__(self, prof, sec):
        self.prof, self.sec = prof, sec
        self.table_off = sec.off(prof_mod.num(prof, "strings", "table_ram")) - sec.payload_off
        self.count = prof["strings"]["count"]
        self.valid = prof["strings"]["valid_count"]
        self.k0_below = prof["strings"]["k0_below_id"]
        self.pairs_off = sec.off(prof_mod.num(prof, "fonts", "pairs_ram")) - sec.payload_off
        self.nfonts = prof["fonts"]["count"]

    def ram2off(self, ram):
        o = ram - self.sec.load
        return o if 0 <= o < self.sec.size else None

    def off2ram(self, off):
        return self.sec.load + off


def load_charmap(path):
    with open(path) as fh:
        j = json.load(fh)
    return CharMap(j["k2"], j["k0"], j.get("decode_only", ()))


# ----------------------------------------------------------------------------- unpack
def unpack(fw_path, work, profile_name="uc5300p", charmap=None):
    data = _r(fw_path)
    lay = container.parse(data)
    prof = prof_mod.load(profile_name)
    if os.path.exists(work) and os.listdir(work):
        raise SystemExit(f"{work} is not empty")
    segs = []

    def seg(name, off, length, rel, kind="raw"):
        segs.append({"name": name, "offset": off, "length": length, "path": rel, "type": kind})
        if kind == "raw":
            _w(os.path.join(work, rel), data[off:off + length])

    seg("header", 0, 0x20, "container/header.bin")
    for s in lay.sections:
        d = f"container/sec{s.index}_{SEC_NAMES.get(s.index, 'x')}"
        seg(f"sec{s.index}.header", s.pos, s.payload_off - s.pos, d + "/header.bin")
        seg(f"sec{s.index}.payload", s.payload_off, s.size, d + "/payload.bin")
        seg(f"sec{s.index}.tail", s.payload_end, s.end - s.payload_end, d + "/tail.bin")
    vols = [v for v in lay.volumes if v.offset + v.size <= len(data)]
    pos = lay.sections[-1].end
    seg("gap", pos, vols[0].offset - pos, "container/gap.bin")
    for v in vols:
        rel = f"volumes/vol{v.index}"
        img = data[v.offset:v.offset + v.size]
        f = fatimg.Fat(img)
        for name, content in f.files().items():
            _w(os.path.join(work, rel, "files", name), content)
        _w(os.path.join(work, rel, "volume.tpl"), f.template())
        with open(os.path.join(work, rel, "volume.json"), "w") as fh:
            json.dump({"index": v.index, "type": v.vtype, "fat": 12 if f.fat12 else 16,
                       "files": [e["name"] for e in f.entries()]}, fh, indent=1)
        segs.append({"name": f"vol{v.index}", "offset": v.offset, "length": v.size, "path": rel,
                     "type": "volume"})
    end = vols[-1].offset + vols[-1].size
    seg("post", end, len(data) - end, "container/post.bin")
    segs.sort(key=lambda s: s["offset"])
    # app decode ------------------------------------------------------------------
    sec = lay.sections[prof["app_section"] - 1]
    payload = data[sec.payload_off:sec.payload_end]
    app = App(prof, sec)
    cm_src = charmap or prof_mod.charmap_path(prof)
    cm = load_charmap(cm_src)
    ents = read_table(payload, app.table_off, app.count, app.ram2off)
    adir = os.path.join(work, "app")
    rows, orig = ["id\tenc\ttext"], {}
    for e in ents[:app.valid]:
        if e["data"] is None:
            continue
        kind = detect_kind(e["data"], e["id"], app.k0_below)
        rows.append(f"{e['id']}\t{kind}\t{cm.decode(e['data'], kind)}")
        orig[e["id"]] = {"enc": kind, "hex": e["data"].hex(), "ptr": e["ptr"]}
    _w(os.path.join(adir, "strings", "strings.tsv"), ("\n".join(rows) + "\n").encode("utf-8"))
    with open(os.path.join(adir, "strings", "strings.orig.json"), "w") as fh:
        json.dump(orig, fh)
    shutil.copy(cm_src, os.path.join(adir, "charmap.json"))
    fl = fontmod.read_fonts(payload, app.pairs_off, app.nfonts, app.ram2off)
    for f in fl:
        fontmod.export_font(payload, f, os.path.join(adir, "fonts"))
    manifest = {"tool": "fwtool " + __version__, "profile": profile_name,
                "source": {"name": os.path.basename(fw_path), "size": len(data),
                           "sha256": hashlib.sha256(data).hexdigest()},
                "segments": segs}
    with open(os.path.join(work, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    return manifest


# ----------------------------------------------------------------------------- pack
def read_tsv(path):
    rows = {}
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh):
            line = line.rstrip("\n")
            if n == 0 or not line:
                continue
            sid, enc, text = (line.split("\t", 2) + [""])[:3]
            rows[int(sid)] = (enc, text)
    return rows


def apply_app(work, prof, sec, payload):
    app = App(prof, sec)
    stats = {}
    cm = load_charmap(os.path.join(work, "app", "charmap.json"))
    ents = read_table(bytes(payload), app.table_off, app.count, app.ram2off)
    rows = read_tsv(os.path.join(work, "app", "strings", "strings.tsv"))
    new = {}
    for sid, (enc, text) in rows.items():
        if ents[sid]["data"] is None:
            continue
        old = ents[sid]["data"]
        kind = enc if enc in ("k0", "k2") else "k2"
        if cm.decode(old, detect_kind(old, sid, app.k0_below)) == text and enc == detect_kind(old, sid, app.k0_below):
            new[sid] = old                      # untouched row: keep the original bytes verbatim
            continue
        try:
            new[sid] = cm.encode(text, kind)
        except StringError as ex:
            raise StringError(f"string {sid}: {ex}")
    stats["strings_changed"] = sum(1 for i, b in new.items() if ents[i]["data"] != b)
    stats["string_space_left"] = relocate(payload, app.table_off, ents, new, app.off2ram)
    fl = fontmod.read_fonts(bytes(payload), app.pairs_off, app.nfonts, app.ram2off)
    stats["glyphs_changed"] = sum(fontmod.import_font(payload, f, os.path.join(work, "app", "fonts")) for f in fl)
    return stats


def pack(work, out_path, profile_name=None):
    with open(os.path.join(work, "manifest.json")) as fh:
        man = json.load(fh)
    prof = prof_mod.load(profile_name or man["profile"])
    total = man["source"]["size"]
    buf = bytearray(total)
    app_sec_idx = prof["app_section"]
    stats = {}
    for s in man["segments"]:
        p = os.path.join(work, s["path"])
        if s["type"] == "volume":
            f = fatimg.Fat(_r(os.path.join(p, "volume.tpl")))
            files = {}
            fdir = os.path.join(p, "files")
            names = json.load(open(os.path.join(p, "volume.json")))["files"]
            for n in names:
                fp = os.path.join(fdir, n)
                if not os.path.exists(fp):
                    raise SystemExit(f"{fp} is missing (deleting files from a volume is not supported)")
                files[n] = _r(fp)
            img = f.write(files)
            if len(img) != s["length"]:
                raise SystemExit("volume size changed")
            buf[s["offset"]:s["offset"] + s["length"]] = img
            continue
        data = _r(p)
        if len(data) != s["length"]:
            raise SystemExit(f"{s['path']}: size {len(data)} != {s['length']} (segments are fixed-size)")
        if s["name"] == f"sec{app_sec_idx}.payload":
            lay_tmp = None
            payload = bytearray(data)
            hdr = next(x for x in man["segments"] if x["name"] == f"sec{app_sec_idx}.header")
            # reconstruct app section geometry from the (unmodified) container header
            full_hdr = _r(os.path.join(work, hdr["path"]))
            geo = _section_from_header(hdr["offset"], full_hdr, s["offset"], s["length"])
            stats = apply_app(work, prof, geo, payload)
            data = bytes(payload)
        buf[s["offset"]:s["offset"] + s["length"]] = data
    lay = container.parse(bytes(buf))
    container.fix(buf, lay)
    ok = all(c[0] for c in container.check(bytes(buf), lay))
    if not ok:
        raise SystemExit("internal error: built image failed container checks")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(buf)
    return bytes(buf), stats


def _section_from_header(pos, hdr, payload_off, size):
    import struct
    flags, shift, span_u, pay_u, sz, load = struct.unpack_from("<IIIIII", hdr, 4)
    return container.Section(0, pos, flags, shift, span_u << shift, payload_off, size, load,
                             payload_off - container.HDR_PAD)
