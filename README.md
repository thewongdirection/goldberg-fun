# goldberg

Turn a string — or an image — into a Rube Goldberg Python function that prints it.
Handy for CTF warm-up challenges: *"what does this print?"*

Every run builds a **different** machine at random:

- **Byte scrambling** — 3–6 of 17 transforms: LCG/repeating-key XOR, Vigenère, affine
  cipher, S-box, bit rotation, positional shifts, permutations, nibble swaps, bit reversal,
  pair swaps, delta and XOR-chain encoding, block/full reversal, zlib/raw-deflate/bz2.
- **Text encoding** — one of 11: base85/a85/64/urlsafe/32/16, hex, rot13-over-base64,
  quoted-printable, big decimal or hex integers.
- **Scattering** — the payload is split across a shuffled dict and reassembled by a
  randomly chosen ordering rule (ascending, by `str`, modulo, ...), interleaved or not.
- **Obfuscation** — homoglyph identifiers (Latin/Cyrillic look-alikes, `lI1`, `O0`, Greek,
  underscores), disguised numbers (Church numerals, XOR/shift/mul-add, `len('...')`,
  `ord('x')`), disguised strings and imports, decoy lines and misleading comments.
- **Pipeline** — `reduce`, loop, nested calls or composed lambdas; four ways to print.

The generated function is executed before it is returned, so it is guaranteed to print
exactly the input (plus a newline). It is capped at **40 lines**; in image mode the art's
data block counts as one line.

## Install

```sh
pip install -r requirements.txt   # only needed for image mode
```

Text mode uses only the standard library (Python 3.9+).

## Usage

```sh
python goldberg.py "Welcome to the lab"            # code to stdout
python goldberg.py "Welcome" -o challenge.py       # code to a file
echo "Welcome" | python goldberg.py -              # text from stdin
python goldberg.py "Welcome" --seed 42             # reproducible output

python goldberg.py -i logo.png -o challenge.py     # image -> ASCII art machine
python goldberg.py -i logo.png -w 220              # wider = more detail
```

### Image options

| Option | Meaning |
| --- | --- |
| `-m shape` (default) | Plain ASCII chosen by matching each cell's *shape* against rendered glyphs of a monospace font. Sharpest; keeps small text legible. Needs numpy. |
| `-m ascii` | Classic brightness ramp (`--ramp " .:-=+*#%@"`). |
| `-m blocks` | Unicode quadrant blocks, 2×2 px per character. |
| `-m braille` | Unicode braille, 2×4 px per character (font-dependent rendering). |
| `-w N` | Width in characters (defaults: shape 180, ascii 80, blocks 120, braille 160). |
| `--font PATH` | Monospace `.ttf` for shape matching (default: auto-detects DejaVu Sans Mono, Menlo, Consolas, ...). |
| `--invert` | Swap which tone is treated as background. |
| `--dither` | Floyd–Steinberg dithering for blocks/braille (photos). |

The background is detected from the image border and rendered as blank, and empty margins
are trimmed automatically. View wide output in a terminal or editor with line wrapping off.

## Tests

```sh
python -m unittest discover -s tests
```
