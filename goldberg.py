#!/usr/bin/env python3
"""goldberg.py - turn a string into a Rube Goldberg Python function that prints it.

Given a string (or an image, rendered as ASCII art), build a deliberately absurd,
randomly constructed Python function whose only job is to print it.

Every run picks a fresh random combination of:
  * byte transforms   (ciphers, permutations, bit tricks, compression, ...)
  * a text encoding   (base85/64/32/16, big integers, rot13-over-base64, ...)
  * chunking          (scattered across a dict with weird ordering rules)
  * obfuscation       (homoglyph names, disguised numbers and strings,
                       hidden imports, Church numerals, misleading comments)
  * pipeline style    (reduce, loop, nested calls, composed lambdas)

The generated function is executed before it is returned, so the output
is guaranteed to print exactly the input (plus a newline).

Usage:
    python goldberg.py "Hello, world"            # code to stdout
    python goldberg.py "Hello" -o challenge.py   # code to a file
    echo "Hello" | python goldberg.py -          # text from stdin
    python goldberg.py "Hello" --seed 42         # reproducible output
    python goldberg.py "Hello" -n 60 --variation 0   # exactly 60 lines
    python goldberg.py --image cat.png -w 60     # print an image as ASCII art
    python goldberg.py -i logo.png -w 200        # wider = more detail (shape-matched ASCII)
    python goldberg.py -i photo.jpg              # photos: auto-picks ascii + long ramp
    python goldberg.py -i logo.png -m braille    # Unicode braille dots instead

The generated function is 35 +/- 5 lines long by default; choose your own with
-n/--lines and --variation. In image mode the (compressed, encoded) art data
block counts as a single line however long it is.

Image mode needs Pillow and numpy; any format Pillow reads works (PNG, JPEG, GIF, BMP,
TIFF, WebP, ...), plus HEIC/HEIF when the optional pillow-heif package is installed.
See README.md for options and limitations.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import builtins
import bz2
import codecs
import contextlib
import io
import keyword
import random
import string
import sys
import zlib
from dataclasses import dataclass, field
from typing import Callable

DEFAULT_LINES = 35      # target length of the generated function (def line + body)
DEFAULT_VARIATION = 5   # each machine lands somewhere in DEFAULT_LINES +/- this
MAX_ATTEMPTS = 120      # re-rolls before giving up on fitting the line budget
MAX_LINES_LIMIT = 10_000  # largest budget accepted (10k lines already takes ~15 s)


def line_range(lines: int = DEFAULT_LINES, variation: int = DEFAULT_VARIATION) -> tuple[int, int]:
    """The (min, max) function length allowed for a target and a +/- variation."""
    if lines < 1:
        raise ValueError("lines must be at least 1")
    if variation < 0:
        raise ValueError("variation must be 0 or more")
    if lines + variation > MAX_LINES_LIMIT:
        raise ValueError(f"lines + variation must be at most {MAX_LINES_LIMIT}")
    return max(1, lines - variation), lines + variation


_FRUGAL_BELOW = 20      # budgets under this many lines skip optional extras


def _transform_count(rng: random.Random, max_lines: int) -> int:
    """How many byte transforms to stack: fewer for tight budgets, more for roomy ones."""
    if max_lines < 20:
        return rng.randint(1, 2)
    if max_lines < 28:
        return rng.randint(2, 4)
    if max_lines <= 50:
        return rng.randint(3, 6)
    return rng.randint(4, min(12, 6 + (max_lines - 50) // 15))


# ---------------------------------------------------------------------------
# Identifier generation: names that are valid, unique, and miserable to read.
# ---------------------------------------------------------------------------
_NAME_STYLES: dict[str, tuple[str, str, int, int]] = {
    # style: (first-char alphabet, rest alphabet, min len, max len)
    "barcode": ("lI", "lI1", 5, 9),
    "zeroes": ("O", "O0", 5, 9),
    "homoglyph": ("aаeеoоcсpр", "aаeеoоcсpрxх", 3, 6),   # Latin/Cyrillic look-alikes
    "greek": ("αβγδεζηθικλμνξπρστυφχψω", "αβγδεζηθικλμνξπρστυφχψω", 1, 3),
    "underscore": ("_", "_", 2, 7),
}
_RESERVED = set(keyword.kwlist) | set(dir(builtins))


class NameGen:
    def __init__(self, rng: random.Random):
        self._rng = rng
        self._styles = rng.sample(sorted(_NAME_STYLES), k=rng.randint(1, 2))
        self._used: set[str] = set()

    def __call__(self) -> str:
        for attempt in range(10_000):
            # Small styles (e.g. underscores) can run dry; widen to every style if so.
            pool = self._styles if attempt < 200 else sorted(_NAME_STYLES)
            first, rest, lo, hi = _NAME_STYLES[self._rng.choice(pool)]
            n = self._rng.randint(lo, hi)
            name = self._rng.choice(first) + "".join(self._rng.choice(rest) for _ in range(n - 1))
            if name.isidentifier() and name not in _RESERVED and name not in self._used:
                self._used.add(name)
                return name
        raise RuntimeError("ran out of identifiers")  # pragma: no cover


# ---------------------------------------------------------------------------
# Context: shared obfuscation helpers + accumulated setup code.
# ---------------------------------------------------------------------------
@dataclass
class Ctx:
    rng: random.Random
    frugal: bool = False          # tight line budget: skip optional multi-line extras
    name: NameGen = field(init=False)
    blocks: list[list[str]] = field(default_factory=list)   # shuffleable setup blocks
    prelude: list[str] = field(default_factory=list)        # must run first
    church: tuple[str, str, str] | None = None
    _mods: dict[str, str] = field(default_factory=dict)
    _y: str | None = None
    data_block: list[str] = field(default_factory=list)     # the payload dict lines

    def __post_init__(self) -> None:
        self.name = NameGen(self.rng)
        if not self.frugal and self.rng.random() < 0.45:     # Church numerals: 3 lines
            z, s, u = self.name(), self.name(), self.name()
            f, x, n, k = self.name(), self.name(), self.name(), self.name()
            self.church = (z, s, u)
            self.prelude += [
                f"{z} = lambda {f}: lambda {x}: {x}",
                f"{s} = lambda {n}: lambda {f}: lambda {x}: {f}({n}({f})({x}))",
                f"{u} = lambda {n}: {n}(lambda {k}: -~{k})(0)",
            ]

    # -- numbers ------------------------------------------------------------
    def num(self, n: int, depth: int = 0) -> str:
        """An expression that evaluates to the int n, disguised."""
        r = self.rng
        if n < 0:
            return f"(-{self.num(-n, depth)})"
        opts = ["dec", "hex", "oct"]
        if n < 4096:
            opts.append("bin")
        if n <= 12:
            opts.append("len")
        if 33 <= n < 127:
            opts.append("ord")
        if self.church and n <= 7:
            opts += ["church"] * 2
        if depth == 0:
            opts += ["muladd", "xor", "tilde", "shift"] * 2
        pick = r.choice(opts)
        sub = lambda v: self.num(v, depth + 1)  # noqa: E731
        if pick == "hex":
            return r.choice([hex(n), hex(n).upper().replace("X", "x")])
        if pick == "oct":
            return oct(n)
        if pick == "bin":
            return bin(n)
        if pick == "len":
            return f"len({''.join(r.choice(string.ascii_letters) for _ in range(n))!r})"
        if pick == "ord":
            return f"ord({chr(n)!r})"
        if pick == "church":
            z, s, u = self.church  # type: ignore[misc]
            succ = "(".join([s] * n) + "(" if n else ""
            return f"{u}({succ}{z}{')' * n})"
        if pick == "muladd" and n > 1:
            a = r.randint(2, 97)
            q, m = divmod(n, a)
            return f"({sub(q)} * {sub(a)} + {sub(m)})"
        if pick == "xor":
            k = r.randrange(1, 1 << max(n.bit_length(), 4))
            return f"({sub(n ^ k)} ^ {sub(k)})"
        if pick == "tilde":
            return f"(-~{sub(n - 1)})" if n > 0 else f"(~-{sub(n + 1)})"
        if pick == "shift" and n > 1:
            k = r.randint(1, 4)
            return f"({sub(n >> k)} << {k} | {sub(n & ((1 << k) - 1))})"
        return str(n)

    # -- strings ------------------------------------------------------------
    def text(self, s: str) -> str:
        """An expression that evaluates to the str s, disguised."""
        if not s:
            return self.rng.choice(["''", "str()", "''.join(())"])
        r = self.rng
        codes = [ord(c) for c in s]
        pick = r.choice(["rev", "chrmap", "fromhex", "percent", "delta", "rot13"])
        if pick == "rev":
            return f"{s[::-1]!r}[::-1]"
        if pick == "chrmap":
            return f"''.join(map(chr, ({', '.join(map(hex, codes))},)))"
        if pick == "fromhex":
            return f"bytes.fromhex({s.encode().hex()!r}).decode()"
        if pick == "percent":
            return f"('%c' * {len(s)} % ({', '.join(map(str, codes))},))"
        if pick == "delta":
            base = r.randint(32, 120)
            v, d = self.name(), ", ".join(str(c - base) for c in codes)
            return f"''.join(chr({base} + {v}) for {v} in ({d},))"
        return f"__import__('codecs').decode({codecs.encode(s, 'rot13')!r}, 'rot13')"

    # -- modules / attributes / builtins ----------------------------------
    def mod(self, m: str) -> str:
        if m not in self._mods:
            v = self.name()
            t = self.text(m)
            expr = self.rng.choice([
                f"__import__({t})",
                f"vars(__import__({self.text('builtins')}))[{self.text('__import__')}]({t})",
                f"__import__({self.text('importlib')}).import_module({t})",
                f"getattr(__import__({self.text('builtins')}), {self.text('__import__')})({t})",
            ])
            self._mods[m] = v
            self.prelude.append(f"{v} = {expr}")
        return self._mods[m]

    def attr(self, obj: str, a: str) -> str:
        return self.rng.choice([f"{obj}.{a}", f"getattr({obj}, {self.text(a)})"])

    def builtin(self, b: str) -> str:
        return self.rng.choice([
            b,
            f"getattr({self.mod('builtins')}, {self.text(b)})",
            f"vars({self.mod('builtins')})[{self.text(b)}]",
        ])

    def y_combinator(self) -> str:
        if self._y is None:
            self._y = self.name()
            f, x, y, a = self.name(), self.name(), self.name(), self.name()
            # prelude, not a shuffled block: nested-style gears call it at definition time
            self.prelude.append(f"{self._y} = lambda {f}: (lambda {x}: {x}({x}))"
                                f"(lambda {y}: {f}(lambda *{a}: {y}({y})(*{a})))")
        return self._y


# ---------------------------------------------------------------------------
# Byte transforms. Each encodes `data` and returns (encoded, decoder_expr),
# where decoder_expr is a Python expression for a bytes -> bytes callable.
# ---------------------------------------------------------------------------
Transform = Callable[[Ctx, bytes], "tuple[bytes, str]"]


def _lcg(seed: int, a: int, c: int, bits: int, shift: int):
    s, mask = seed, (1 << bits) - 1
    while True:
        s = (s * a + c) & mask
        yield s >> shift & 255


def t_xor_lcg(c: Ctx, data: bytes) -> tuple[bytes, str]:
    r = c.rng
    a, inc = r.randrange(1 << 20, 1 << 31) | 1, r.randrange(1, 1 << 16)
    bits = r.choice([31, 32])
    shift, seed = r.randrange(8, bits - 8), r.randrange(1, 1 << bits)
    enc = bytes(x ^ k for x, k in zip(data, _lcg(seed, a, inc, bits, shift)))
    fn, s, b, x, y = (c.name() for _ in range(5))
    c.blocks.append([
        f"def {fn}({s}={c.num(seed)}):",
        f"    while {c.num(1)}:",
        f"        {s} = ({s} * {c.num(a)} + {c.num(inc)}) & {c.num((1 << bits) - 1)}",
        f"        yield {s} >> {c.num(shift)} & {c.num(255)}",
    ])
    return enc, r.choice([
        f"lambda {b}: bytes(map(int.__xor__, {b}, {fn}()))",
        f"lambda {b}: bytes({x} ^ {y} for {x}, {y} in zip({b}, {fn}()))",
    ])


def t_xor_word(c: Ctx, data: bytes) -> tuple[bytes, str]:
    r = c.rng
    key = bytes(r.choice(string.ascii_letters.encode()) for _ in range(r.randint(3, 9)))
    enc = bytes(x ^ key[i % len(key)] for i, x in enumerate(data))
    b, x, y = c.name(), c.name(), c.name()
    cyc = c.attr(c.mod("itertools"), "cycle")
    return enc, f"lambda {b}: bytes({x} ^ {y} for {x}, {y} in zip({b}, {cyc}({c.text(key.decode())}.encode())))"


def t_vigenere(c: Ctx, data: bytes) -> tuple[bytes, str]:
    r = c.rng
    key = [r.randrange(256) for _ in range(r.randint(3, 7))]
    enc = bytes((x + key[i % len(key)]) & 255 for i, x in enumerate(data))
    b, i, x = c.name(), c.name(), c.name()
    k = "(" + ", ".join(c.num(v) for v in key) + ",)"
    return enc, (f"lambda {b}: bytes(({x} - {k}[{i} % {c.num(len(key))}]) % {c.num(256)} "
                 f"for {i}, {x} in enumerate({b}))")


def t_affine(c: Ctx, data: bytes) -> tuple[bytes, str]:
    m, k = c.rng.randrange(3, 256, 2), c.rng.randrange(256)
    enc = bytes((x * m + k) & 255 for x in data)
    b, x = c.name(), c.name()
    return enc, (f"lambda {b}: bytes(({x} - {c.num(k)}) * {c.num(pow(m, -1, 256))} "
                 f"& {c.num(255)} for {x} in {b})")


def t_sbox(c: Ctx, data: bytes) -> tuple[bytes, str]:
    r = c.rng
    a, k, mod = r.randrange(1, 1 << 16), r.randrange(1 << 16), r.choice([257, 263, 509, 521, 1021])
    sbox = sorted(range(256), key=lambda i: (i * a + k) % mod)
    enc = bytes(sbox[x] for x in data)
    sv, i, b, x = c.name(), c.name(), c.name(), c.name()
    c.blocks.append([f"{sv} = sorted(range({c.num(256)}), key=lambda {i}: "
                     f"({i} * {c.num(a)} + {c.num(k)}) % {c.num(mod)})"])
    return enc, r.choice([
        f"lambda {b}: bytes(map({sv}.index, {b}))",
        f"lambda {b}: bytes({sv}.index({x}) for {x} in {b})",
    ])


def t_rotate_bits(c: Ctx, data: bytes) -> tuple[bytes, str]:
    k = c.rng.randint(1, 7)
    enc = bytes((x << k | x >> (8 - k)) & 255 for x in data)
    b, x = c.name(), c.name()
    return enc, f"lambda {b}: bytes(({x} >> {c.num(k)} | {x} << {c.num(8 - k)}) & {c.num(255)} for {x} in {b})"


def t_positional(c: Ctx, data: bytes) -> tuple[bytes, str]:
    k, k0 = c.rng.randrange(1, 256), c.rng.randrange(256)
    enc = bytes((x + i * k + k0) % 256 for i, x in enumerate(data))
    b, i, x = c.name(), c.name(), c.name()
    return enc, (f"lambda {b}: bytes(({x} - {i} * {c.num(k)} - {c.num(k0)}) % {c.num(256)} "
                 f"for {i}, {x} in enumerate({b}))")


def t_permute(c: Ctx, data: bytes) -> tuple[bytes, str]:
    r = c.rng
    a, k, mod = r.randrange(1, 1 << 16) | 1, r.randrange(1 << 16), r.choice([1009, 2003, 4001, 7919])
    perm = sorted(range(len(data)), key=lambda i: (i * a + k) % mod)
    enc = bytes(data[j] for j in perm)
    b, i, x, u = c.name(), c.name(), c.name(), c.name()
    return enc, (f"lambda {b}: bytes({x} for {u}, {x} in sorted(zip(sorted(range(len({b})), "
                 f"key=lambda {i}: ({i} * {c.num(a)} + {c.num(k)}) % {c.num(mod)}), {b})))")


def t_nibble(c: Ctx, data: bytes) -> tuple[bytes, str]:
    b, x = c.name(), c.name()
    return bytes((x << 4 | x >> 4) & 255 for x in data), \
        f"lambda {b}: bytes(({x} << {c.num(4)} | {x} >> {c.num(4)}) & {c.num(255)} for {x} in {b})"


def t_invert(c: Ctx, data: bytes) -> tuple[bytes, str]:
    b, x = c.name(), c.name()
    return bytes(255 - x for x in data), c.rng.choice([
        f"lambda {b}: bytes(~{x} & {c.num(255)} for {x} in {b})",
        f"lambda {b}: bytes({c.num(255)} - {x} for {x} in {b})",
        f"lambda {b}: bytes({x} ^ {c.num(255)} for {x} in {b})",
    ])


def t_bitreverse(c: Ctx, data: bytes) -> tuple[bytes, str]:
    b, x = c.name(), c.name()
    return bytes(int(f"{x:08b}"[::-1], 2) for x in data), \
        f"lambda {b}: bytes(int(f'{{{x}:08b}}'[::-1], {c.num(2)}) for {x} in {b})"


def t_pairswap(c: Ctx, data: bytes) -> tuple[bytes, str]:
    n = len(data)
    enc = bytes(data[i ^ 1] if i ^ 1 < n else data[i] for i in range(n))
    b, i = c.name(), c.name()
    return enc, (f"lambda {b}: bytes({b}[{i} ^ {c.num(1)}] if {i} ^ {c.num(1)} < len({b}) "
                 f"else {b}[{i}] for {i} in range(len({b})))")


def t_delta(c: Ctx, data: bytes) -> tuple[bytes, str]:
    enc = bytes((data[i] - (data[i - 1] if i else 0)) & 255 for i in range(len(data)))
    b, x = c.name(), c.name()
    acc = c.attr(c.mod("itertools"), "accumulate")
    return enc, f"lambda {b}: bytes({x} & {c.num(255)} for {x} in {acc}({b}))"


def t_xorchain(c: Ctx, data: bytes) -> tuple[bytes, str]:
    out, prev = bytearray(), 0
    for x in data:
        prev ^= x
        out.append(prev)
    b, x, y = c.name(), c.name(), c.name()
    return bytes(out), f"lambda {b}: bytes({x} ^ {y} for {x}, {y} in zip({b}, bytes({c.num(1)}) + {b}))"


_Y_MAX_BYTES = 120


def t_reverse(c: Ctx, data: bytes) -> tuple[bytes, str]:
    b, a, x, rr = c.name(), c.name(), c.name(), c.name()
    opts = [
        f"lambda {b}: {b}[::-1]",
        f"lambda {b}: bytes(reversed({b}))",
        f"lambda {b}: {c.attr(c.mod('functools'), 'reduce')}(lambda {a}, {x}: bytes(({x},)) + {a}, {b}, b'')",
    ]
    if len(data) < _Y_MAX_BYTES:   # ~3 stack frames per byte: keep well under the limit
        y = c.y_combinator()
        opts.append(f"{y}(lambda {rr}: lambda {b}, {a}=b'': {a} if not {b} else {rr}({b}[1:], {b}[:1] + {a}))")
    return data[::-1], c.rng.choice(opts)


def t_blockreverse(c: Ctx, data: bytes) -> tuple[bytes, str]:
    k = c.rng.randint(2, 6)
    enc = b"".join(data[i:i + k][::-1] for i in range(0, len(data), k))
    b, i = c.name(), c.name()
    return enc, (f"lambda {b}: b''.join({b}[{i}:{i} + {c.num(k)}][::-1] "
                 f"for {i} in range(0, len({b}), {c.num(k)}))")


def t_compress(c: Ctx, data: bytes) -> tuple[bytes, str]:
    r, b = c.rng, c.name()
    kind = r.choice(["zlib", "rawdeflate", "bz2"] if len(data) > 200 else ["zlib", "rawdeflate"])
    if kind == "zlib":
        return zlib.compress(data, 9), c.attr(c.mod("zlib"), "decompress")
    if kind == "bz2":
        return bz2.compress(data, 9), c.attr(c.mod("bz2"), "decompress")
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    return co.compress(data) + co.flush(), \
        f"lambda {b}: {c.attr(c.mod('zlib'), 'decompress')}({b}, {c.num(-15)})"


TRANSFORMS: dict[str, Transform] = {
    f.__name__[2:]: f for f in (
        t_xor_lcg, t_xor_word, t_vigenere, t_affine, t_sbox, t_rotate_bits, t_positional,
        t_permute, t_nibble, t_invert, t_bitreverse, t_pairswap, t_delta, t_xorchain,
        t_reverse, t_blockreverse, t_compress,
    )
}
# Transforms that actually hide byte values (at least one is always used).
_KEYED = ("xor_lcg", "xor_word", "vigenere", "affine", "sbox", "positional")


# ---------------------------------------------------------------------------
# Text encodings: bytes -> printable str, plus an expression decoding it back.
# ---------------------------------------------------------------------------
def _serialize(c: Ctx, data: bytes) -> tuple[str, str]:
    r, t = c.rng, c.name()
    b64 = lambda fn: c.attr(c.mod("base64"), fn)  # noqa: E731
    kinds = ["b85", "a85", "b64", "urlsafe", "b32", "b16", "fromhex", "rot13b64", "qp"]
    if data:
        kinds.append("hexint")
    if 0 < len(data) < 1500:    # str(int) is capped at 4300 decimal digits
        kinds.append("bigint")
    kind = r.choice(kinds)
    if kind == "b85":
        return base64.b85encode(data).decode(), b64("b85decode")
    if kind == "a85":
        return base64.a85encode(data).decode(), b64("a85decode")
    if kind == "b64":
        return base64.b64encode(data).decode(), b64("b64decode")
    if kind == "urlsafe":
        return base64.urlsafe_b64encode(data).decode(), b64("urlsafe_b64decode")
    if kind == "b32":
        return base64.b32encode(data).decode(), b64("b32decode")
    if kind == "b16":
        return base64.b16encode(data).decode(), b64("b16decode")
    if kind == "fromhex":
        return data.hex(), "bytes.fromhex"
    if kind == "rot13b64":
        txt = codecs.encode(base64.b64encode(data).decode(), "rot13")
        dec = c.attr(c.mod("codecs"), "decode")
        return txt, f"lambda {t}: {b64('b64decode')}({dec}({t}, {c.text('rot13')}))"
    if kind == "qp":
        return binascii.b2a_qp(data, istext=False).decode(), \
            f"lambda {t}: {c.attr(c.mod('binascii'), 'a2b_qp')}({t})"
    order = r.choice(["big", "little"])
    n = int.from_bytes(data, order)
    if kind == "bigint":
        return str(n), f"lambda {t}: int({t}).to_bytes({c.num(len(data))}, {c.text(order)})"
    return format(n, "x"), f"lambda {t}: int({t}, {c.num(16)}).to_bytes({c.num(len(data))}, {c.text(order)})"


def _scatter(c: Ctx, text: str, width: int) -> str:
    """Split text into chunks in a shuffled dict; return the reassembly expression."""
    r = c.rng
    k = max(1, min(len(text), r.randint(2, 9)))
    interleave = r.random() < 0.5
    chunks = [text[i::k] for i in range(k)] if interleave else \
        [text[len(text) * i // k: len(text) * (i + 1) // k] for i in range(k)]
    keys = r.sample(range(1, 10_000), k)
    rule = r.choice(["asc", "desc", "str", "strdesc", "mod"])
    m = r.randint(11, 97)
    sort_key = {"asc": lambda v: v, "desc": lambda v: -v, "str": str,
                "strdesc": str, "mod": lambda v: (v % m, v)}[rule]
    ordered = sorted(keys, key=sort_key, reverse=rule == "strdesc")
    pairs = list(zip(ordered, chunks))
    r.shuffle(pairs)

    d, kv = c.name(), c.name()
    items = [f"{c.num(key)}: {chunk!r}" for key, chunk in pairs]
    lines, cur = [], f"{d} = {{"
    for it in items:
        if len(cur) + len(it) > width and not cur.endswith("{"):
            lines.append(cur.rstrip())
            cur = "    "
        cur += it + ", "
    lines.append(cur.rstrip(", ") + "}")
    c.blocks.append(lines)
    c.data_block = lines

    sorter = {
        "asc": f"sorted({d})",
        "desc": f"sorted({d}, reverse={c.num(1)})",
        "str": f"sorted({d}, key=str)",
        "strdesc": f"sorted({d}, key=str, reverse=True)",
        "mod": f"sorted({d}, key=lambda {kv}: ({kv} % {c.num(m)}, {kv}))",
    }[rule]
    cols = f"({d}[{kv}] for {kv} in {sorter})"
    if interleave:
        zl = c.attr(c.mod("itertools"), "zip_longest")
        return f"''.join(map(''.join, {zl}(*{cols}, fillvalue='')))"
    return f"''.join{cols}" if r.random() < 0.5 else f"str().join([*{cols}])"


# ---------------------------------------------------------------------------
# Output + pipeline assembly.
# ---------------------------------------------------------------------------
_DECOY_TEXT = ["flag{n0t_th1s_0n3}", "rot13", "try harder", "base64?", "XOR is enough",
               "ctf{almost}", "TODO: remove", "\x48\x49", "hunter2", "0xDEADBEEF"]
_LIES = ["# rot13", "# definitely base64", "# do not touch", "# O(1)", "# returns None",
         "# the flag is not here", "# TODO: remove", "# thread-safe", "# dead code",
         "# trust me", "# load-bearing", "# just a sanity check", "# identity function"]


def _decoy(c: Ctx) -> str:
    r, n, m = c.rng, c.name(), c.name()
    return r.choice([
        f"{n} = lambda *{m}: {m}[{c.num(0)}:{c.num(0)}]",
        f"if {c.num(0)}: {n} = {c.text(r.choice(_DECOY_TEXT))}",
        f"assert {c.num(r.randint(1, 999))}",
        f"{n} = [{m} for {m} in range({c.num(r.randint(5, 40))}) if not {m} % {c.num(r.randint(2, 9))}]",
        f"{n} = {c.text(r.choice(_DECOY_TEXT))}[::{c.num(r.randint(1, 3))}]",
        f"{n} = {{{c.num(r.randint(0, 99))}: {c.text(r.choice(_DECOY_TEXT))}}}.get",
        f"{n} = type({c.text(r.choice(['Gear', 'Lever', 'Pulley', 'Cog']))}, (), {{}})",
    ])


def _output_gear(c: Ctx) -> str:
    s = c.name()
    write = c.attr(c.attr(c.mod("sys"), "stdout"), "write")
    pr = c.builtin("print")
    return c.rng.choice([
        f"lambda {s}: {write}({s} + chr({c.num(10)}))",
        f"lambda {s}: {pr}({s})",
        f"lambda {s}: {pr}(*{s}, sep='')",
        f"lambda {s}: {pr}(end={s} + {c.text(chr(10))})",
    ])


def _str_gear(c: Ctx) -> str:
    b = c.name()
    return c.rng.choice([
        "bytes.decode",
        f"lambda {b}: {b}.decode()",
        f"lambda {b}: str({b}, {c.text('utf-8')})",
        f"lambda {b}: {b}.decode({c.text('utf8')})",
        f"lambda {b}: {c.attr(c.mod('codecs'), 'decode')}({b}, {c.text('utf-8')})",
    ])


def _pipeline(c: Ctx, start: str, gears: list[str]) -> list[str]:
    r, ind = c.rng, "    "
    style = r.choice(["reduce", "loop", "nested", "compose"])
    if style == "nested":
        names = [c.name() for _ in gears]
        c.blocks += [[f"{n} = {g}"] for n, g in zip(names, gears)]
        expr = start
        for n in names:
            expr = f"{n}({expr})"
        return [f"return {expr}"]
    body = [f"{ind}{g}," for g in gears]
    if style == "reduce":
        red, a, g = c.attr(c.mod("functools"), "reduce"), c.name(), c.name()
        return [f"return {red}(lambda {a}, {g}: {g}({a}), ["] + body + [f"], {start})"]
    if style == "compose":
        red, f, g, x = c.attr(c.mod("functools"), "reduce"), c.name(), c.name(), c.name()
        return [f"return {red}(lambda {f}, {g}: lambda {x}: {g}({f}({x})), ["] + body + [f"])({start})"]
    v, g = c.name(), c.name()
    return [f"{v} = {start}", f"for {g} in ("] + body + ["):", f"{ind}{v} = {g}({v})"]


def _build(text: str, rng: random.Random, width: int, data_exempt: bool,
           span: tuple[int, int]) -> tuple[str, int]:
    """Build one machine aiming for a length within span. Returns (source, counted lines)."""
    c = Ctx(rng, frugal=span[1] < _FRUGAL_BELOW)
    names = list(TRANSFORMS)
    k = _transform_count(rng, span[1])
    # Beyond 17 steps, repeat transforms (each repeat gets its own random keys).
    chosen = rng.sample(names, k=min(k, len(names))) + rng.choices(names, k=max(0, k - len(names)))
    if not set(chosen) & set(_KEYED):
        chosen[rng.randrange(len(chosen))] = rng.choice(_KEYED)
    if data_exempt and "compress" not in chosen:    # keep big payloads (ASCII art) compact
        chosen.insert(rng.randint(0, len(chosen)), "compress")

    data, decoders = text.encode("utf-8"), []
    for t in chosen:
        data, dec = TRANSFORMS[t](c, data)
        decoders.append(dec)

    serial, ser_dec = _serialize(c, data)
    start = _scatter(c, serial, width)
    gears = [ser_dec, *reversed(decoders), _str_gear(c), _output_gear(c)]
    tail = _pipeline(c, start, gears)

    fname = c.name()
    target = rng.randint(*span)
    exempt = len(c.data_block) - 1 if data_exempt else 0

    def count() -> int:
        return 1 + len(c.prelude) + sum(map(len, c.blocks)) + len(tail) - exempt

    while count() < target:
        c.blocks.append([_decoy(c)])

    rng.shuffle(c.blocks)
    body = c.prelude + [ln for blk in c.blocks for ln in blk] + tail
    if body and rng.random() < 0.8:
        for _ in range(rng.randint(1, 3)):
            i = rng.randrange(len(body))
            if "#" not in body[i] and not body[i].rstrip().endswith((",", "(", "[", "{")):
                body[i] += "  " + rng.choice(_LIES)
    lines = [f"def {fname}():"] + ["    " + ln for ln in body]
    call = rng.choice([f"{fname}()", f"if __name__ == {c.text('__main__')}:\n    {fname}()"])
    return "\n".join(lines) + "\n\n\n" + call + "\n", count()


def function_lines(code: str) -> int:
    """Number of lines in the generated function (def line through last body line)."""
    return code.split("\n\n\n", 1)[0].count("\n") + 1


def run_generated(code: str) -> str:
    """Execute generated code in a fresh namespace and return what it printed."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(code, "<goldberg>", "exec"), {"__name__": "__main__"})  # noqa: S102
    return buf.getvalue()


def generate_with_stats(text: str, seed: int | None = None, verify: bool = True,
                        data_exempt: bool = False, lines: int = DEFAULT_LINES,
                        variation: int = DEFAULT_VARIATION) -> tuple[str, int]:
    """Return (source, counted lines) for a convoluted function that prints `text`.

    The function is lines +/- variation long (def line included). With data_exempt,
    the payload dict counts as one line, however many lines it really takes.
    """
    lo, hi = line_range(lines, variation)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as e:
        raise ValueError(f"text is not valid Unicode (e.g. a lone surrogate at index {e.start})") from e
    rng = random.Random(seed)
    last_err: Exception | None = None
    shortest: int | None = None
    for attempt in range(MAX_ATTEMPTS):
        # Wrap data lines at 100 chars, unless that busts a tight budget: then one line.
        roomy = data_exempt or (hi >= _FRUGAL_BELOW and attempt < MAX_ATTEMPTS // 2)
        width = 100 if roomy else 10**9
        code, n = _build(text, rng, width, data_exempt, (lo, hi))
        shortest = n if shortest is None else min(shortest, n)
        if not lo <= n <= hi:
            continue
        if verify:
            try:
                out = run_generated(code)
            except Exception as e:  # noqa: BLE001 - any failure means re-roll
                last_err = e
                continue
            if out != text + "\n":
                last_err = AssertionError(f"printed {out[:80]!r}...")
                continue
        return code, n
    if last_err is None:      # never fit the budget
        raise ValueError(f"cannot fit a machine into {lo}-{hi} lines; the shortest built was "
                         f"{shortest} lines. Allow more lines (-n/--lines) or more --variation.")
    raise RuntimeError(f"could not build a valid machine in {MAX_ATTEMPTS} attempts: {last_err}")


def generate(text: str, seed: int | None = None, verify: bool = True,
             data_exempt: bool = False, lines: int = DEFAULT_LINES,
             variation: int = DEFAULT_VARIATION) -> str:
    """Return Python source for a convoluted function that prints `text`."""
    return generate_with_stats(text, seed, verify, data_exempt, lines, variation)[0]


# ---------------------------------------------------------------------------
# Image -> text art.
# ---------------------------------------------------------------------------
# Brightness ramps for the ascii style, dark -> bright (suits dark terminal backgrounds).
RAMPS = {
    "short": " .:-=+*#%@",                                                 # bold, high contrast
    "long": " .'`^\",:;Il!i><~+_-?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$",  # photos
}
DEFAULT_RAMP = RAMPS["short"]
IMAGE_MODES = ("auto", "shape", "ascii", "blocks", "braille")
# Quadrant glyphs indexed by bits: 1=top-left, 2=top-right, 4=bottom-left, 8=bottom-right.
_QUADRANTS = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"
# Braille dot bit for each (x, y) in the 2x4 cell.
_BRAILLE_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))
_BRAILLE_BLANK = "\u2800"
# Default widths: higher-resolution modes pack more pixels per char, so go wider.
DEFAULT_WIDTH = {"shape": 180, "ascii": 80, "blocks": 120, "braille": 160}
PHOTO_WIDTH = 140        # auto mode, photo-like images: ascii style with the long ramp
# Auto mode calls an image logo-like when its border is mostly one tone (a clear
# background) that also covers a good share of the picture; otherwise photo-like.
_LOGO_BORDER_UNIFORMITY = 0.75
_LOGO_BACKGROUND_SHARE = 0.30
_TONE_TOLERANCE = 16
MAX_WIDTH = 1000         # beyond this, art is unwieldy and rendering gets slow
MAX_ROWS = 500           # tall images are narrowed so the art stays at most this tall
_ADAPTIVE_SLACK = 0.15   # "on" if >15% brighter than the local mean...
_ADAPTIVE_FLOOR = 40     # ...and not just dark noise


MAX_SOURCE_SIDE = 4096   # larger images are downscaled on load (output is far smaller anyway)
_JPEG_DRAFT_SIDE = 2048  # JPEGs may decode straight down to this; detail beyond it is unused


def _register_optional_formats() -> None:
    """Enable HEIC/HEIF (e.g. iPhone photos) when the optional pillow-heif is installed."""
    try:
        import pillow_heif
    except ImportError:
        return
    pillow_heif.register_heif_opener()


def _request_reduced_decode(im) -> None:
    """Let a large JPEG decode straight to 1/2, 1/4 or 1/8 size (no-op for other formats).

    The decoder only shrinks while the result still covers the requested size, so ask
    for the image's own aspect ratio (not a square) with its longest side at
    _JPEG_DRAFT_SIDE. Saves most of the time and memory for big photos.
    """
    scale = _JPEG_DRAFT_SIDE / max(im.size)
    if scale < 1:
        im.draft(None, (max(1, int(im.width * scale)), max(1, int(im.height * scale))))


def _to_gray(im):
    """Any Pillow mode -> 8-bit grayscale, transparency flattened onto black."""
    from PIL import Image
    if im.mode in ("I", "F") or im.mode.startswith("I;16"):
        # High bit depth (16-bit PNG/TIFF, float TIFF): converting straight to "L"
        # clips everything above 255, so stretch the actual range into 0..255 first.
        im = im.convert("F")
        lo, hi = im.getextrema()
        scale = 255.0 / (hi - lo) if hi > lo else 0.0
        return im.point(lambda v: (v - lo) * scale).convert("L")
    if im.mode in ("RGBA", "LA", "PA", "RGBa", "La") or \
            (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        im = Image.alpha_composite(Image.new("RGBA", im.size, (0, 0, 0, 255)), im)
    return im.convert("L")


def _load_gray(path: str, invert: bool):
    """Open an image as grayscale with the subject bright, background dark, margins trimmed."""
    return _prepare_gray(_read_gray(path), invert)


def _read_gray(path: str):
    """Open any image as 8-bit grayscale, upright and size-limited, but otherwise untouched.

    Accepts any format Pillow reads (PNG, JPEG, GIF, BMP, TIFF, WebP, AVIF, ICO, ...);
    multi-frame files (animated GIF/WebP, multi-page TIFF) use their first frame.
    """
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as e:  # pragma: no cover
        raise SystemExit("image mode needs Pillow: pip install pillow") from e
    _register_optional_formats()
    try:
        with Image.open(path) as im:
            _request_reduced_decode(im)
            im = ImageOps.exif_transpose(im)
            if max(im.size) > MAX_SOURCE_SIDE:
                im.thumbnail((MAX_SOURCE_SIDE, MAX_SOURCE_SIDE), Image.Resampling.LANCZOS)
            gray = _to_gray(im)
    except FileNotFoundError as e:
        raise SystemExit(f"image not found: {path}") from e
    except UnidentifiedImageError as e:
        hint = (" SVG is a vector format: export it to PNG first." if str(path).lower().endswith(".svg")
                else " HEIC/HEIF needs: pip install pillow-heif."
                if str(path).lower().endswith((".heic", ".heif")) else "")
        raise SystemExit(f"cannot read {path!r} as an image.{hint}") from e
    except Image.DecompressionBombError as e:
        raise SystemExit(f"{path!r} is too large to open safely ({e}). Downscale it first.") from e
    except OSError as e:   # truncated / corrupt files
        raise SystemExit(f"could not decode {path!r}: {e}") from e
    return gray


def _prepare_gray(gray, invert: bool):
    """Subject bright, background dark (blank in the art), contrast stretched, margins trimmed."""
    from PIL import ImageOps
    # Auto-orient: the border (background) should render as blank.
    w, h = gray.size
    border = [gray.getpixel((x, y)) for x in range(0, w, max(1, w // 50)) for y in (0, h - 1)]
    border += [gray.getpixel((x, y)) for y in range(0, h, max(1, h // 50)) for x in (0, w - 1)]
    if sorted(border)[len(border) // 2] > 127:
        gray = ImageOps.invert(gray)
    if invert:
        gray = ImageOps.invert(gray)
    gray = ImageOps.autocontrast(gray)
    bbox = gray.point(lambda v: 255 if v > 24 else 0).getbbox()   # trim empty margins
    return gray.crop(bbox) if bbox else gray


def _classify_gray(gray) -> str:
    """'logo' if the image has a clear, uniform background; otherwise 'photo'."""
    small = gray.copy()
    small.thumbnail((256, 256))
    w, h = small.size
    px = small.load()
    border = [px[x, y] for x in range(w) for y in (0, h - 1)] + \
             [px[x, y] for y in range(h) for x in (0, w - 1)]
    bg = sorted(border)[len(border) // 2]
    near = lambda v: abs(v - bg) <= _TONE_TOLERANCE  # noqa: E731
    uniformity = sum(map(near, border)) / len(border)
    share = sum(c for v, c in enumerate(small.histogram()) if near(v)) / (w * h)
    logo = uniformity >= _LOGO_BORDER_UNIFORMITY and share >= _LOGO_BACKGROUND_SHARE
    return "logo" if logo else "photo"


def classify_image(path: str) -> str:
    """'logo' (clear background: suits the shape style) or 'photo' (suits ascii, long ramp)."""
    return _classify_gray(_read_gray(path))


def resolve_ramp(ramp: str | None) -> str | None:
    """A preset name ('short', 'long') -> its characters; anything else is used as given."""
    return RAMPS.get(ramp, ramp) if ramp is not None else None


def _otsu(gray) -> int:
    """Otsu's threshold: the cut that best separates foreground from background."""
    hist = gray.histogram()
    total, sum_all = sum(hist), sum(i * c for i, c in enumerate(hist))
    best_t, best_var, w_b, sum_b = 128, -1.0, 0, 0
    for t, c in enumerate(hist):
        w_b += c
        if w_b == 0 or w_b == total:
            continue
        sum_b += t * c
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / (total - w_b)
        var = w_b * (total - w_b) * (m_b - m_f) ** 2
        if var > best_var:
            best_t, best_var = t, var
    return best_t


def _bitmap(gray, px_w: int, px_h: int, dither: bool) -> list[list[bool]]:
    """Resize and reduce to on/off pixels (Otsu threshold, or Floyd-Steinberg dither)."""
    from PIL import Image, ImageChops, ImageFilter
    if dither:
        small = gray.resize((px_w, px_h), Image.Resampling.LANCZOS)
        px = small.convert("1").load()               # Pillow dithers by default
        return [[bool(px[x, y]) for x in range(px_w)] for y in range(px_h)]
    # Area-average downscale keeps thin strokes (e.g. small text) as grey instead of
    # dropping them; then a pixel is "on" if it beats the global Otsu cut, OR it is
    # clearly brighter than its neighbourhood (local/adaptive threshold), which
    # rescues those faint strokes without flooding solid regions.
    small = gray.resize((px_w, px_h), Image.Resampling.BOX)
    t = _otsu(small)
    local = small.filter(ImageFilter.BoxBlur(max(2, px_w // 80)))
    local = local.point(lambda v: min(255, int(v * (1 - _ADAPTIVE_SLACK))))
    above_local = ImageChops.subtract(small, local).point(lambda v: 255 if v > 0 else 0)
    floor = small.point(lambda v: 255 if v > _ADAPTIVE_FLOOR else 0)
    global_on = small.point(lambda v: 255 if v > t else 0)
    mono = ImageChops.lighter(global_on, ImageChops.darker(above_local, floor))
    px = mono.load()
    return [[px[x, y] > 0 for x in range(px_w)] for y in range(px_h)]


def _fit(gray, width: int, cell_aspect: float) -> tuple[int, int]:
    """(width, rows) of the art for this image; cell_aspect = cell width / height.

    Rows follow the image's aspect ratio. A tall image that would need more than
    MAX_ROWS rows is narrowed (keeping its shape), bounding time and memory.
    """
    ratio = gray.height / gray.width * cell_aspect
    rows = max(1, round(ratio * width))
    if rows > MAX_ROWS:
        width = max(1, round(MAX_ROWS / ratio))
        rows = min(MAX_ROWS, max(1, round(ratio * width)))
    return width, rows


def _render_ascii(gray, width: int, ramp: str) -> list[str]:
    from PIL import Image, ImageFilter
    width, height = _fit(gray, width, 0.5)                          # cells ~2x tall
    small = gray.resize((width, height), Image.Resampling.LANCZOS)
    small = small.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=2))
    scale, px = (len(ramp) - 1) / 255, small.load()
    return ["".join(ramp[round(px[x, y] * scale)] for x in range(width)) for y in range(height)]


def _render_cells(gray, width: int, cw: int, ch: int, dither: bool, glyph) -> list[str]:
    """Render with cw x ch pixels per character; glyph(cell_bits) -> str."""
    width, rows = _fit(gray, width, 0.5)                          # cells ~2x tall
    bm = _bitmap(gray, width * cw, rows * ch, dither)
    return ["".join(glyph([[bm[r * ch + dy][c * cw + dx] for dx in range(cw)] for dy in range(ch)])
                    for c in range(width)) for r in range(rows)]

# Shape matching: every cell is compared with rendered glyphs of a monospace font.
_SHAPE_CELL_H = 24       # template cell height in px (width follows the font's aspect)
_SHAPE_BLUR = 1.5        # blur on glyphs and image: tolerates small misalignments
_SHAPE_BAND_CELLS = 20_000   # cells matched per batch (~25 MB of floats)
_FONT_CANDIDATES = (
    "DejaVuSansMono.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf",
    "C:/Windows/Fonts/consola.ttf", "C:/Windows/Fonts/cour.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf", "Courier New.ttf",
)


def _mono_font(font_path: str | None, cell_h: int):
    """A font sized so one line is cell_h px tall, plus its cell width."""
    from PIL import ImageFont
    for cand in ([font_path] if font_path else list(_FONT_CANDIDATES)):
        try:
            probe = ImageFont.truetype(cand, 100)
        except OSError as e:
            if font_path:
                raise SystemExit(f"cannot load font {font_path!r}: {e}") from e
            continue
        a, d = probe.getmetrics()
        font = ImageFont.truetype(cand, max(6, int(100 * cell_h / (a + d))))
        return font, max(1, round(font.getlength("M")))
    font = ImageFont.load_default(size=cell_h * 0.8)   # Pillow's bundled fallback
    return font, max(1, round(font.getlength("M")))


def _render_shape(gray, width: int, font_path: str | None) -> list[str]:
    """Pick, for each cell, the printable ASCII glyph whose shape best matches it."""
    try:
        import numpy as np
    except ImportError as e:  # pragma: no cover
        raise SystemExit("shape mode needs numpy: pip install numpy (or use -m ascii)") from e
    from PIL import Image, ImageDraw, ImageFilter
    ch = _SHAPE_CELL_H
    font, cw = _mono_font(font_path, ch)
    a, d = font.getmetrics()
    chars = [chr(c) for c in range(32, 127)]
    glyphs = []
    for c in chars:
        im = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(im).text((0, ch - (a + d)), c, fill=255, font=font)
        glyphs.append(np.asarray(im.filter(ImageFilter.GaussianBlur(_SHAPE_BLUR)), np.float32))
    tmpl = np.stack(glyphs).reshape(len(chars), -1) / 255

    norms = (tmpl * tmpl).sum(1)[None, :]

    width, rows = _fit(gray, width, cw / ch)
    img = gray.resize((width * cw, rows * ch), Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.GaussianBlur(_SHAPE_BLUR))
    out = []
    band = max(1, _SHAPE_BAND_CELLS // width)          # text rows per band: bounds memory
    for r0 in range(0, rows, band):
        n = min(band, rows - r0)
        part = np.asarray(img.crop((0, r0 * ch, width * cw, (r0 + n) * ch)), np.float32) / 255
        cells = part.reshape(n, ch, width, cw).transpose(0, 2, 1, 3).reshape(n * width, -1)
        # argmin ||cell - glyph||^2 == argmin (|glyph|^2 - 2 cell.glyph): one matrix multiply.
        best = (norms - 2 * cells @ tmpl.T).argmin(1).reshape(n, width)
        out += ["".join(chars[i] for i in r) for r in best]
    return out


def _quadrant(cell) -> str:
    (a, b), (c, d) = cell
    return _QUADRANTS[a | b << 1 | c << 2 | d << 3]


def _braille(cell) -> str:
    return chr(0x2800 + sum(_BRAILLE_BITS[y][x] for y in range(4) for x in range(2) if cell[y][x]))


def image_to_ascii(path: str, width: int | None = None, ramp: str | None = None, invert: bool = False,
                   mode: str = "auto", dither: bool = False, font: str | None = None) -> str:
    """Render an image file as text art, `width` characters wide.

    Modes: "auto" (default: "shape" for logo-like images with a clear background,
    "ascii" with the long ramp at PHOTO_WIDTH for photos; see classify_image),
    "shape" (plain ASCII chosen by matching each cell's shape against rendered
    glyphs of a monospace font - sharpest pure-ASCII result, needs numpy),
    "ascii" (1 brightness level per char, from `ramp`), "blocks" (2x2 pixels
    per char, Unicode quadrants) or "braille" (2x4 pixels per char, Unicode braille).
    `dither` uses Floyd-Steinberg for blocks/braille (best for photos); otherwise
    an automatic threshold is used (best for logos and text). `ramp` is a preset
    name from RAMPS ("short", the ascii default; "long") or the characters to use.
    """
    if mode not in IMAGE_MODES:
        raise ValueError(f"mode must be one of {IMAGE_MODES}")
    ramp = resolve_ramp(ramp)
    if ramp is not None and len(ramp) < 2:
        raise ValueError("ramp needs at least 2 characters (or a preset: "
                         f"{', '.join(RAMPS)})")
    if width is not None and not 1 <= width <= MAX_WIDTH:
        raise ValueError(f"width must be between 1 and {MAX_WIDTH}")
    raw = _read_gray(path)
    if mode == "auto":
        if _classify_gray(raw) == "logo":
            mode = "shape"
        else:
            mode, width = "ascii", PHOTO_WIDTH if width is None else width
            ramp = RAMPS["long"] if ramp is None else ramp
    width = DEFAULT_WIDTH[mode] if width is None else width
    ramp = DEFAULT_RAMP if ramp is None else ramp
    gray = _prepare_gray(raw, invert)
    if mode == "shape":
        rows, blank = _render_shape(gray, width, font), " "
    elif mode == "ascii":
        rows, blank = _render_ascii(gray, width, ramp), " "
    elif mode == "blocks":
        rows, blank = _render_cells(gray, width, 2, 2, dither, _quadrant), " "
    else:
        rows, blank = _render_cells(gray, width, 2, 4, dither, _braille), _BRAILLE_BLANK
    # Strip trailing blanks per row, then blank rows at the end.
    return "\n".join(r.rstrip(blank + " ") for r in rows).rstrip("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("text", nargs="?", help="string to print, or '-' to read stdin")
    ap.add_argument("-i", "--image", help="image file to print as ASCII art instead of text")
    ap.add_argument("-w", "--width", type=int,
                    help="art width in chars (default: 180 shape, 140 auto-photo, 80 ascii, "
                         "120 blocks, 160 braille)")
    ap.add_argument("--ramp", help="ascii ramp, dark to bright: a preset (short, long) or "
                                   "your own characters (default: short; long for photos in auto)")
    ap.add_argument("--invert", action="store_true", help="swap which tone counts as background")
    ap.add_argument("-m", "--mode", choices=IMAGE_MODES, default="auto",
                    help="auto (default: shape for logos, ascii + long ramp for photos), shape "
                         "(ASCII matched to glyph shapes), ascii (brightness ramp), blocks "
                         "(2x2 px/char) or braille (2x4 px/char)")
    ap.add_argument("--font", help="monospace .ttf used for shape matching (default: auto)")
    ap.add_argument("--dither", action="store_true", help="dither blocks/braille (good for photos)")
    ap.add_argument("-n", "--lines", type=int, default=DEFAULT_LINES,
                    help=f"target length of the generated function (default {DEFAULT_LINES})")
    ap.add_argument("--variation", type=int, default=DEFAULT_VARIATION,
                    help=f"allowed +/- around --lines (default {DEFAULT_VARIATION}; 0 = exact)")
    ap.add_argument("-o", "--output", help="write code to this file instead of stdout")
    ap.add_argument("--seed", type=int, help="seed for reproducible output")
    ap.add_argument("--no-verify", action="store_true", help="skip executing the result")
    args = ap.parse_args(argv)
    if (args.text is None) == (args.image is None):
        ap.error("give exactly one of TEXT or --image")

    try:
        if args.image:
            if args.mode == "auto":
                kind = classify_image(args.image)
                style = "shape style" if kind == "logo" else "ascii style, long ramp"
                print(f"auto: {kind}-like image -> {style} (choose with -m)", file=sys.stderr)
            text = image_to_ascii(args.image, args.width, args.ramp, args.invert, args.mode,
                                  args.dither, args.font)
        else:
            text = sys.stdin.read().rstrip("\n") if args.text == "-" else args.text
        code = generate(text, seed=args.seed, verify=not args.no_verify,
                        data_exempt=bool(args.image), lines=args.lines, variation=args.variation)
    except ValueError as e:
        ap.error(str(e))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(code)
    else:
        # Generated identifiers are Greek/Cyrillic: don't crash on a non-UTF-8 console.
        with contextlib.suppress(AttributeError, ValueError):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
