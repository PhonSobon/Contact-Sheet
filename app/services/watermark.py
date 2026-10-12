"""
Watermark detection and removal.

What can be removed (nothing else in the document is re-encoded):
  * Watermark annotations (and, optionally, stamp annotations).
  * Content marked as a watermark: `/Artifact <</Subtype /Watermark>>` sections
    (Microsoft Word, LibreOffice and many PDF libraries write these) and
    content in an optional-content layer named like "Watermark".
  * Acrobat watermarks: Form XObjects tagged `/PieceInfo /ADBE_CompoundType
    /Private /Watermark`.
  * Text watermarks the user names (e.g. "CONFIDENTIAL"): a text object is
    only removed when *all* of its text is the watermark, so a sentence that
    merely contains the word is never touched. Only the text-drawing
    operators are cut, so colour/graphics state set alongside is kept.

What can't: a watermark baked into a scanned page image.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Set

import fitz  

from app.services import content_stream as cs

WATERMARK_NAME = re.compile(rb"watermark", re.IGNORECASE)
MAX_CANDIDATES = 8


@dataclass
class RemovalReport:
    text_objects: int = 0
    marked_sections: int = 0
    annotations: int = 0
    xobjects: int = 0

    @property
    def total(self) -> int:
        return self.text_objects + self.marked_sections + self.annotations + self.xobjects


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "").casefold()


def _is_only(text_norm: str, targets: List[str]) -> bool:
    """True if the text is one target, possibly repeated (tiled watermarks)."""
    if not text_norm:
        return False
    for t in targets:
        if t and len(text_norm) % len(t) == 0 and text_norm == t * (len(text_norm) // len(t)):
            return True
    return False


# ---------------------------------------------------------------- detection

def detect(doc: fitz.Document) -> dict:
    """Finds likely watermarks so the user can pick what to remove."""
    lines: Dict[str, dict] = {}
    marked = annots = scanned = 0
    for page in doc:
        page_area = abs(page.rect) or 1
        image_area = sum(abs(fitz.Rect(i["bbox"]) & page.rect) for i in page.get_image_info())
        if image_area > 0.5 * page_area:
            scanned += 1
        annots += sum(1 for a in page.annots() or [] if a.type[0] == fitz.PDF_ANNOT_WATERMARK)
        content = _read_page_content(doc, page)
        marked += len(_watermark_sections(cs.parse(content), _watermark_ocg_names(doc, page)))
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = " ".join("".join(s["text"] for s in line["spans"]).split())
                if len(text) < 2 or len(text) > 60 or not re.search(r"[^\W\d_]", text):
                    continue
                info = lines.setdefault(text, {"pages": set(), "rotated": False, "size": 0.0})
                info["pages"].add(page.number)
                info["rotated"] |= abs(line["dir"][1]) > 0.05
                info["size"] = max(info["size"], max(s["size"] for s in line["spans"]))

    page_count = doc.page_count
    candidates = []
    for text, info in lines.items():
        repeated = len(info["pages"]) >= max(2, 0.6 * page_count)
        if info["rotated"] or info["size"] >= 28 or repeated:
            score = (2 if info["rotated"] else 0) + (1 if info["size"] >= 28 else 0) + len(info["pages"]) / page_count
            candidates.append(
                {
                    "text": text,
                    "pages": len(info["pages"]),
                    "rotated": info["rotated"],
                    "font_size": round(info["size"], 1),
                    "likely": info["rotated"] or info["size"] >= 28,
                    "_score": score,
                }
            )
    candidates.sort(key=lambda c: -c["_score"])
    for c in candidates:
        del c["_score"]

    return {
        "page_count": page_count,
        "watermark_annotations": annots,
        "marked_watermarks": marked,
        "acrobat_watermarks": len(_acrobat_watermark_xobjects(doc)),
        "scanned_pages": scanned,
        "text_candidates": candidates[:MAX_CANDIDATES],
    }


# ---------------------------------------------------------------- removal

def remove(doc: fitz.Document, texts: List[str], remove_stamps: bool = False) -> RemovalReport:
    report = RemovalReport()
    targets = sorted({normalize(t) for t in texts if normalize(t)}, key=len, reverse=True)

    for xref in _acrobat_watermark_xobjects(doc):
        doc.update_stream(xref, b"")
        report.xobjects += 1

    handled_xobjects: Set[int] = set()
    for page in doc:
        for annot in list(page.annots() or []):
            kind = annot.type[0]
            if kind == fitz.PDF_ANNOT_WATERMARK or (remove_stamps and kind == fitz.PDF_ANNOT_STAMP):
                page.delete_annot(annot)
                report.annotations += 1

        _clean_page_content(doc, page, targets, report)
        if targets:
            _clean_page_xobjects(doc, page, targets, report, handled_xobjects)

    return report


def _clean_page_content(doc, page, targets, report) -> None:
    content = _read_page_content(doc, page)
    if not content:
        return
    ops = cs.parse(content)
    ranges = []

    for first, last in _watermark_sections(ops, _watermark_ocg_names(doc, page)):
        net_q = sum(1 for op in ops[first:last + 1] if op.name == "q") - sum(
            1 for op in ops[first:last + 1] if op.name == "Q"
        )
        keep = b"q " * net_q if net_q > 0 else b"Q " * -net_q
        ranges.append((ops[first].start, ops[last].end, keep.strip()))
        report.marked_sections += 1

    if targets:
        matched = _matching_text_blocks(doc, page, ops, targets)
        for first, last in matched:
            ranges.extend(_text_show_ranges(ops, first, last))
        report.text_objects += len(matched)

    if ranges:
        _write_page_content(doc, page, cs.splice_out(content, ranges))


def _matching_text_blocks(doc, page, ops, targets):
    """Text objects whose entire text is a watermark target."""
    blocks = cs.text_blocks(ops)
    matched, unsure = [], []
    for first, last in blocks:
        raw = b"".join(cs.shown_bytes(op) for op in ops[first:last + 1] if op.name in cs.TEXT_SHOW_OPS)
        if not raw:
            continue
        guess = raw.decode("latin-1")
        if _is_only(normalize(guess), targets):
            matched.append((first, last))
        elif not _looks_like_text(guess):
            # Embedded fonts often draw glyph ids, not characters, so the bytes
            # say nothing; ask MuPDF (which applies the font's ToUnicode map).
            unsure.append((first, last))

    if unsure and any(t in normalize(page.get_text()) for t in targets):
        matched.extend(_BlockIsolator(doc, page, ops).find(unsure, targets))
    return matched


def _looks_like_text(s: str) -> bool:
    printable = sum(1 for ch in s if ch.isprintable() and ord(ch) < 0x250)
    return printable >= 0.9 * len(s)


class _BlockIsolator:
    """Extracts the text of chosen text objects alone, by drawing only them on
    a scratch copy of the page. Groups are bisected so the common case — most
    text objects aren't the watermark — costs one extraction per group."""

    def __init__(self, doc, page, ops):
        self.ops = ops
        self.tmp = fitz.open()
        self.tmp.insert_pdf(doc, from_page=page.number, to_page=page.number, annots=False)
        self.xrefs = self.tmp[0].get_contents()
        self.content = _read_page_content(doc, page)

    def _last_font_before(self, idx):
        for op in reversed(self.ops[:idx]):
            if op.name == "Tf":
                return self.content[op.start:op.end]
        return b""

    def _text_of(self, group):
        parts = []
        for first, last in group:
            block = self.content[self.ops[first].start:self.ops[last].end]
            parts.append(b"q " + self._last_font_before(first) + b"\n" + block + b"\nQ\n")
        self.tmp.update_stream(self.xrefs[0], b"".join(parts))
        for x in self.xrefs[1:]:
            self.tmp.update_stream(x, b"")
        return normalize(self.tmp.reload_page(self.tmp[0]).get_text())

    def find(self, group, targets):
        text = self._text_of(group)
        if not any(t in text for t in targets):
            return []
        if len(group) == 1:
            return group if _is_only(text, targets) else []
        mid = len(group) // 2
        return self.find(group[:mid], targets) + self.find(group[mid:], targets)


def _clean_page_xobjects(doc, page, targets, report, handled) -> None:
    """A Form XObject whose only text is the watermark (a common way tools
    stamp every page) gets its text-drawing operators removed."""
    entries = page.get_xobjects()
    children = defaultdict(list)  # form xref -> nested xobject xrefs
    for xref, _name, invoker, _bbox in entries:
        if invoker:
            children[invoker].append(xref)

    isolator = None
    for xref, name, invoker, _bbox in entries:
        if xref in handled or invoker != 0 or doc.xref_get_key(xref, "Subtype")[1] != "/Form":
            continue
        handled.add(xref)
        if isolator is None:
            isolator = _BlockIsolator(doc, page, cs.parse(_read_page_content(doc, page)))
        isolator.tmp.update_stream(isolator.xrefs[0], b"q /" + name.encode("latin-1") + b" Do Q")
        for x in isolator.xrefs[1:]:
            isolator.tmp.update_stream(x, b"")
        text = normalize(isolator.tmp.reload_page(isolator.tmp[0]).get_text())
        if not _is_only(text, targets):
            continue

        # The XObject (and anything nested in it, e.g. an overlay page wrapped
        # by show_pdf_page) draws only watermark text: strip its text drawing.
        stack, seen, changed = [xref], set(), False
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(children.get(x, []))
            stream = doc.xref_stream(x) or b""
            ranges = [(op.start, op.end, b"") for op in cs.parse(stream) if op.name in cs.TEXT_SHOW_OPS]
            if ranges:
                doc.update_stream(x, cs.splice_out(stream, ranges))
                changed = True
        handled.update(seen)
        report.xobjects += int(changed)


def _text_show_ranges(ops, first, last):
    return [(op.start, op.end, b"") for op in ops[first:last + 1] if op.name in cs.TEXT_SHOW_OPS]


def _watermark_sections(ops, ocg_names: Set[bytes]):
    """(first, last) op indexes of marked-content sections that are watermarks."""
    sections, stack = [], []
    for idx, op in enumerate(ops):
        if op.name in ("BMC", "BDC"):
            is_wm = False
            if op.name == "BDC" and len(op.operands) >= 2:
                tag, props = op.operands[0][1], op.operands[1]
                if tag == b"/Artifact" and props[0] == "dict" and re.search(rb"/Subtype\s*/Watermark", props[1]):
                    is_wm = True
                elif tag == b"/OC" and props[0] == "name" and props[1][1:] in ocg_names:
                    is_wm = True
            stack.append((idx, is_wm))
        elif op.name == "EMC" and stack:
            start, is_wm = stack.pop()
            # Only outermost watermark sections; nested ones go with their parent.
            if is_wm and not any(w for _, w in stack):
                sections.append((start, idx))
    return sections


def _watermark_ocg_names(doc, page) -> Set[bytes]:
    """Resource names (e.g. b'oc1') of optional-content layers named like 'Watermark'."""
    wm_xrefs = {x for x, info in (doc.get_ocgs() or {}).items() if WATERMARK_NAME.search(info["name"].encode())}
    if not wm_xrefs:
        return set()
    kind, value = doc.xref_get_key(page.xref, "Resources/Properties")
    if kind != "dict":
        return set()
    return {
        name.encode()
        for name, xref in re.findall(r"/([^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R", value)
        if int(xref) in wm_xrefs
    }


def _acrobat_watermark_xobjects(doc) -> List[int]:
    found = []
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "Subtype")[1] != "/Form":
                continue
            if doc.xref_get_key(xref, "PieceInfo/ADBE_CompoundType/Private")[1] == "/Watermark":
                found.append(xref)
        except Exception:
            continue
    return found


def _read_page_content(doc, page) -> bytes:
    return b"\n".join(doc.xref_stream(x) or b"" for x in page.get_contents())


def _write_page_content(doc, page, data: bytes) -> None:
    xrefs = page.get_contents()
    doc.update_stream(xrefs[0], data)
    for x in xrefs[1:]:
        doc.update_stream(x, b"")
