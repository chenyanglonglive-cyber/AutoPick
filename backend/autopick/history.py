from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from backend.autopick.images import dhash_bytes, hamming_distance
from backend.autopick.report_layout import extract_report_slots


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass
class HistoryMedia:
    media_name: str
    sha256: str
    dhash: str | None
    context_text: str


def extract_history_media(report_path: Path) -> list[HistoryMedia]:
    """Read a DOCX/DOCM package without modifying it and retain nearby table text."""
    slot_context = {slot.media_name: slot.caption for slot in extract_report_slots(report_path) if slot.media_name}
    with zipfile.ZipFile(report_path) as package:
        document = ET.fromstring(package.read("word/document.xml"))
        relationships = ET.fromstring(package.read("word/_rels/document.xml.rels"))
        relation_targets = {
            node.attrib["Id"]: node.attrib["Target"].replace("\\", "/")
            for node in relationships.findall(f"{{{REL}}}Relationship")
            if node.attrib.get("Target", "").startswith("media/")
        }
        contexts: dict[str, str] = {f"media/{name}": caption for name, caption in slot_context.items()}
        for row in document.iter(f"{{{W}}}tr"):
            text = " ".join(node.text or "" for node in row.iter(f"{{{W}}}t")).strip()
            for blip in row.iter(f"{{{A}}}blip"):
                relation_id = blip.attrib.get(f"{{{R}}}embed")
                target = relation_targets.get(relation_id or "")
                if target:
                    contexts[target] = contexts.get(target) or text[:1000]
        result: list[HistoryMedia] = []
        for target in relation_targets.values():
            zip_name = f"word/{target}"
            if zip_name not in package.namelist():
                continue
            raw = package.read(zip_name)
            try:
                dhash = dhash_bytes(raw)
            except Exception:
                dhash = None
            result.append(
                HistoryMedia(
                    media_name=Path(target).name,
                    sha256=hashlib.sha256(raw).hexdigest(),
                    dhash=dhash,
                    context_text=contexts.get(target, ""),
                )
            )
        return result
