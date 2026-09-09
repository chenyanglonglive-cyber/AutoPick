from __future__ import annotations

import shutil
from pathlib import Path

from openpyxl import load_workbook


def test_history_alias_upsert_updates_existing_catalog_row(tmp_path: Path) -> None:
    """The SQLite upsert must reference the actual aliases_json column."""
    import sqlite3

    database = tmp_path / "catalog.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE checklist_catalog(label TEXT PRIMARY KEY, aliases_json TEXT NOT NULL)")
        db.execute("INSERT INTO checklist_catalog VALUES ('Factory gate', '[]')")
        db.execute(
            "INSERT INTO checklist_catalog(label, aliases_json) VALUES (?, ?) "
            "ON CONFLICT(label) DO UPDATE SET aliases_json=excluded.aliases_json",
            ("Factory gate", '["facility gate"]'),
        )
        value = db.execute("SELECT aliases_json FROM checklist_catalog WHERE label='Factory gate'").fetchone()[0]
    assert value == '["facility gate"]'
from PIL import Image

from backend.autopick.config import Settings
from backend.autopick.db import connect
from backend.autopick.services import ProjectService


def test_imported_blank_image_cell_becomes_a_project_local_rejection(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    service = ProjectService(settings)
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    Image.new("RGB", (1200, 800), (80, 90, 100)).save(gallery / "photo.jpg", "JPEG")
    project = service.create_project("Factory", str(gallery), checklist_type_id="quality_v1")
    slot = service.list_slots(project["id"])[0]
    with connect(service.db_path(project["id"])) as db:
        photo_id = db.execute("SELECT id FROM photos LIMIT 1").fetchone()["id"]
    service.confirm(project["id"], slot["id"], [photo_id], source="system")

    exported = service.export_excel(project["id"])
    feedback = tmp_path / "edited-feedback.xlsx"
    shutil.copy2(exported["output_path"], feedback)
    workbook = load_workbook(feedback)
    workbook["Photo report Tool"]._images = []
    workbook.save(feedback)
    result = service.import_excel_feedback(project["id"], str(feedback))

    assert result["rejected_count"] == 1
    assert result["accepted_count"] == 0
    with connect(service.db_path(project["id"])) as db:
        assert db.execute("SELECT 1 FROM confirmations WHERE slot_id=?", (slot["id"],)).fetchone() is None
        rejection = db.execute("SELECT photo_id FROM rejections WHERE slot_id=?", (slot["id"],)).fetchone()
        event = db.execute("SELECT outcome FROM feedback_events WHERE slot_id=?", (slot["id"],)).fetchone()
    assert rejection["photo_id"] == photo_id
    assert event["outcome"] == "rejected"


def test_manual_replacement_is_saved_when_the_checklist_is_exported(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    service = ProjectService(settings)
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    Image.new("RGB", (1200, 800), (80, 90, 100)).save(gallery / "system.jpg", "JPEG")
    Image.new("RGB", (1200, 800), (100, 90, 80)).save(gallery / "manual.jpg", "JPEG")
    project = service.create_project("Factory", str(gallery), checklist_type_id="quality_v1")
    slot = service.list_slots(project["id"])[0]
    with connect(service.db_path(project["id"])) as db:
        photos = db.execute("SELECT id FROM photos ORDER BY source_filename").fetchall()
    service.confirm(project["id"], slot["id"], [photos[1]["id"]], source="system")
    service.confirm(project["id"], slot["id"], [photos[0]["id"]], source="manual")

    service.export_excel(project["id"])

    with connect(service.db_path(project["id"])) as db:
        event = db.execute("SELECT outcome, system_photo_id, selected_photo_id FROM feedback_events WHERE source='manual'").fetchone()
    assert dict(event) == {"outcome": "replaced", "system_photo_id": photos[1]["id"], "selected_photo_id": photos[0]["id"]}


def test_auto_confirm_does_not_reuse_a_photo_between_fields(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    service = ProjectService(settings)
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    Image.new("RGB", (1200, 800), (80, 90, 100)).save(gallery / "first.jpg", "JPEG")
    Image.new("RGB", (1200, 800), (100, 90, 80)).save(gallery / "second.jpg", "JPEG")
    project = service.create_project("Factory", str(gallery), checklist_type_id="quality_v1")
    slots = service.list_slots(project["id"])[:2]
    with connect(service.db_path(project["id"])) as db:
        photos = db.execute("SELECT id FROM photos ORDER BY source_filename").fetchall()
        candidates = (
            (slots[0]["id"], photos[0]["id"], 0.9, 1),
            (slots[1]["id"], photos[0]["id"], 0.8, 1),
            (slots[1]["id"], photos[1]["id"], 0.7, 2),
        )
        db.executemany(
            "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            [(slot_id, photo_id, score, score, score, rank) for slot_id, photo_id, score, rank in candidates],
        )

    result = service.confirm_all_top_candidates(project["id"])

    assert result["selected_count"] == 2
    with connect(service.db_path(project["id"])) as db:
        selected = db.execute("SELECT photo_id FROM confirmations ORDER BY slot_id").fetchall()
    assert {row["photo_id"] for row in selected} == {photos[0]["id"], photos[1]["id"]}


def test_training_readiness_reaches_configured_threshold(tmp_path: Path) -> None:
    settings = Settings(
        tmp_path / "data", None, True, "test-token",
        training_feedback_threshold=2,
    )
    service = ProjectService(settings)
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    Image.new("RGB", (1200, 800), (80, 90, 100)).save(gallery / "photo.jpg", "JPEG")
    project = service.create_project("Factory", str(gallery), checklist_type_id="quality_v1")
    slots = service.list_slots(project["id"])[:2]
    with connect(service.db_path(project["id"])) as db:
        db.executemany(
            """INSERT INTO feedback_events(
                   id, export_id, slot_id, outcome, source, created_at
               ) VALUES (?, ?, ?, 'accepted', 'excel_feedback', CURRENT_TIMESTAMP)""",
            [
                ("feedback-1", "export-1", slots[0]["id"]),
                ("feedback-2", "export-2", slots[1]["id"]),
            ],
        )

    readiness = service.export_preflight(project["id"])

    assert readiness["training_data_count"] == 2
    assert readiness["training_data_threshold"] == 2
    assert readiness["training_progress_percent"] == 100
    assert readiness["training_remaining"] == 0
    assert readiness["training_ready"] is True
