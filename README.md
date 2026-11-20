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
| **NumPy** | image mode, default `shape` style | `pip install numpy` |
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
| `--variation V` | How far each machine may land from the target: anywhere in N−V to N+V. Default **5**; `0` means exactly N lines. |

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
python goldberg.py -i logo.png -o puzzle.py        # default: 180 characters wide
python goldberg.py -i logo.jpg -w 220              # wider = more detail
python goldberg.py -i photo.jpg -m braille --dither
```

How the conversion works:

- The **background is detected automatically** from the image border and rendered as blank
  space, whether it is white, black or transparent. Use `--invert` to swap foreground and
  background if the guess is wrong.
- **Empty margins are trimmed**, so the full width is spent on the subject.
- In the default **`shape`** style, every character cell of the image is compared with the
  actual shapes of the 95 printable ASCII characters drawn in a monospace font, and the
  closest match wins. Edges become `/`, `_`, `(`, `|` and friends, which keeps outlines crisp
  and small text legible.
- In image mode the line budget (`-n`, `--variation`) applies to the code only: the art's
  data block counts as one line, however long it is.

| Option | Meaning |
| --- | --- |
| `-i FILE`, `--image FILE` | Reference image to turn into ASCII art. |
| `-w N`, `--width N` | Art width in characters, 1–1000. Defaults: shape 180, ascii 80, blocks 120, braille 160. |
| `-m shape` *(default)* | Plain ASCII chosen by shape matching. Sharpest; best for logos and text. |
| `-m ascii` | Classic brightness ramp, one shade per character (`--ramp " .:-=+*#%@"`). |
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

## Limitations

- **Very high resolution or highly detailed images.** The art is at most 1000 characters
  wide, and by default 180, so an image is effectively reduced to roughly 180×100
  "pixels" of character shapes. Fine detail (thin lines, small print, textures, faces in a
  crowd) is lost or turns to noise; bold, high-contrast subjects such as logos, icons and
  large lettering work best. Very large files are downscaled to 4096 px on the longest side
  as they load, and images over about 178 megapixels are refused by Pillow's built-in
  decompression-bomb protection.
- **Photographs** convert less cleanly than flat graphics. Shading becomes texture; try
  `-m braille --dither` or `-m ascii` and experiment with `-w`.
- **Small text in an image** needs width. Text that is tiny relative to the whole picture
  may need `-w 200` or more to become readable, and the result is then that many
  characters wide.
- **Colour is lost.** Art is monochrome; different colours are only distinguished by
  brightness, and two colours of similar brightness merge into one shape.
- **Viewing wide art.** Output wider than your terminal or editor will wrap and look
  scrambled. Widen the window, reduce the font size, or turn off line wrapping.
- **Fonts matter.** `shape` art is tuned to the matching font; it looks best in a similar
  monospace font. `blocks` and `braille` need a font containing those Unicode characters
  and look poor (misaligned, faint) in some viewers and in the legacy Windows console;
  `shape` and `ascii` use plain ASCII and display everywhere.
- **Speed and size.** Image puzzles carry the whole art as compressed data, typically a few
  KB to tens of KB. Generation takes a second or two; widths near 1000 take longer.
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

The suite (39 tests) covers correctness across many seeds and tricky strings, the line
budget (default range, custom and exact budgets, impossible budgets), randomness, every byte transform, image formats and bit depths, transparency, EXIF
rotation, large and blank images, error messages, and the command line. Tests that need an
optional codec or package are skipped when it is not installed.
