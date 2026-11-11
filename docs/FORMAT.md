# UC5300P firmware format (as understood by this project)

All offsets below are *file* offsets of `UC5300P.bin` (15 128 608 bytes for v1.23). Flash offset `N` is stored at file
offset `N + 0x20`.

## Container

```
0x00  "AITS" 01 00 00 00 ...        header (0x20 bytes)
0x10  16 bytes                      MD5("VDRAC999" || file[0x20:])      <- checked by the on-device updater
0x20  MCR2 section #1 header (0x200) ... payload ... padding
      MCR2 section #2
      MCR2 section #3 (application)
      gap, then FAT volumes (type 3 in the table), end of file
```

Section header (`MCR2`, 0x200 bytes, last 4 bytes `MCR2` again):

| off | meaning |
|---|---|
| +0x04 | flags `0x40000001` (bit 30: CRC check enabled) |
| +0x08 | shift (12) - units below are 4 KiB |
| +0x0C | span of the section in units (header + payload + padding) |
| +0x10 | flash offset of the payload in units (file offset = `(v << 12) + 0x20`) |
| +0x14 | payload size in bytes |
| +0x18 | RAM load address of the payload |
| +0xC0.. | (first section only) volume table: `{start_sector, n_sectors, type, n_sectors}` x N, 512-byte sectors |

Section CRC16 is stored at *payload flash offset - 0x1000* (2 bytes, little endian) and is
**CRC-16/MCRF4XX** (poly 0x1021 reflected, init 0xFFFF, no xorout) of the payload. The boot loader computes it with the
SPI-flash DMA engine at every boot; a mismatch prints `CRC check fail`, then the loader spins forever.
The CRC of the application section (3) is what changes whenever strings/fonts are edited.

Sections: 1 = first stage (SRAM, Thumb), 2 = second stage, 3 = application (RAM 0x1000000, ARM, ~8 MB).

## Header MD5

The updater of the application (`SD:\UC5300P.bin`, routine at file offset 0x37B2C0 in v1.23) reads the file in
256-byte chunks and feeds MD5: first the 8 ASCII bytes `VDRAC999`, then `file[0x20:]`. The digest must equal
`file[0x10:0x20]`. `fwtool verify --emulate` runs that very routine in an emulator.

## Application payload

* **String table**: array of 1056 little-endian pointers (RAM) at RAM `0x178A910` (file offset `0x7BE930`), the last 3
  entries are not strings. Strings are NUL-terminated. Table slices: ids 0-193 English UI, 194-216 legacy Korean for the
  18 px font, 218+ Korean UI (menus 683-1052).
* **Encoding**: bytes < 0x80 are ASCII, a byte >= 0xA1 starts a 2-byte *code*; glyph slot = `code - 0xA1A1`
  (so the "code" is a 16-bit big-endian number). The glyph set is a ~400 syllable subset; slots 0-28 hold Latin/Cyrillic/CJK
  glyphs used by language names.
* **Fonts**: 7 emWin-style fonts listed in an array of `{string_table_ptr, font_ptr}` at RAM `0x1789960`
  (heights 18 (old), 14, 16, 18, 20, 22, 24 px). A font holds a chain of `{first, last, charinfo_ptr, next}` ranges;
  `charinfo` = 8 bytes `{xsize, xdist, bytes_per_line, 0, bitmap_ptr}`; bitmaps are 1 bpp, MSB first.
  Ranges: `0x20-0x7E` (ASCII) and `0xA1A1-0xA340` (416 slots; the 18 px font has only `A1A1-A1DC`).
* Voice prompts are **not** in the payload but in the FAT16 volume #2 (`01_SP_xx.mp3`, `chgToDriving.mp3`, ...),
  MP3 44.1 kHz mono. Volume #3 holds `rp_cam.idb` (speed-camera database).

## Volumes

Plain FAT12/FAT16 images (root directory only, long names kept). `fwtool` replaces file contents; when the cluster count
of every file is unchanged it writes in place (FAT untouched), otherwise it lays files out contiguously and rewrites both
FAT copies. Files cannot be added or removed.
