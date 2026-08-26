from __future__ import annotations

import zipfile
from pathlib import Path

from backend.autopick.history import extract_history_media
from backend.autopick.report_layout import best_checklist_match, extract_report_slots
from backend.autopick.config import Settings
from backend.autopick.reports import ReportService
from backend.autopick.services import ProjectService
from PIL import Image


def make_word_package(path: Path) -> None:
    document = """<?xml version='1.0' encoding='UTF-8'?>
<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
 xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
 xmlns:a='http://schemas.openxmlformats.org/drawingml/2006/main'
 xmlns:v='urn:schemas-microsoft-com:vml'>
 <w:body><w:tbl>
  <w:tr><w:tc><w:p><w:r><w:pict><v:imagedata r:id='rId1'/></w:pict></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:drawing><a:blip r:embed='rId2'/></w:drawing></w:r></w:p></w:tc></w:tr>
  <w:tr><w:tc><w:p><w:r><w:t>Quality manual</w:t></w:r></w:p></w:tc>
            <w:tc><w:p><w:r><w:t>ISO9001 Certificate</w:t></w:r></w:p></w:tc></w:tr>
 </w:tbl></w:body></w:document>"""
    relationships = """<?xml version='1.0' encoding='UTF-8'?>
<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>
 <Relationship Id='rId1' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/image' Target='media/image1.jpeg'/>
 <Relationship Id='rId2' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/image' Target='media/image2.jpeg'/>
</Relationships>"""
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", document)
        package.writestr("word/_rels/document.xml.rels", relationships)
        # Invalid image bytes are fine for layout discovery; history ignores their hash.
        package.writestr("word/media/image1.jpeg", b"x")
        package.writestr("word/media/image2.jpeg", b"y")


def test_layout_discovers_vml_and_drawingml_slots(tmp_path: Path) -> None:
    report = tmp_path / "template.docm"
    make_word_package(report)

    slots = extract_report_slots(report)

    assert [(slot.image_kind, slot.caption) for slot in slots] == [
        ("vml", "Quality manual"),
        ("drawingml", "ISO9001 Certificate"),
    ]
    # Captions are surfaced as history context even when the frame is VML.
    assert {item.context_text for item in extract_history_media(report)} >= {"Quality manual", "ISO9001 Certificate"}


def test_checklist_mapping_accepts_report_caption_variants() -> None:
    manual_id, manual_score = best_checklist_match("Quality policy and objective", [("manual", "Quality Objective")])
    iso_id, iso_score = best_checklist_match("ISO9001 Certificate", [("iso", "ISO9001:2015 certificate")])

    assert manual_id == "manual" and manual_score >= 0.42
    assert iso_id == "iso" and iso_score >= 0.42


def test_report_analysis_creates_project_local_slots(tmp_path: Path) -> None:
    gallery = tmp_path / "gallery"; gallery.mkdir()
    Image.new("RGB", (1200, 800), (100, 100, 100)).save(gallery / "evidence.jpg")
    template = tmp_path / "template.docm"; make_word_package(template)
    projects = ProjectService(Settings(tmp_path / "data", None, True, "test-token"))
    project = projects.create_project("Factory", str(gallery), str(template), None)

    report = ReportService(projects)
    analysis = report.analyze_template(project["id"])
    coverage = report.coverage(project["id"])

    assert analysis["slot_count"] == 2
    assert coverage["analyzed_slots"] == 2
    assert len(coverage["missing_images"]) == 2


def test_replacing_template_resets_only_report_slot_mapping(tmp_path: Path) -> None:
    gallery = tmp_path / "gallery"; gallery.mkdir()
    Image.new("RGB", (1200, 800), (100, 100, 100)).save(gallery / "evidence.jpg")
    original = tmp_path / "original.docm"; make_word_package(original)
    replacement = tmp_path / "replacement.docm"; make_word_package(replacement)
    projects = ProjectService(Settings(tmp_path / "data", None, True, "test-token"))
    project = projects.create_project("Factory", str(gallery), str(original), None)
    report = ReportService(projects)
    report.analyze_template(project["id"])

    result = projects.replace_template(project["id"], str(replacement))

    assert result["template_name"] == "replacement.docm"
    assert projects.get_project(project["id"])["template_name"] == "replacement.docm"
    assert report.coverage(project["id"])["analyzed_slots"] == 0
