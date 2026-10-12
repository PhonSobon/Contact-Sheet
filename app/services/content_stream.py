"""
A small PDF content-stream tokenizer: just enough to find operators, their
operands and their byte ranges so that pieces can be cut out of a stream
without re-encoding anything else.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

WHITESPACE = b" \t\r\n\f\x00"
DELIMITERS = b"()<>[]{}/%"
TEXT_SHOW_OPS = {"Tj", "TJ", "'", '"'}


@dataclass
class Op:
    name: str
    start: int                 # offset of the first operand (or the operator itself)
    end: int                   # offset just past the operator
    operands: List[Tuple[str, bytes]] = field(default_factory=list)  # (kind, raw bytes)


def _skip_literal_string(data: bytes, i: int) -> int:
    """`i` points at '('; returns the offset just past the matching ')'."""
    depth = 0
    n = len(data)
    while i < n:
        c = data[i]
        if c == 0x5C:  # backslash escapes the next byte
            i += 2
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _skip_composite(data: bytes, i: int) -> int:
    """`i` points at '[' or '<<'; returns the offset just past the matching close,
    skipping over strings that may contain bracket characters."""
    depth = 0
    n = len(data)
    while i < n:
        c = data[i]
        if c == 0x28:
            i = _skip_literal_string(data, i)
            continue
        if c == 0x25:  # comment
            while i < n and data[i] not in b"\r\n":
                i += 1
            continue
        if data.startswith(b"<<", i):
            depth += 1
            i += 2
            continue
        if data.startswith(b">>", i):
            depth -= 1
            i += 2
            if depth == 0:
                return i
            continue
        if c == 0x3C:  # hex string
            close = data.find(b">", i)
            i = n if close == -1 else close + 1
            continue
        if c == 0x5B:
            depth += 1
        elif c == 0x5D:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _skip_inline_image(data: bytes, i: int) -> int:
    """`i` points just past the 'ID' operator; returns the offset past 'EI'."""
    n = len(data)
    j = i + 1
    while j < n:
        k = data.find(b"EI", j)
        if k == -1:
            return n
        before_ok = k == 0 or data[k - 1] in WHITESPACE
        after_ok = k + 2 >= n or data[k + 2] in WHITESPACE
        if before_ok and after_ok:
            return k + 2
        j = k + 2
    return n


def parse(data: bytes) -> List[Op]:
    ops: List[Op] = []
    operands: List[Tuple[str, bytes]] = []
    op_start = None
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        if c in WHITESPACE:
            i += 1
            continue
        if c == 0x25:  # comment
            while i < n and data[i] not in b"\r\n":
                i += 1
            continue

        start = i
        if c == 0x28:
            i = _skip_literal_string(data, i)
            kind = "str"
        elif data.startswith(b"<<", i):
            i = _skip_composite(data, i)
            kind = "dict"
        elif c == 0x3C:
            close = data.find(b">", i)
            i = n if close == -1 else close + 1
            kind = "hex"
        elif c == 0x5B:
            i = _skip_composite(data, i)
            kind = "array"
        elif c == 0x2F:
            i += 1
            while i < n and data[i] not in WHITESPACE and data[i] not in DELIMITERS:
                i += 1
            kind = "name"
        elif c in b")>]}{":
            i += 1  # stray delimiter: ignore
            continue
        else:
            while i < n and data[i] not in WHITESPACE and data[i] not in DELIMITERS:
                i += 1
            word = data[start:i]
            if word in (b"true", b"false", b"null") or _is_number(word):
                kind = "num"
            else:
                name = word.decode("latin-1")
                if name == "BI":
                    id_pos = data.find(b"ID", i)
                    i = n if id_pos == -1 else _skip_inline_image(data, id_pos + 2)
                ops.append(Op(name, op_start if op_start is not None else start, i, operands))
                operands, op_start = [], None
                continue

        if op_start is None:
            op_start = start
        operands.append((kind, data[start:i]))
    return ops


def _is_number(word: bytes) -> bool:
    try:
        float(word)
        return True
    except ValueError:
        return False


def decode_literal(raw: bytes) -> bytes:
    """Decodes a '(...)' literal string's escapes."""
    body = raw[1:-1] if raw.endswith(b")") else raw[1:]
    out = bytearray()
    i, n = 0, len(body)
    escapes = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
    while i < n:
        c = body[i]
        if c != 0x5C:
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= n:
            break
        e = body[i]
        if e in escapes:
            out.append(escapes[e])
            i += 1
        elif 0x30 <= e <= 0x37:
            j = i
            while j < n and j - i < 3 and 0x30 <= body[j] <= 0x37:
                j += 1
            out.append(int(body[i:j], 8) & 0xFF)
            i = j
        elif e in b"\r\n":  # line continuation
            i += 2 if body[i:i + 2] == b"\r\n" else 1
        else:
            out.append(e)
            i += 1
    return bytes(out)


def decode_hex(raw: bytes) -> bytes:
    digits = bytes(b for b in raw[1:-1] if b not in WHITESPACE)
    if len(digits) % 2:
        digits += b"0"
    try:
        return bytes.fromhex(digits.decode("ascii"))
    except ValueError:
        return b""


def strings_in(raw: bytes) -> List[bytes]:
    """All string operands inside a TJ array (or a single string operand)."""
    out = []
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c == 0x28:
            j = _skip_literal_string(raw, i)
            out.append(decode_literal(raw[i:j]))
            i = j
        elif c == 0x3C and not raw.startswith(b"<<", i):
            j = raw.find(b">", i)
            j = n if j == -1 else j + 1
            out.append(decode_hex(raw[i:j]))
            i = j
        else:
            i += 1
    return out


def shown_bytes(op: Op) -> bytes:
    """The raw (undecoded-by-font) bytes a text-showing operator draws."""
    parts = []
    for kind, raw in op.operands:
        if kind in ("str", "hex", "array"):
            parts.extend(strings_in(raw))
    return b"".join(parts)


def text_blocks(ops: List[Op]) -> List[Tuple[int, int]]:
    """(index of BT, index of ET) for every top-level text object."""
    blocks, open_at = [], None
    for idx, op in enumerate(ops):
        if op.name == "BT" and open_at is None:
            open_at = idx
        elif op.name == "ET" and open_at is not None:
            blocks.append((open_at, idx))
            open_at = None
    return blocks


def splice_out(data: bytes, ranges: List[Tuple[int, int, bytes]]) -> bytes:
    """Replaces each (start, end) byte range with its replacement bytes.
    Ranges nested inside an earlier range are dropped."""
    out, pos = [], 0
    for start, end, repl in sorted(ranges):
        if start < pos:
            continue
        out.append(data[pos:start])
        out.append(b" " + repl + b" " if repl else b" ")
        pos = end
    out.append(data[pos:])
    return b"".join(out)
