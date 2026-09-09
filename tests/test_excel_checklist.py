from pathlib import Path

from openpyxl import load_workbook
from PIL import Image

from backend.autopick.config import Settings
from backend.autopick.db import connect
from backend.autopick.excel_checklist import checklist_types
from backend.autopick.services import ProjectService


def _image(path: Path, color=(40, 100, 180)) -> None:
    Image.new("RGB", (120, 80), color).save(path)


def test_quality_registry_has_199_slots_and_skips_markers() -> None:
    checklist = next(item for item in checklist_types() if item.id == "quality_v1")
    assert checklist.id == "quality_v1"
    assert checklist.label == "Quality Checklist"
    assert len(checklist.slots) == 199
    assert all(slot.label.lower() != "onsite:" for slot in checklist.slots)
    assert len({slot.item_key for slot in checklist.slots}) == 199
    assert all(slot.image_cell.endswith(str(int(slot.label_cell[1:]) - 1)) for slot in checklist.slots)


def test_social_audit_registry_has_36_reserved_photo_slots() -> None:
    checklist = next(item for item in checklist_types() if item.id == "social_audit_v1")
    assert checklist.label == "Social Audit Checklist"
    assert len(checklist.slots) == 36
    assert {slot.sheet_name for slot in checklist.slots} == {"Sheet1"}
    assert len({slot.item_key for slot in checklist.slots}) == 36


def test_excel_export_preserves_sheets_and_inserts_image(tmp_path: Path) -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    _image(gallery / "evidence.jpg")
    service = ProjectService(Settings(tmp_path / "data", None, True, "token"))
    project = service.create_project("Factory", str(gallery))
    slot = service.list_slots(project["id"])[0]
    photo_id = service.list_gallery(project["id"])[0]["photo_id"]
    service.confirm(project["id"], slot["id"], [photo_id])
    result = service.export_excel(project["id"])
    workbook = load_workbook(result["output_path"])
    assert workbook.sheetnames == ["Photo report Tool", "Sheet2"]
    assert len(workbook["Photo report Tool"]._images) == 1
    assert result["inserted_count"] == 1
    assert result["missing_count"] == 198


def test_social_audit_export_inserts_into_reserved_sheet1_cell(tmp_path: Path) -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    _image(gallery / "evidence.jpg")
    service = ProjectService(Settings(tmp_path / "data", None, True, "token"))
    project = service.create_project("Factory", str(gallery), checklist_type_id="social_audit_v1")
    slot = service.list_slots(project["id"])[0]
    photo_id = service.list_gallery(project["id"])[0]["photo_id"]
    service.confirm(project["id"], slot["id"], [photo_id])
    result = service.export_excel(project["id"])
    workbook = load_workbook(result["output_path"])
    assert workbook.sheetnames == ["Sheet1", "Sheet2", "Sheet3"]
    assert len(workbook["Sheet1"]._images) == 1
    assert result["inserted_count"] == 1
    assert result["missing_count"] == 35


def test_project_can_switch_checklists_without_sharing_confirmations_or_exports(tmp_path: Path) -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    _image(gallery / "evidence.jpg")
    service = ProjectService(Settings(tmp_path / "data", None, True, "token"))
    project = service.create_project("Factory", str(gallery), checklist_type_id="quality_v1")
    photo_id = service.list_gallery(project["id"])[0]["photo_id"]

    quality_slot = service.list_slots(project["id"], "quality_v1")[0]
    social_slot = service.list_slots(project["id"], "social_audit_v1")[0]
    service.confirm(project["id"], quality_slot["id"], [photo_id])
    service.confirm(project["id"], social_slot["id"], [photo_id])

    quality_preflight = service.export_preflight(project["id"], "quality_v1")
    social_preflight = service.export_preflight(project["id"], "social_audit_v1")
    assert (quality_preflight["total_slots"], quality_preflight["selected_slots"]) == (199, 1)
    assert (social_preflight["total_slots"], social_preflight["selected_slots"]) == (36, 1)

    quality_export = service.export_excel(project["id"], checklist_type_id="quality_v1")
    social_export = service.export_excel(project["id"], checklist_type_id="social_audit_v1")
    assert quality_export["missing_count"] == 198
    assert social_export["missing_count"] == 35


def test_rematch_removes_duplicate_automatic_selections_within_one_checklist(tmp_path: Path) -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    _image(gallery / "evidence.jpg")
    service = ProjectService(Settings(tmp_path / "data", None, True, "token"))
    project = service.create_project("Factory", str(gallery))
    slots = service.list_slots(project["id"], "quality_v1")[:2]
    photo_id = service.list_gallery(project["id"])[0]["photo_id"]
    with connect(service.db_path(project["id"])) as db:
        for slot in slots:
            db.execute(
                "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?)",
                (slot["id"], photo_id, 0.9, 1.0, 0.6, 1, "now"),
            )
            db.execute(
                "INSERT INTO confirmations(slot_id, photo_id, confirmed_at, source, system_photo_id) VALUES (?, ?, ?, 'system', ?)",
                (slot["id"], photo_id, "now", photo_id),
            )

    assert service._deduplicate_system_confirmations(project["id"], "quality_v1") == 1
    assert sum(bool(slot["confirmed_photo_ids"]) for slot in service.list_slots(project["id"], "quality_v1")[:2]) == 1


def test_clear_gallery_keeps_export_and_external_source(tmp_path: Path) -> None:
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    source = gallery / "evidence.jpg"
    _image(source)
    service = ProjectService(Settings(tmp_path / "data", None, True, "token"))
    project = service.create_project("Factory", str(gallery))
    result = service.clear_gallery(project["id"], "Factory")
    assert result["deleted_photos"] == 1
    assert source.is_file()
    assert service.get_project(project["id"])["photo_count"] == 0
