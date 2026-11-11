"""Minimal FAT12/FAT16 image handling (root directory only), used for flash volumes.

Unpack: extract files.  Pack: replace file contents keeping every other byte of the volume
(boot sector, directory entries incl. long names, timestamps) untouched.
"""
import struct


class FatError(Exception):
    pass


class Fat:
    def __init__(self, img: bytes):
        self.img = bytearray(img)
        b = self.img
        self.bps = struct.unpack_from("<H", b, 11)[0]
        self.spc = b[13]
        self.res = struct.unpack_from("<H", b, 14)[0]
        self.nfats = b[16]
        self.rootent = struct.unpack_from("<H", b, 17)[0]
        tot16 = struct.unpack_from("<H", b, 19)[0]
        self.spf = struct.unpack_from("<H", b, 22)[0]
        tot32 = struct.unpack_from("<I", b, 32)[0]
        self.total = tot16 or tot32
        if self.bps not in (512, 1024, 2048, 4096) or not self.spc or not self.nfats or not self.spf:
            raise FatError("not a FAT12/16 boot sector")
        self.fat_off = self.res * self.bps
        self.root_off = (self.res + self.nfats * self.spf) * self.bps
        self.data_off = self.root_off + self.rootent * 32
        self.clsz = self.spc * self.bps
        self.nclusters = (self.total * self.bps - self.data_off) // self.clsz
        self.fat12 = self.nclusters < 4085

    # --- FAT table -------------------------------------------------------
    def _fat_get(self, n):
        o = self.fat_off
        if self.fat12:
            p = o + n + n // 2
            v = self.img[p] | (self.img[p + 1] << 8)
            return (v >> 4) if n & 1 else (v & 0xFFF)
        return struct.unpack_from("<H", self.img, o + 2 * n)[0]

    def _fat_table(self):
        return [self._fat_get(i) for i in range(self.nclusters + 2)]

    def _fat_bytes(self, fat):
        if self.fat12:
            out = bytearray((len(fat) * 3 + 1) // 2 + 2)
            for n, v in enumerate(fat):
                p = n + n // 2
                if n & 1:
                    out[p] = (out[p] & 0x0F) | ((v & 0x0F) << 4)
                    out[p + 1] = (v >> 4) & 0xFF
                else:
                    out[p] = v & 0xFF
                    out[p + 1] = (out[p + 1] & 0xF0) | ((v >> 8) & 0x0F)
            return bytes(out[:self.spf * self.bps])
        return b"".join(struct.pack("<H", v) for v in fat)

    def _eof(self):
        return 0xFFF if self.fat12 else 0xFFFF

    # --- directory -------------------------------------------------------
    def entries(self):
        out, lfn = [], []
        for i in range(self.rootent):
            o = self.root_off + i * 32
            e = bytes(self.img[o:o + 32])
            if e[0] == 0:
                break
            if e[0] == 0xE5:
                lfn = []
                continue
            if e[11] == 0x0F:
                lfn.append(e)
                continue
            if e[11] & 0x08:           # volume label
                lfn = []
                continue
            if e[11] & 0x10:
                raise FatError("sub-directories are not supported")
            if lfn:
                name = "".join(bytes(l[1:11] + l[14:26] + l[28:32]).decode("utf-16le")
                               for l in reversed(lfn)).split("\x00")[0].split("\uffff")[0]
            else:
                name = (e[:8].decode("latin1").strip() + "." + e[8:11].decode("latin1").strip()).rstrip(".")
            cl = struct.unpack_from("<H", e, 26)[0]
            size = struct.unpack_from("<I", e, 28)[0]
            out.append({"off": o, "name": name, "cluster": cl, "size": size})
            lfn = []
        return out

    def chain(self, cl):
        out = []
        while 2 <= cl < (0xFF0 if self.fat12 else 0xFFF0) and len(out) <= self.nclusters:
            out.append(cl)
            cl = self._fat_get(cl)
        return out

    def read(self, ent):
        data = bytearray()
        for cl in self.chain(ent["cluster"]):
            p = self.data_off + (cl - 2) * self.clsz
            data += self.img[p:p + self.clsz]
        return bytes(data[:ent["size"]])

    def files(self):
        return {e["name"]: self.read(e) for e in self.entries()}

    # --- template / write ------------------------------------------------
    def template(self):
        """Image with the bytes of every file zeroed. Slack after the end of a file (unused tail
        of its last cluster) is preserved so an unchanged volume round-trips byte for byte."""
        t = bytearray(self.img)
        for e in self.entries():
            left = e["size"]
            for cl in self.chain(e["cluster"]):
                n = min(left, self.clsz)
                p = self.data_off + (cl - 2) * self.clsz
                t[p:p + n] = b"\x00" * n
                left -= n
        return bytes(t)

    @staticmethod
    def _ncl(size, clsz):
        return (size + clsz - 1) // clsz

    def write(self, new_files: dict):
        """Return a new image with contents replaced by new_files {name: bytes}.

        If the cluster count of every file is unchanged the data is rewritten in place and the
        FAT is left alone (byte-exact roundtrip for unchanged volumes).  Otherwise every file
        is laid out contiguously and both FAT copies are regenerated.
        """
        ents = self.entries()
        names = [e["name"] for e in ents]
        extra = set(new_files) - set(names)
        if extra:
            raise FatError(f"new files cannot be added, only replaced: {sorted(extra)}")
        data = {e["name"]: new_files.get(e["name"], None) for e in ents}
        for e in ents:
            if data[e["name"]] is None:
                data[e["name"]] = self.read(e)
        same = all(self._ncl(len(data[e["name"]]), self.clsz) == len(self.chain(e["cluster"])) for e in ents)
        img = bytearray(self.img)
        if same:
            for e in ents:
                d = data[e["name"]]
                chain = self.chain(e["cluster"])
                old = e["size"]
                for i, cl in enumerate(chain):
                    p = self.data_off + (cl - 2) * self.clsz
                    chunk = d[i * self.clsz:(i + 1) * self.clsz]
                    img[p:p + len(chunk)] = chunk
                    # bytes after the new end of file: zero them only if the file got shorter
                    if len(d) < old and len(chunk) < self.clsz:
                        a = max(len(chunk), max(0, len(d) - i * self.clsz))
                        img[p + a:p + self.clsz] = b"\x00" * (self.clsz - a)
                struct.pack_into("<I", img, e["off"] + 28, len(d))
            return bytes(img)
        fat = [0] * (self.nclusters + 2)
        fat[0], fat[1] = self._fat_get(0), self._fat_get(1)
        img[self.data_off:] = b"\x00" * (len(img) - self.data_off)
        cur = 2
        for e in ents:
            d = data[e["name"]]
            n = max(1, self._ncl(len(d), self.clsz))
            if cur + n > self.nclusters + 2:
                raise FatError(f"volume full while writing {e['name']} "
                               f"({sum(len(v) for v in data.values())} bytes of {self.nclusters * self.clsz})")
            p = self.data_off + (cur - 2) * self.clsz
            img[p:p + len(d)] = d
            for j in range(n):
                fat[cur + j] = cur + j + 1
            fat[cur + n - 1] = self._eof()
            struct.pack_into("<H", img, e["off"] + 26, cur)
            struct.pack_into("<H", img, e["off"] + 20, 0)
            struct.pack_into("<I", img, e["off"] + 28, len(d))
            cur += n
        fb = self._fat_bytes(fat)
        for k in range(self.nfats):
            o = self.fat_off + k * self.spf * self.bps
            img[o:o + self.spf * self.bps] = b"\x00" * (self.spf * self.bps)
            img[o:o + len(fb)] = fb
        return bytes(img)
