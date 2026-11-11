import pytest
from PIL import Image

from fwtool import overlay

pytestmark = pytest.mark.skipif(overlay._pcf(14, "b") is None, reason="Terminus (xfonts-terminus) not installed")

# (cell height, baseline row of the device's own Latin capitals) for the six k2 fonts of the UC5300P
DEVICE_FONTS = [(14, 11), (16, 13), (18, 14), (20, 16), (22, 18), (24, 19)]


@pytest.mark.parametrize("ysize,base", DEVICE_FONTS)
def test_cyrillic_stands_on_the_latin_baseline_and_tails_fit(ysize, base):
    pick = overlay.pick_pixel_font(ysize, base, "b")
    assert pick is not None

    def rows(ch):
        img, w = overlay.render_glyph_pixel(ch, ysize, 4, pick)
        ink = [y for y in range(ysize) if any(img.getpixel((x, y)) == 0 for x in range(img.width))]
        return ink[0], ink[-1]

    assert rows("Н")[1] == base                  # capitals end exactly on the baseline row
    assert rows("е")[1] == base                  # so do lowercase letters
    for ch in "рцщду":
        assert rows(ch)[1] <= ysize - 1          # descenders are not clipped by the cell


def test_glyph_image_is_a_proper_bitmap():
    pick = overlay.pick_pixel_font(16, 13, "b")
    img, w = overlay.render_glyph_pixel("Ж", 16, 3, pick)
    assert img.size == (24, 16) and w == 8            # Terminus 8x16 cell: width = the font's advance
    assert isinstance(img, Image.Image) and img.mode == "1"


@pytest.mark.parametrize("ysize,base", DEVICE_FONTS)
def test_width_is_the_font_advance_and_ink_stays_inside_the_cell(ysize, base):
    """Like the device's own glyphs: side bearings are part of the glyph, width = the font's advance."""
    from PIL import ImageFont
    path, size, _ = pick = overlay.pick_pixel_font(ysize, base, "b")
    f = ImageFont.truetype(path, size)
    for ch in "ЖШЩЫЮмшаеоЁё":
        img, w = overlay.render_glyph_pixel(ch, ysize, 4, pick)
        assert w == int(round(f.getlength(ch)))
        spill = [x for x in range(w, img.width) if any(img.getpixel((x, y)) == 0 for y in range(ysize))]
        assert not spill, f"{ch}: ink beyond the advance"
