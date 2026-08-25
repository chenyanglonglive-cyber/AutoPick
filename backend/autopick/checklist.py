from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def extract_checklist_items(path: Path) -> list[tuple[str, str | None]]:
    """Extract unique usable labels from a Word checklist without mutating it."""
    if not path.exists():
        return []
    try:
        with zipfile.ZipFile(path) as document:
            root = ET.fromstring(document.read("word/document.xml"))
    except (KeyError, zipfile.BadZipFile, ET.ParseError):
        return []

    labels: list[tuple[str, str | None]] = []
    section: str | None = None
    seen: set[str] = set()
    for row in root.findall(".//w:tr", NS):
        cells = []
        for cell in row.findall("w:tc", NS):
            text = "".join(node.text or "" for node in cell.findall(".//w:t", NS)).strip()
            if text:
                cells.append(re.sub(r"\s+", " ", text))
        for label in cells:
            compact = label.lower()
            if len(label) < 4 or compact in seen:
                continue
            if "onsite:" in compact or (len(label) < 35 and re.match(r"^[一二三四五六七八九十0-9].{0,20}$", label)):
                section = label
                continue
            seen.add(compact)
            labels.append((label, section))
    return labels


def fallback_checklist() -> list[tuple[str, str | None]]:
    return [
        ("Factory gate", "Onsite"),
        ("Factory building", "Onsite"),
        ("Office", "Onsite"),
        ("Production line", "Manufacturing Process"),
        ("Warehouse", "Materials Control"),
        ("Fire equipment", "Safety"),
        ("ISO9001 certificate", "Certificates"),
    ]
