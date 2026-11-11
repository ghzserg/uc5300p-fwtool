import argparse
import hashlib
import json
import os
import sys

from . import __version__, container, workspace


def cmd_info(a):
    data = open(a.firmware, "rb").read()
    lay = container.parse(data)
    print(f"{a.firmware}: {len(data)} bytes  sha256={hashlib.sha256(data).hexdigest()}")
    for s in lay.sections:
        print(f"  section {s.index}: header@0x{s.pos:x} payload@0x{s.payload_off:x} size=0x{s.size:x} "
              f"load=0x{s.load:x} crc@0x{s.crc_off:x}")
    for v in lay.volumes:
        where = "in file" if v.offset + v.size <= len(data) else "flash only"
        print(f"  volume {v.index}: @0x{v.offset:x} size=0x{v.size:x} type={v.vtype} ({where})")


def cmd_verify(a):
    data = open(a.firmware, "rb").read()
    ok = True
    for good, msg in container.check(data):
        print(("OK   " if good else "FAIL ") + msg)
        ok &= good
    if a.emulate:
        from . import emuverify
        res = emuverify.run(data, a.profile)
        print(("OK   " if res.startswith("OK") else "FAIL ") + "device update routine (emulated): " + res)
        ok &= res.startswith("OK")
    return 0 if ok else 1


def cmd_unpack(a):
    man = workspace.unpack(a.firmware, a.work, a.profile, a.charmap)
    print(f"unpacked {man['source']['size']} bytes -> {a.work}/ ({len(man['segments'])} segments)")
    print("edit: app/strings/strings.tsv, app/fonts/*/glyphs/*.png, volumes/*/files/*, then: fwtool pack")


def cmd_pack(a):
    data, stats = workspace.pack(a.work, a.output)
    print(f"wrote {a.output} ({len(data)} bytes) sha256={hashlib.sha256(data).hexdigest()}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    rel = os.path.dirname(os.path.abspath(a.output))
    with open(os.path.join(rel, "BUILD_INFO.json"), "w") as fh:
        json.dump({"tool": "fwtool " + __version__, "file": os.path.basename(a.output),
                   "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), **stats}, fh, indent=1)
    if a.verify:
        class A: pass
        v = A(); v.firmware, v.emulate, v.profile = a.output, a.emulate, a.profile or "uc5300p"
        return cmd_verify(v)
    return 0


def cmd_overlay(a):
    from . import overlay
    overlay.apply(a.overlay, a.work, a.profile or "uc5300p")


def main(argv=None):
    p = argparse.ArgumentParser(prog="fwtool", description="UC5300P / Urive G600 firmware tool")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info"); s.add_argument("firmware"); s.set_defaults(f=cmd_info)
    s = sub.add_parser("verify", help="check MD5/CRC like the device does")
    s.add_argument("firmware"); s.add_argument("--emulate", action="store_true",
                                               help="also run the device's own update-check code (needs unicorn+capstone)")
    s.add_argument("--profile", default="uc5300p"); s.set_defaults(f=cmd_verify)
    s = sub.add_parser("unpack"); s.add_argument("firmware"); s.add_argument("work")
    s.add_argument("--profile", default="uc5300p")
    s.add_argument("--charmap", help="charmap.json to decode a modified firmware (e.g. the one from its work tree)")
    s.set_defaults(f=cmd_unpack)
    s = sub.add_parser("pack"); s.add_argument("work"); s.add_argument("output")
    s.add_argument("--profile"); s.add_argument("--verify", action="store_true")
    s.add_argument("--emulate", action="store_true"); s.set_defaults(f=cmd_pack)
    s = sub.add_parser("overlay", help="apply a translation overlay to an unpacked work tree")
    s.add_argument("overlay"); s.add_argument("work"); s.add_argument("--profile")
    s.set_defaults(f=cmd_overlay)
    a = p.parse_args(argv)
    try:
        return a.f(a) or 0
    except (SystemExit, KeyboardInterrupt):
        raise
    except Exception as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
