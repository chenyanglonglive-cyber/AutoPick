from __future__ import annotations

"""Read-only OOXML report-layout discovery for QIMA-style Word reports.

The reports used by AutoPick are table-driven.  A photo frame normally lives in
one table row and the business caption lives in the following row.  Word emits
both modern DrawingML and legacy VML for those frames, so bookmarks are not a
reliable business identifier.
"""

import hashlib
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
V = "{urn:schemas-microsoft-com:vml}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"


@dataclass(frozen=True)
class ReportSlot:
    key: str
    table_index: int
    row_index: int
    cell_index: int
    image_kind: str
    media_name: str | None
    caption: str
    section: str | None
    width_emu: int | None = None
    height_emu: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def template_fingerprint(path: Path) -> str:
    """Hash the template bytes; a change produces a different blueprint."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_label(value: str) -> str:
    value = value.lower().replace("\u00a0", " ")
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value)
    return " ".join(value.split())


def _text(node: ET.Element) -> str:
    return " ".join((child.text or "") for child in node.iter(W + "t")).strip()


def _media_relationships(package: zipfile.ZipFile) -> dict[str, str]:
    relationships = ET.fromstring(package.read("word/_rels/document.xml.rels"))
    return {
        node.attrib["Id"]: Path(node.attrib["Target"]).name
        for node in relationships.findall(REL + "Relationship")
        if node.attrib.get("Target", "").replace("\\", "/").startswith("media/")
    }


def _cell_images(cell: ET.Element, relationships: dict[str, str]) -> list[tuple[str, str | None, int | None, int | None]]:
    """Return every image in a cell together with its OOXML representation."""
    result: list[tuple[str, str | None, int | None, int | None]] = []
    for node in cell.iter(A + "blip"):
        target = relationships.get(node.attrib.get(R + "embed", ""))
        result.append(("drawingml", target, None, None))
    for node in cell.iter(V + "imagedata"):
        target = relationships.get(node.attrib.get(R + "id", ""))
        result.append(("vml", target, None, None))
    # A DrawingML extent gives a useful aspect-ratio preference to the matcher.
    extents = list(cell.iter(WP + "extent"))
    if extents:
        width = int(extents[0].attrib.get("cx", "0")) or None
        height = int(extents[0].attrib.get("cy", "0")) or None
        result = [(kind, media, width, height) for kind, media, _, _ in result]
    return result


def _caption_for(rows: list[ET.Element], row_index: int, cell_index: int) -> str:
    """Captions in these reports are normally in the immediate next row."""
    for candidate_index in (row_index + 1, row_index - 1):
        if not 1 <= candidate_index <= len(rows):
            continue
        cells = rows[candidate_index - 1].findall(W + "tc")
        if cell_index <= len(cells):
            candidate = _text(cells[cell_index - 1])
            if candidate and normalize_label(candidate) not in {"picture s", "photos", "nil"}:
                return candidate
    return ""


def _section_before(tables: list[ET.Element], table_index: int) -> str | None:
    """Use nearby table text as a stable, supplier-independent section hint."""
    for index in range(table_index - 1, max(-1, table_index - 4), -1):
        content = _text(tables[index])
        if content:
            # Questions can be very long; the short leading context is enough.
            return content[:240]
    return None


def extract_report_slots(path: Path) -> list[ReportSlot]:
    """Discover photo frames and their adjacent captions without editing Word."""
    try:
        with zipfile.ZipFile(path) as package:
            document = ET.fromstring(package.read("word/document.xml"))
            relationships = _media_relationships(package)
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError("模板不是可读取的Word文件") from exc

    tables = list(document.iter(W + "tbl"))
    slots: list[ReportSlot] = []
    for table_index, table in enumerate(tables, start=1):
        rows = table.findall(W + "tr")
        section = _section_before(tables, table_index - 1)
        for row_index, row in enumerate(rows, start=1):
            for cell_index, cell in enumerate(row.findall(W + "tc"), start=1):
                for image_order, (kind, media_name, width, height) in enumerate(_cell_images(cell, relationships), start=1):
                    caption = _caption_for(rows, row_index, cell_index)
                    identity = "|".join(
                        [str(table_index), str(row_index), str(cell_index), str(image_order), normalize_label(caption), media_name or ""]
                    )
                    slots.append(
                        ReportSlot(
                            key=hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
                            table_index=table_index,
                            row_index=row_index,
                            cell_index=cell_index,
                            image_kind=kind,
                            media_name=media_name,
                            caption=caption or f"图片位置 {table_index}-{row_index}-{cell_index}",
                            section=section,
                            width_emu=width,
                            height_emu=height,
                        )
                    )
    return slots


def best_checklist_match(caption: str, checklist: list[tuple[str, str]]) -> tuple[str | None, float]:
    """Deterministic first pass used before embedding-based image selection.

    It deliberately only accepts a reasonably clear lexical relation.  A weak
    textual relation remains visible as an unmapped risk instead of silently
    pretending that a report field is covered.
    """
    target = normalize_label(caption)
    if not target:
        return None, 0.0
    best_id: str | None = None
    best_score = 0.0
    target_tokens = set(target.split())
    for slot_id, label in checklist:
        source = normalize_label(label)
        if not source:
            continue
        if source in target or target in source:
            score = min(len(source), len(target)) / max(len(source), len(target))
            score = max(score, 0.82)
        else:
            source_tokens = set(source.split())
            overlap = len(target_tokens & source_tokens)
            score = overlap / max(1, min(len(target_tokens), len(source_tokens)))
        if score > best_score:
            best_id, best_score = slot_id, score
    return (best_id, round(best_score, 4)) if best_score >= 0.42 else (None, round(best_score, 4))
