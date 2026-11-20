"""Image input tests: file formats, bit depths, transparency, EXIF, size limits, errors.

Run with: python -m unittest discover -s tests
"""
import contextlib
import io
import os
import pathlib
import sys
import tempfile
import unittest
import warnings

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import goldberg  # noqa: E402

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    np = Image = ImageDraw = None

WIDTH = 40


def _reference() -> "Image.Image":
    """A small logo-like picture: dark shapes on white, asymmetric so rotations show."""
    im = Image.new("RGB", (300, 200), "white")
    d = ImageDraw.Draw(im)
    d.rectangle((30, 30, 120, 170), fill=(200, 30, 0))        # red bar, left
    d.ellipse((160, 40, 270, 150), fill=(40, 40, 40))        # dark disc, right
    d.rectangle((160, 160, 270, 175), fill=(40, 40, 40))      # underline
    return im


def _gray16(im):
    return Image.fromarray(np.asarray(im.convert("L"), np.uint16) * 257)


@unittest.skipIf(Image is None, "Pillow/numpy not installed")
class TestImageInput(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.ref = _reference()
        self.ref_path = self._save("ref.png", lambda p: self.ref.save(p))
        self.expected = goldberg.image_to_ascii(self.ref_path, width=WIDTH)

    def tearDown(self):
        self._tmp.cleanup()

    def _save(self, name, writer):
        path = os.path.join(self.dir, name)
        writer(path)
        return path

    def _render(self, path, **kw):
        return goldberg.image_to_ascii(path, width=WIDTH, **kw)

    def test_reference_is_non_trivial(self):
        self.assertGreater(sum(ch != " " for ch in self.expected), 100)

    def test_lossless_formats_match_png(self):
        writers = {
            "bmp": lambda p: self.ref.save(p),
            "tif": lambda p: self.ref.save(p),
            "gif": lambda p: self.ref.quantize(256).save(p),
            "ppm": lambda p: self.ref.save(p),
            "tga": lambda p: self.ref.save(p),
            "webp": lambda p: self.ref.save(p, lossless=True),
            "ico": lambda p: self.ref.resize((256, 256)).save(p),   # ICO is square
        }
        for ext, writer in writers.items():
            with self.subTest(fmt=ext):
                try:
                    path = self._save(f"img.{ext}", writer)
                except (OSError, KeyError, ValueError) as e:     # codec not built in
                    self.skipTest(f"{ext} not supported by this Pillow: {e}")
                art = self._render(path)
                if ext == "ico":     # different aspect: just require real content
                    self.assertGreater(sum(ch != " " for ch in art), 100)
                else:
                    self.assertEqual(art, self.expected)

    def test_lossy_formats_render(self):
        writers = {
            "jpg": lambda p: self.ref.save(p, quality=90),
            "jpeg": lambda p: self.ref.save(p, "JPEG", quality=75),
            "webp": lambda p: self.ref.save(p, quality=80),
            "avif": lambda p: self.ref.save(p),
            "jp2": lambda p: self.ref.save(p),
        }
        exp_ink = sum(ch != " " for ch in self.expected)
        for ext, writer in writers.items():
            with self.subTest(fmt=ext):
                try:
                    path = self._save(f"lossy.{ext}", writer)
                except (OSError, KeyError, ValueError):
                    continue                                  # codec not available here
                art = self._render(path)
                ink = sum(ch != " " for ch in art)
                self.assertAlmostEqual(ink, exp_ink, delta=exp_ink * 0.15)

    def test_heic_when_plugin_installed(self):
        try:
            import pillow_heif
        except ImportError:
            self.skipTest("pillow-heif not installed")
        pillow_heif.register_heif_opener()
        path = self._save("img.heic", lambda p: self.ref.save(p))
        ink = sum(ch != " " for ch in self._render(path))
        self.assertGreater(ink, 100)

    def test_bit_depths_and_colour_modes(self):
        writers = {
            "16bit.png": lambda p: _gray16(self.ref).save(p),
            "16bit.tif": lambda p: _gray16(self.ref).save(p),
            "float.tif": lambda p: Image.fromarray(
                np.asarray(self.ref.convert("L"), np.float32) / 255).save(p),
            "gray.png": lambda p: self.ref.convert("L").save(p),
            "palette.png": lambda p: self.ref.quantize(64).save(p),
        }
        for name, writer in writers.items():
            with self.subTest(variant=name):
                art = self._render(self._save(name, writer))
                self.assertEqual(art, self.expected, f"{name} renders differently")
        # 1-bit and CMYK change pixel values slightly: require the same picture overall.
        for name, writer in {"1bit.png": lambda p: self.ref.convert("1").save(p),
                             "cmyk.jpg": lambda p: self.ref.convert("CMYK").save(p, quality=95),
                             "cmyk.tif": lambda p: self.ref.convert("CMYK").save(p)}.items():
            with self.subTest(variant=name):
                art = self._render(self._save(name, writer))
                self.assertGreater(sum(ch != " " for ch in art), 100)

    def test_transparency_is_treated_as_background(self):
        rgba = self.ref.convert("RGBA")
        px = rgba.load()
        for y in range(rgba.height):                      # make the white background clear
            for x in range(rgba.width):
                if px[x, y][:3] == (255, 255, 255):
                    px[x, y] = (255, 255, 255, 0)
        variants = {
            "rgba.png": lambda p: rgba.save(p),
            "la.png": lambda p: rgba.convert("LA").save(p),
            "transp.gif": lambda p: rgba.convert("P").save(p, transparency=255),
            "rgba.webp": lambda p: rgba.save(p, lossless=True),
        }
        for name, writer in variants.items():
            with self.subTest(variant=name):
                art = self._render(self._save(name, writer))
                rows = art.split("\n")
                self.assertGreater(sum(ch != " " for ch in art), 100)
                self.assertTrue(rows[0].strip() or rows[-1].strip(), "margins should be trimmed")

    def test_exif_orientation_is_applied(self):
        rotated = self.ref.rotate(90, expand=True)          # what a viewer would show
        expected = goldberg.image_to_ascii(self._save("upright.png", lambda p: rotated.save(p)),
                                           width=WIDTH)
        exif = Image.Exif()
        exif[0x0112] = 8                                    # "rotate 90 CW to display"
        path = self._save("tagged.png", lambda p: self.ref.save(p, exif=exif.tobytes()))
        self.assertEqual(self._render(path), expected)

    def test_multiframe_uses_first_frame(self):
        blank = Image.new("RGB", self.ref.size, "white")
        path = self._save("anim.gif", lambda p: self.ref.quantize(256).save(
            p, save_all=True, append_images=[blank.quantize(256)], duration=100))
        self.assertEqual(self._render(path), self.expected)

    def test_large_image_is_downscaled_on_load(self):
        big = self.ref.resize((9000, 6000))
        path = self._save("big.png", lambda p: big.save(p, compress_level=1))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gray = goldberg._load_gray(path, invert=False)
        self.assertLessEqual(max(gray.size), goldberg.MAX_SOURCE_SIDE)
        self.assertGreater(sum(ch != " " for ch in self._render(path)), 100)

    def test_tall_images_are_capped_in_rows(self):
        """A tall strip at a large width must not explode into thousands of rows."""
        tall = Image.new("RGB", (300, 2000), "white")
        ImageDraw.Draw(tall).rectangle((50, 50, 250, 1900), fill="black")
        path = self._save("tall.png", lambda p: tall.save(p))
        for mode in goldberg.IMAGE_MODES:
            with self.subTest(mode=mode):
                rows = goldberg.image_to_ascii(path, width=goldberg.MAX_WIDTH, mode=mode).split("\n")
                self.assertLessEqual(len(rows), goldberg.MAX_ROWS)
                self.assertGreater(len(rows), goldberg.MAX_ROWS * 0.9)   # uses the room it has
                width = max(map(len, rows))
                self.assertLess(width, 200)                              # narrowed to keep shape
                self.assertGreater(width, 60)

    def test_wide_images_keep_requested_width(self):
        wide = self._save("wide.png", lambda p: self.ref.resize((2000, 300)).save(p))
        rows = goldberg.image_to_ascii(wide, width=300).split("\n")
        self.assertLessEqual(len(rows), goldberg.MAX_ROWS)
        self.assertGreater(max(map(len, rows)), 250)

    def test_tiny_and_blank_images(self):
        tiny = self._save("tiny.png", lambda p: Image.new("RGB", (1, 1), "black").save(p))
        self.assertIsInstance(self._render(tiny), str)
        blank = self._save("blank.png", lambda p: Image.new("RGB", (200, 100), "white").save(p))
        art = self._render(blank)
        self.assertEqual(art.strip(), "")
        code = goldberg.generate(art, seed=1, data_exempt=True)      # still a valid machine
        self.assertEqual(goldberg.run_generated(code), art + "\n")

    def test_all_modes_accept_jpeg_and_png(self):
        jpg = self._save("m.jpg", lambda p: self.ref.save(p, quality=90))
        for mode in goldberg.IMAGE_MODES:
            for path in (self.ref_path, jpg):
                with self.subTest(mode=mode, file=os.path.basename(path)):
                    art = goldberg.image_to_ascii(path, width=WIDTH, mode=mode)
                    self.assertTrue(art.strip())

    def test_banded_shape_matching_equals_single_pass(self):
        whole = goldberg._SHAPE_BAND_CELLS
        try:
            goldberg._SHAPE_BAND_CELLS = 10**9
            single = self._render(self.ref_path)
            goldberg._SHAPE_BAND_CELLS = WIDTH * 2             # two text rows per band
            banded = self._render(self.ref_path)
        finally:
            goldberg._SHAPE_BAND_CELLS = whole
        self.assertEqual(banded, single)

    # -- errors ---------------------------------------------------------------
    def _exit_message(self, fn):
        with self.assertRaises(SystemExit) as cm:
            fn()
        return str(cm.exception)

    def test_missing_file(self):
        msg = self._exit_message(lambda: self._render(os.path.join(self.dir, "nope.png")))
        self.assertIn("not found", msg)

    def test_corrupt_and_truncated_files(self):
        garbage = self._save("bad.png", lambda p: pathlib.Path(p).write_bytes(b"\x89PNG\r\n\x1a\nnope"))
        self.assertIn("cannot read", self._exit_message(lambda: self._render(garbage)))
        good = pathlib.Path(self.ref_path).read_bytes()
        trunc = self._save("trunc.png", lambda p: pathlib.Path(p).write_bytes(good[: len(good) // 2]))
        self.assertIn("could not decode", self._exit_message(lambda: self._render(trunc)))

    def test_svg_gets_a_hint(self):
        svg = self._save("x.svg", lambda p: pathlib.Path(p).write_text(
            "<svg xmlns='http://www.w3.org/2000/svg'/>"))
        self.assertIn("export it to PNG", self._exit_message(lambda: self._render(svg)))

    def test_bad_font_path(self):
        msg = self._exit_message(lambda: self._render(self.ref_path, font="/no/such/font.ttf"))
        self.assertIn("cannot load font", msg)

    def test_width_and_ramp_validation(self):
        for width in (0, -5, goldberg.MAX_WIDTH + 1):
            with self.subTest(width=width), self.assertRaises(ValueError):
                goldberg.image_to_ascii(self.ref_path, width=width)
        with self.assertRaises(ValueError):
            goldberg.image_to_ascii(self.ref_path, mode="ascii", ramp="#")

    def test_cli_reports_bad_width_as_usage_error(self):
        with self.assertRaises(SystemExit) as cm, contextlib.redirect_stderr(io.StringIO()) as err:
            goldberg.main(["--image", self.ref_path, "-w", "0"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("width must be between", err.getvalue())


if __name__ == "__main__":
    unittest.main()
