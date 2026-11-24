# goldberg

**Print "Hello" in the most ridiculous way possible.**

`goldberg.py` takes a string and produces a ridiculously over-engineered Python function
whose only job is to print that string — in the spirit of a
[Rube Goldberg machine](https://en.wikipedia.org/wiki/Rube_Goldberg_machine), where a
simple task is performed through an absurd chain of contraptions. The text is scrambled
through several layers of encoding and encryption, scattered across a dictionary, and
reassembled by code written with look-alike variable names, disguised numbers, hidden
imports and decoy lines that do nothing at all.

It is meant for fun and for **CTF-style puzzles** ("what does this program print?"):
reading the output is easy if you run it, and a satisfying exercise if you don't.

```text
$ python goldberg.py "Welcome to the lab"
def lIIl1l1():
    ββ = lambda γθ: lambda ξ: ξ
    ...                        # 30-40 lines of nonsense
    return OOO0O(...)

lIIl1l1()
$ python goldberg.py "Welcome to the lab" -o puzzle.py && python puzzle.py
Welcome to the lab
```

It can also do the same with a **picture**: give it an image (a logo, for example) and the
generated function prints that image as ASCII art.

## Highlights

- **Different every time.** Run it twice on the same input and you get two completely
  different programs that print exactly the same thing. Each run randomly picks from:
  - **17 byte transforms**, 3–6 per program: XOR with a pseudo-random stream or a key word,
    Vigenère, affine cipher, S-box substitution, bit rotation, positional shifts, byte
    permutation, nibble swap, bit reversal, pair swap, delta and XOR-chain encoding,
    block/full reversal (sometimes via a Y combinator), and zlib/raw-deflate/bz2 compression.
  - **11 text encodings**: base85, ascii85, base64, URL-safe base64, base32, base16, hex,
    rot13-over-base64, quoted-printable, or one huge decimal or hexadecimal integer.
  - **Scattering**: the payload is cut into pieces stored in a shuffled dictionary and put
    back together by an odd ordering rule (by key, by key *as text*, by key modulo n, ...).
  - **Obfuscation**: names made of `lI1`, `O0`, Greek letters, underscores or Latin/Cyrillic
    look-alikes; numbers written as Church numerals, XORs, shifts or `len('xyz')`; strings
    and imports spelled backwards, in hex, rot13 or as character offsets; decoy lines and
    misleading comments.
  - **4 pipeline styles** (reduce, loop, nested calls, composed lambdas) and 4 ways to print.
- **Always correct.** Every generated program is executed before it is returned and must
  print exactly the input (plus a newline), or it is rebuilt.
- **Length you choose.** By default each generated function is **35 lines, give or take
  5** (so 30–40), picked at random per run. Set your own target with `-n/--lines` and the
  allowed spread with `--variation`. Long budgets stack more scrambling steps and decoys.
- **Reproducible on request** with `--seed`.

## Prerequisites

| Requirement | Needed for | Install |
| --- | --- | --- |
| **Python 3.9+** | everything | [python.org](https://www.python.org/downloads/) |
| **Pillow ≥ 10.1** | image mode | `pip install pillow` |
| **NumPy** | image mode, `shape` style (used for logos) | `pip install numpy` |
| pillow-heif *(optional)* | HEIC/HEIF photos (e.g. from iPhones) | `pip install pillow-heif` |
| A monospace TrueType font *(usually already present)* | `shape` style | DejaVu Sans Mono, Menlo, Consolas, Courier New, ... are found automatically |

**Text mode needs nothing beyond the Python standard library.** To install everything for
image mode:

```sh
pip install -r requirements.txt
```

The generated programs themselves only use the standard library, so whoever runs a puzzle
needs nothing but Python.

## Usage: text

```sh
python goldberg.py "Welcome to the lab"            # print the generated code
python goldberg.py "Welcome" -o puzzle.py          # write it to a file
echo "Welcome" | python goldberg.py -              # read the text from stdin
python goldberg.py "Welcome" --seed 42             # same seed -> same program
python goldberg.py "Welcome" --no-verify           # skip the self-check (faster)
python goldberg.py "Welcome" -n 60                 # about 60 lines (55-65)
python goldberg.py "Welcome" -n 20 --variation 0   # exactly 20 lines
python goldberg.py "Welcome" -n 150 --variation 25 # anywhere from 125 to 175 lines
```

### Program length

| Option | Meaning |
| --- | --- |
| `-n N`, `--lines N` | Target length of the generated function, counting the `def` line. Default **35**. |
| `--variation V` | How far each machine may land from the target: anywhere in N−V to N+V. Default **5**; `0` means exactly N lines. N+V may be at most 10,000. |

Every program is checked against this range before it is returned. Small budgets get fewer
scrambling steps; large ones get more steps (up to 12) and more decoys. The practical
minimum is about **11 lines**: a working machine needs its imports, at least one scrambling
step, the data and the decoding pipeline. Asking for less gives an error that says how short
it could get, e.g. `cannot fit a machine into 8-8 lines; the shortest built was 10 lines`.

Any Unicode text works, including quotes, backslashes, newlines, accents, CJK and emoji.

## Usage: ASCII art from an image

Supply a reference image with `-i/--image` instead of text. The tool converts the image to
ASCII art, then builds a Rube Goldberg program that prints that art.

```sh
python goldberg.py -i logo.png -o puzzle.py        # logo: shape style, 180 wide
python goldberg.py -i photo.jpg -o puzzle.py       # photo: ascii style, long ramp, 140 wide
python goldberg.py -i logo.jpg -w 220              # wider = more detail
python goldberg.py -i photo.jpg -m braille --dither
```

How the conversion works:

- The **background is detected automatically** from the image border and rendered as blank
  space, whether it is white, black or transparent. Use `--invert` to swap foreground and
  background if the guess is wrong.
- **Empty margins are trimmed**, so the full width is spent on the subject.
- **The style is picked automatically** (`-m auto`, the default). The tool checks whether
  the image has a clear background: at least 75% of its border is one tone, and that tone
  covers at least 30% of the picture.
  - **Logo-like** images (logos, icons, wordmarks, anything on a plain background) get the
    **`shape`** style: every character cell is compared with the actual shapes of the 95
    printable ASCII characters drawn in a monospace font, and the closest match wins. Edges
    become `/`, `_`, `(`, `|` and friends, which keeps outlines crisp and small text legible.
  - **Photo-like** images (no clear background: landscapes, cityscapes, portraits) get the
    **`ascii`** style with the 70-step **`long`** ramp at 140 columns, which keeps the
    photo's shading instead of forcing it into hard shapes.

  The tool prints which it chose, e.g. `auto: photo-like image -> ascii style, long ramp`.
  Any explicit `-m`, `-w` or `--ramp` overrides the automatic choice.
- In image mode the line budget (`-n`, `--variation`) applies to the code only: the art's
  data block counts as one line, however long it is.

| Option | Meaning |
| --- | --- |
| `-i FILE`, `--image FILE` | Reference image to turn into ASCII art. |
| `-w N`, `--width N` | Art width in characters, 1–1000. Defaults: shape 180, photos in auto 140, ascii 80, blocks 120, braille 160. Art is at most 500 rows tall: tall images are narrowed to fit, keeping their shape. |
| `-m auto` *(default)* | `shape` for logo-like images, `ascii` with the `long` ramp for photo-like ones (see above). |
| `-m shape` | Plain ASCII chosen by shape matching. Sharpest; best for logos and text. |
| `-m ascii` | Brightness ramp, one shade per character. |
| `--ramp R` | Ramp for `ascii`, dark to bright: a preset, `short` (`" .:-=+*#%@"`, the default for `-m ascii`) or `long` (70 steps, the default for photos in auto), or your own characters, e.g. `--ramp " .oO@"`. |
| `-m blocks` | Unicode quadrant blocks (`▘▝▀▖▌...`), 2×2 pixels per character. |
| `-m braille` | Unicode braille dots, 2×4 pixels per character. |
| `--font PATH` | Monospace `.ttf`/`.ttc` used for shape matching (default: auto-detected). |
| `--invert` | Swap which tone is treated as the background. |
| `--dither` | Floyd–Steinberg dithering for `blocks`/`braille`; better for photos. |

### Supported image formats

Anything Pillow can read, including:

- **PNG** and **JPEG/JPG** (the most common; fully tested)
- GIF, BMP, TIFF, WebP, ICO, PPM/PGM/PBM, TGA
- AVIF and JPEG 2000 (when your Pillow build includes them, as the standard wheels do)
- HEIC/HEIF, with the optional `pillow-heif` package

Colour, grayscale, palette, 1-bit, CMYK, 16-bit and floating-point images are all handled,
as is transparency (treated as background) and EXIF rotation from phone cameras.
Animated GIF/WebP and multi-page TIFF files use their **first frame**.

**SVG is not supported** (it is a vector format): export it to PNG first.

### Choosing a good image

**In short:** a PNG or JPEG about **800–4000 pixels wide**, showing a **bold, simple,
high-contrast** subject (a logo, icon, wordmark or silhouette), gives the best results.
Intricate images are the main thing that does *not* work well, however large the file.

#### Image size

Measured on a 1400×860 logo in the `shape` style (what `auto` uses for logos) at 180
characters wide.
"Detail kept" compares the art with the art made from the full-quality image.

| Source width | Result | Convert time | Peak memory |
| --- | --- | --- | --- |
| 100–200 px | Too small: shapes break up, upscaled blur (30–55% of detail kept) | ~0.1 s | ~75 MB |
| 400 px | Usable but soft (~85%) | ~0.1 s | ~75 MB |
| **800–4000 px** | **Sweet spot: full detail (95–100%)** | 0.1–0.25 s | 75–125 MB |
| 4000–12000 px JPEG | Works; no extra detail. Decoded at reduced size, so still cheap | ~0.2 s | 90–125 MB |
| 4000–12000 px PNG, TIFF, ... | Works; no extra detail, but slower and memory-hungry | 0.3–1.3 s | 0.1–0.9 GB |
| over ~178 megapixels | Refused (Pillow's decompression-bomb protection) | | |

A typical 12-megapixel phone photo (4032×3024 JPEG) converts in about 0.4 s using about
150 MB. Building the program afterwards takes a few hundredths of a second.

**Rule of thumb: give the source at least 4 pixels per column of art.** That means 720 px
wide for the default 180 columns, 1600 px for `-w 400` and 4000 px for `-w 1000`. Past about
6 pixels per column there is no further gain, so very large originals don't help; scaling
them down first (to 2000–4000 px) does no harm. What matters is pixel dimensions, not file
size in MB.

#### Detail: what survives the conversion

Each character stands for a block of the image. At width `W`, a block is about 1/`W` of
the image's width across and twice that tall: at the default 180 columns, roughly a 5×10 px
patch of a 900 px wide image. Anything much smaller than one block is averaged away. In
practice:

- **Lines and outlines** survive if they are at least about half a block thick (1/360 of
  the image width at the default). Hairlines vanish or turn into specks.
- **Text** needs about 3 rows of characters to be legible, so its capital letters should be
  at least about 6/`W` of the image width tall: **3.3% at 180 columns**, 2.7% at 220, 1.5% at
  400. For example, a logo whose tagline has capitals about 4.5% of the image width reads
  clearly at 180; text around 2% needs about `-w 300`, and anything much smaller is unlikely to
  read at any practical width.
- **Shapes must differ in brightness**, not just colour. Art is monochrome, so a red and a
  green of similar brightness merge into one shape.

#### Intricate images

Excessively intricate images rarely look good as ASCII art, because most of what makes
them interesting is detail smaller than a character. More width helps only up to a point,
and wide art is itself hard to view.

| Works well | Works poorly |
| --- | --- |
| Logos, wordmarks, emblems, icons | Detailed illustrations, engravings, crests with fine linework |
| Silhouettes and bold shapes | Maps, charts and diagrams with small labels |
| Large lettering, signs, slogans | Screenshots of small UI text, documents, spreadsheets |
| Line art with thick strokes | Dense patterns and textures: foliage, fabric, hair, crowds |
| Flat graphics with a plain background | Busy backgrounds, low contrast, many small objects |
| Strongly lit portraits, in moderation (`-m braille --dither`) | Subtle gradients and shading (turn into noise or bands) |

If an image is too intricate:

1. **Crop** to the part that matters; fewer elements means bigger elements.
2. **Simplify** in an image editor: remove the background, raise contrast, or convert to
   black and white; thicken thin lines.
3. **Go wider** (`-w 220`, `-w 300`) if the problem is small text or thin lines, and view
   the result in a wide window.
4. **Try another style:** `auto` already switches photos to `ascii` with the `long` ramp;
   `-m braille --dither` is worth a try too, and `--ramp short` gives a bolder look.
5. **Preview before you share:** generate the program and run it
   (`python goldberg.py -i logo.png -o puzzle.py && python puzzle.py`).

## Limitations

- **Intricate or highly detailed images** lose most of their detail: the art is a grid of
  at most 1000×500 characters (180 wide by default), and anything smaller than a character
  is averaged away. See [Choosing a good image](#choosing-a-good-image).
- **Very high resolution adds nothing.** Images are downscaled to at most 4096 px on the
  longest side as they load (JPEGs straight to about 2048 px), so huge originals cost time
  and memory without improving the art. Images over about 178 megapixels are refused by
  Pillow's built-in decompression-bomb protection, and very large PNG/TIFF files (40+
  megapixels) need 0.5–1 GB of memory to decode.
- **Tall images** (e.g. long screenshots) are narrowed so the art stays within 500 rows.
- **Photographs** convert less cleanly than flat graphics: shading becomes texture. `auto`
  picks the photo-friendly `ascii` style with the `long` ramp; experiment with `-w`,
  `--ramp` and `-m braille --dither`. A photo with a plain, uniform background (e.g. a
  product shot on white) counts as logo-like, so use `-m ascii --ramp long` if the `shape`
  result looks too harsh.
- **Colour is lost.** Art is monochrome; different colours are only distinguished by
  brightness, and two colours of similar brightness merge into one shape.
- **Viewing wide art.** Output wider than your terminal or editor will wrap and look
  scrambled. Widen the window, reduce the font size, or turn off line wrapping.
- **Fonts matter.** `shape` art is tuned to the matching font; it looks best in a similar
  monospace font. `blocks` and `braille` need a font containing those Unicode characters
  and look poor (misaligned, faint) in some viewers and in the legacy Windows console;
  `shape` and `ascii` use plain ASCII and display everywhere.
- **Speed and size.** Image puzzles carry the whole art as compressed data, typically a few
  KB to tens of KB. Generation takes a second or two; widths near 1000 take longer. Very
  long programs are slow to build too: about 2 s for 2,000 lines and 15 s for 10,000 (the
  maximum).
- **Not real security.** The scrambling is designed to be fun to unravel, not to keep a
  secret: running the program reveals the text. Don't use it to hide anything sensitive.

## How it works (briefly)

1. The input is encoded as UTF-8 bytes and pushed through a random chain of reversible
   byte transforms, then a random text encoding.
2. The encoded text is split into pieces and hidden in a dictionary with disguised keys.
3. The decoder for each step is written out as a disguised lambda, in reverse order, and
   wired together with a randomly chosen pipeline style.
4. Decoy lines pad the function to a random length within the line budget (30–40 by
   default).
5. The program is executed in-process; if it does not print exactly the input, it is
   discarded and rebuilt.

## Running the tests

```sh
python -m unittest discover -s tests
```

The suite (46 tests) covers correctness across many seeds and tricky strings, the line
budget (default range, custom and exact budgets, impossible budgets), randomness,
automatic style choice and ramp presets, every byte transform, image formats and bit
depths, transparency, EXIF rotation, large and blank images, error messages, and the
command line. Tests that need an optional codec or package are skipped when it is not
installed.