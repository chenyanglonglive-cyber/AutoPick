from pathlib import Path

from openpyxl import load_workbook
from PIL import Image

from backend.autopick.config import Settings
from backend.autopick.excel_checklist import checklist_types
from backend.autopick.services import ProjectService


def _image(path: Path, color=(40, 100, 180)) -> None:
    Image.new("RGB", (120, 80), color).save(path)


def test_quality_registry_has_199_slots_and_skips_markers() -> None:
    checklist = checklist_types()[0]
    assert checklist.id == "quality_v1"
    assert len(checklist.slots) == 199
    assert all(slot.label.lower() != "onsite:" for slot in checklist.slots)
    assert len({slot.item_key for slot in checklist.slots}) == 199
    assert all(slot.image_cell.endswith(str(int(slot.label_cell[1:]) - 1)) for slot in checklist.slots)


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
