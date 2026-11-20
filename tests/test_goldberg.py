"""Regression tests for goldberg.py. Run with: python -m unittest discover -s tests"""
import ast
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import goldberg  # noqa: E402

SAMPLES = [
    "Welcome to the Rube Goldberg Computing Laboratory",
    "",
    "a",
    "quote ' \" \\ backslash\nnewline\ttab\r",
    "héllo wörld 世界 🚀",
    "x" * 600,
    "flag{th1s_1s_f1n3}",
]
SEEDS = range(60)


class TestGoldberg(unittest.TestCase):
    def test_prints_exact_text_across_seeds(self):
        for text in SAMPLES:
            for seed in SEEDS:
                with self.subTest(text=text[:20], seed=seed):
                    code = goldberg.generate(text, seed=seed, verify=False)
                    self.assertEqual(goldberg.run_generated(code), text + "\n")

    def test_line_cap(self):
        for text in SAMPLES:
            for seed in SEEDS:
                with self.subTest(text=text[:20], seed=seed):
                    n = goldberg.function_lines(goldberg.generate(text, seed=seed))
                    self.assertLessEqual(n, goldberg.MAX_LINES)
                    self.assertGreaterEqual(n, goldberg.MIN_LINES)

    def test_single_function_and_valid_syntax(self):
        tree = ast.parse(goldberg.generate(SAMPLES[0], seed=1))
        defs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        self.assertEqual(len(defs), 1)

    def test_plaintext_not_in_source(self):
        for seed in SEEDS:
            code = goldberg.generate(SAMPLES[0], seed=seed)
            self.assertNotIn("Welcome", code)
            self.assertNotIn("Goldberg", code)

    def test_seed_is_reproducible(self):
        self.assertEqual(goldberg.generate("hi", seed=7), goldberg.generate("hi", seed=7))

    def test_unseeded_runs_differ(self):
        outs = {goldberg.generate(SAMPLES[0]) for _ in range(10)}
        self.assertEqual(len(outs), 10)

    def test_every_transform_roundtrips(self):
        for name in goldberg.TRANSFORMS:
            for seed in range(15):
                with self.subTest(transform=name, seed=seed):
                    import random
                    c = goldberg.Ctx(random.Random(seed))
                    data = ("payload " * 50 + "✓").encode()
                    enc, dec = goldberg.TRANSFORMS[name](c, data)
                    src = "\n".join(c.prelude + [ln for b in c.blocks for ln in b])
                    ns: dict = {}
                    exec(src, ns)  # noqa: S102
                    self.assertEqual(eval(dec, ns)(enc), data)  # noqa: S307

    def test_image_mode(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as d:
            for bg, fg in (((255, 255, 255, 255), (200, 30, 0, 255)),   # light background
                           ((0, 0, 0, 0), (255, 255, 255, 255))):     # transparent background
                path = os.path.join(d, "img.png")
                im = Image.new("RGBA", (300, 120), bg)
                draw = ImageDraw.Draw(im)
                draw.rectangle((60, 30, 120, 90), fill=fg)      # two shapes with a gap
                draw.rectangle((180, 30, 240, 90), fill=fg)
                im.save(path)
                art = goldberg.image_to_ascii(path, width=60)
                rows = art.split("\n")
                mid = rows[len(rows) // 2]
                # margins trimmed: shapes touch the edges; gap (background) blank;
                # shapes dense - whichever background colour.
                self.assertNotEqual(mid[0], " ")
                self.assertNotEqual(mid[-1], " ")
                self.assertEqual(mid[len(mid) // 2], " ")
                self.assertTrue(all(len(r) <= 60 for r in rows))
                for seed in range(15):
                    code, n = goldberg.generate_with_stats(art, seed=seed, data_exempt=True)
                    self.assertLessEqual(n, goldberg.MAX_LINES)
                    self.assertEqual(goldberg.run_generated(code), art + "\n")

    def test_image_modes_resolution_and_roundtrip(self):
        try:
            from PIL import Image, ImageDraw
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "stripes.png")
            im = Image.new("RGB", (400, 200), "white")
            draw = ImageDraw.Draw(im)
            for x in range(0, 400, 20):                 # 10px stripes, 10px gaps
                draw.rectangle((x, 0, x + 9, 199), fill="black")
            im.save(path)
            for mode in goldberg.IMAGE_MODES:
                for dither in (False, True):
                    with self.subTest(mode=mode, dither=dither):
                        art = goldberg.image_to_ascii(path, width=40, mode=mode, dither=dither)
                        rows = art.split("\n")
                        self.assertTrue(all(len(r) <= 40 for r in rows))
                        code, n = goldberg.generate_with_stats(art, seed=3, data_exempt=True)
                        self.assertLessEqual(n, goldberg.MAX_LINES)
                        self.assertEqual(goldberg.run_generated(code), art + "\n")
            # 20 stripes in 40 chars: braille/blocks have 2 px per char, so each
            # stripe gets 2 pixels -> both on and off dots must appear in a row.
            braille = goldberg.image_to_ascii(path, width=40, mode="braille").split("\n")[1]
            self.assertTrue(any(ch not in ("⣿", "⠀") for ch in braille))
        with self.assertRaises(ValueError):
            goldberg.image_to_ascii(path, mode="nope")

    def test_thin_strokes_survive_downscale(self):
        """Small text: 3px strokes at 1/10 scale must not vanish next to a big solid block."""
        try:
            from PIL import Image, ImageDraw
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow not installed")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "thin.png")
            im = Image.new("RGB", (800, 400), "white")
            draw = ImageDraw.Draw(im)
            draw.rectangle((0, 0, 399, 399), fill="black")          # big solid region
            for x in range(440, 800, 40):                           # thin 3px strokes
                draw.rectangle((x, 40, x + 2, 360), fill="black")
            im.save(path)
            art = goldberg.image_to_ascii(path, width=40, mode="braille")
            right = "".join(row[22:] for row in art.split("\n")[2:-2])
            self.assertTrue(any(ch not in (" ", "⠀") for ch in right),
                            "thin strokes were dropped")

    def test_shape_mode_reads_back_rendered_text(self):
        """Text drawn in the matching font, one glyph per cell, must be recognised exactly."""
        try:
            from PIL import Image, ImageDraw
            __import__("numpy")
        except ImportError:  # pragma: no cover
            self.skipTest("Pillow/numpy not installed")
        word = "Th3 qu1ck /brown|fox\\ jumps_over"
        ch = goldberg._SHAPE_CELL_H
        font, cw = goldberg._mono_font(None, ch)
        a, d = font.getmetrics()
        im = Image.new("L", (cw * len(word), ch), 0)
        draw = ImageDraw.Draw(im)
        for i, c in enumerate(word):          # bright text on dark = "subject"
            draw.text((i * cw, ch - (a + d)), c, fill=255, font=font)
        out = goldberg._render_shape(im, len(word), None)
        self.assertEqual(out, [word])

    def test_invalid_unicode_text_is_rejected_cleanly(self):
        with self.assertRaises(ValueError) as cm:
            goldberg.generate("bad \ud800 surrogate", seed=1)
        self.assertIn("not valid Unicode", str(cm.exception))

    def test_y_combinator_reverse_has_stack_headroom(self):
        """The recursive reversal must survive being called from deep inside other code."""
        import random
        data = bytes(range(goldberg._Y_MAX_BYTES - 1))
        for seed in range(200):                  # find a build that picks the Y variant
            c = goldberg.Ctx(random.Random(seed))
            enc, dec = goldberg.t_reverse(c, data)
            if c._y and c._y in dec:
                break
        else:
            self.fail("Y-combinator variant never chosen")
        ns: dict = {}
        exec("\n".join(c.prelude), ns)  # noqa: S102
        fn = eval(dec, ns)  # noqa: S307

        def deep(n):
            return deep(n - 1) if n else fn(enc)
        self.assertEqual(deep(600), data)

    def test_cli_stdin_and_non_utf8_console(self):
        script = os.path.join(os.path.dirname(__file__), "..", "goldberg.py")
        env = {**os.environ, "PYTHONIOENCODING": "ascii"}      # e.g. a legacy Windows console
        res = subprocess.run([sys.executable, script, "-", "--seed", "3"], input=b"stdin text\n",
                             capture_output=True, env=env)
        self.assertEqual(res.returncode, 0, res.stderr.decode(errors="replace"))
        out = goldberg.run_generated(res.stdout.decode("utf-8"))
        self.assertEqual(out, "stdin text\n")

    def test_cli_requires_exactly_one_input(self):
        for argv in (["hi", "--image", "x.png"], []):
            with self.subTest(argv=argv), self.assertRaises(SystemExit), \
                    contextlib.redirect_stderr(io.StringIO()):
                goldberg.main(argv)

    def test_cli_writes_runnable_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "c.py")
            script = os.path.join(os.path.dirname(__file__), "..", "goldberg.py")
            subprocess.run([sys.executable, script, "CLI test ✓", "-o", out], check=True)
            res = subprocess.run([sys.executable, "-I", out], capture_output=True, check=True,
                                 env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            self.assertEqual(res.stdout.decode("utf-8").replace("\r\n", "\n"), "CLI test ✓\n")


if __name__ == "__main__":
    unittest.main()
