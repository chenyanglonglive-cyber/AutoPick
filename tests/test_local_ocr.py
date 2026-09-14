from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from backend.autopick.config import Settings
from backend.autopick.db import connect
from backend.autopick.local_ocr import LocalOcrClient
from backend.autopick.services import ProjectService


def test_local_ocr_normalizes_text_without_network(monkeypatch) -> None:
    class FakeOutput:
        txts = (" ISO9001  ", " 质量 管理 ")

    class FakeEngine:
        def __call__(self, image_path: str) -> FakeOutput:
            assert image_path.endswith("sample.jpg")
            return FakeOutput()

    monkeypatch.setattr(LocalOcrClient, "_engine", FakeEngine())
    assert LocalOcrClient().extract_text(Path("sample.jpg")) == "ISO9001 质量 管理"


def test_ocr_text_breaks_a_semantic_tie_for_checklist_matching(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    service = ProjectService(settings)
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    Image.new("RGB", (1200, 800), (90, 90, 90)).save(gallery / "a.jpg", "JPEG")
    Image.new("RGB", (1200, 800), (90, 90, 90)).save(gallery / "b.jpg", "JPEG")
    project = service.create_project("Factory", str(gallery), checklist_type_id="quality_v1")
    slot = service.list_slots(project["id"])[0]

    with connect(service.db_path(project["id"])) as db:
        photos = db.execute("SELECT id FROM photos ORDER BY source_filename").fetchall()
        vector = np.zeros(settings.embedding_dimension, dtype=np.float32)
        vector[0] = 1.0
        for photo in photos:
            db.execute(
                "INSERT INTO embeddings VALUES (?, ?, ?, ?, ?, ?, ?)",
                (photo["id"], settings.embedding_model, settings.embedding_dimension, "test", vector.tobytes(), 0, "now"),
            )
            db.execute("UPDATE photos SET quality_score=0.5 WHERE id=?", (photo["id"],))
        db.execute("INSERT INTO ocr_results VALUES (?, ?, ?)", (photos[1]["id"], slot["label"], "now"))

    monkeypatch.setattr(service, "_query_vector", lambda *_: vector)
    service._compute_candidates(project["id"], slot["id"], slot["label"], 8)

    with connect(service.db_path(project["id"])) as db:
        top = db.execute("SELECT photo_id FROM candidates WHERE slot_id=? AND rank=1", (slot["id"],)).fetchone()
    assert top["photo_id"] == photos[1]["id"]


def test_ocr_restarts_after_an_interrupted_application_session(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    original_service = ProjectService(settings)
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    Image.new("RGB", (120, 80), (90, 90, 90)).save(gallery / "a.jpg", "JPEG")
    Image.new("RGB", (120, 80), (120, 100, 80)).save(gallery / "b.jpg", "JPEG")
    project = original_service.create_project("Factory", str(gallery), checklist_type_id="quality_v1")

    with connect(original_service.db_path(project["id"])) as db:
        first_photo = db.execute("SELECT id FROM photos ORDER BY source_filename LIMIT 1").fetchone()
        db.execute("INSERT INTO ocr_results VALUES (?, ?, ?)", (first_photo["id"], "already indexed", "now"))
        db.execute(
            "INSERT INTO jobs VALUES (?, 'ocr', 'running', 1, 2, ?, 0, 0, ?, ?)",
            ("interrupted-ocr", "本地 OCR 已识别 1/2 张图片", "now", "now"),
        )

    class DormantThread:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start(self) -> None:
            pass

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr("backend.autopick.services.threading.Thread", DormantThread)
    restarted_service = ProjectService(settings)
    resumed = restarted_service.start_ocr(project["id"])

    assert resumed["id"] != "interrupted-ocr"
    assert resumed["status"] == "queued"
    assert resumed["total"] == 1
    with connect(restarted_service.db_path(project["id"])) as db:
        interrupted = db.execute("SELECT status, message FROM jobs WHERE id='interrupted-ocr'").fetchone()
    assert interrupted["status"] == "interrupted"
    assert "中断" in interrupted["message"]


def test_exact_duplicate_photos_reuse_existing_ocr_text(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    service = ProjectService(settings)
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    source = gallery / "a.jpg"
    Image.new("RGB", (120, 80), (90, 90, 90)).save(source, "JPEG")
    duplicate = gallery / "b.jpg"
    duplicate.write_bytes(source.read_bytes())
    project = service.create_project("Factory", str(gallery), checklist_type_id="quality_v1")

    with connect(service.db_path(project["id"])) as db:
        original = db.execute("SELECT id FROM photos WHERE duplicate_of IS NULL").fetchone()
        copied = db.execute("SELECT id FROM photos WHERE duplicate_of IS NOT NULL").fetchone()
        db.execute("INSERT INTO ocr_results VALUES (?, ?, ?)", (original["id"], "shared OCR", "now"))

    service._copy_exact_duplicate_ocr(project["id"])

    with connect(service.db_path(project["id"])) as db:
        result = db.execute("SELECT text FROM ocr_results WHERE photo_id=?", (copied["id"],)).fetchone()
    assert result["text"] == "shared OCR"


def test_gallery_update_adds_only_new_content_and_preserves_existing_processing(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    service = ProjectService(settings)
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    Image.new("RGB", (120, 80), (10, 20, 30)).save(gallery / "a.jpg", "JPEG")
    Image.new("RGB", (120, 80), (40, 50, 60)).save(gallery / "b.jpg", "JPEG")
    project = service.create_project("Factory", str(gallery), checklist_type_id="quality_v1")

    with connect(service.db_path(project["id"])) as db:
        first_photo = db.execute("SELECT id FROM photos ORDER BY source_filename LIMIT 1").fetchone()
        vector = np.zeros(settings.embedding_dimension, dtype=np.float32)
        db.execute(
            "INSERT INTO embeddings VALUES (?, ?, ?, ?, ?, ?, ?)",
            (first_photo["id"], settings.embedding_model, settings.embedding_dimension, "test", vector.tobytes(), 0, "now"),
        )
        db.execute("INSERT INTO ocr_results VALUES (?, ?, ?)", (first_photo["id"], "existing OCR", "now"))

    unchanged = service.import_gallery(project["id"], gallery)
    Image.new("RGB", (120, 80), (70, 80, 90)).save(gallery / "c.jpg", "JPEG")
    updated = service.import_gallery(project["id"], gallery)

    assert unchanged["added_count"] == 0
    assert unchanged["skipped_count"] == 2
    assert updated["added_count"] == 1
    assert updated["skipped_count"] == 2
    with connect(service.db_path(project["id"])) as db:
        assert db.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM ocr_results").fetchone()[0] == 1


def test_combined_gallery_processing_queues_one_vector_and_ocr_pipeline(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    service = ProjectService(settings)
    gallery = tmp_path / "gallery"
    gallery.mkdir()
    Image.new("RGB", (120, 80), (10, 20, 30)).save(gallery / "a.jpg", "JPEG")
    Image.new("RGB", (120, 80), (40, 50, 60)).save(gallery / "b.jpg", "JPEG")
    project = service.create_project("Factory", str(gallery), checklist_type_id="quality_v1")
    calls: list[tuple[str, str, bool]] = []

    def fake_worker(project_id: str, job_id: str, include_ocr: bool = False) -> None:
        calls.append((project_id, job_id, include_ocr))

    monkeypatch.setattr(service, "_index_worker", fake_worker)
    job = service.start_gallery_processing(project["id"])
    service._jobs[job["id"]].join(timeout=2)

    assert job["kind"] == "gallery_processing"
    assert job["total"] == 2 + 2 + len(service.list_slots(project["id"]))
    assert calls == [(project["id"], job["id"], True)]
