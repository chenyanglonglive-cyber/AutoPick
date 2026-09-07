from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.autopick.config import Settings
from backend.autopick.db import connect
from backend.autopick.services import ProjectService


def write_image(path: Path, color: tuple[int, int, int]) -> None:
    Image.new("RGB", (1200, 800), color).save(path, "JPEG")


def make_template(path: Path) -> None:
    # Only existence/extension are used by project creation in this unit test.
    path.write_bytes(b"placeholder")


def test_project_photo_paths_are_physically_isolated(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    settings = Settings(data_root, None, True, "test-token")
    service = ProjectService(settings)
    gallery_a, gallery_b = tmp_path / "a", tmp_path / "b"
    gallery_a.mkdir(); gallery_b.mkdir()
    write_image(gallery_a / "same-name.jpg", (200, 20, 20))
    write_image(gallery_b / "same-name.jpg", (20, 20, 200))
    template = tmp_path / "template.docm"; make_template(template)

    a = service.create_project("Factory A", str(gallery_a), str(template), None)
    b = service.create_project("Factory B", str(gallery_b), str(template), None)
    with pytest.raises(ValueError):
        service._safe_relative(service.project_root(b["id"]), f"../{a['id']}/originals/forbidden.jpg")

    with service.db_path(a["id"]).open("rb") as handle_a, service.db_path(b["id"]).open("rb") as handle_b:
        assert handle_a.read() != handle_b.read()


def test_delete_project_removes_only_the_confirmed_project(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    service = ProjectService(settings)
    gallery_a, gallery_b = tmp_path / "a", tmp_path / "b"
    gallery_a.mkdir(); gallery_b.mkdir()
    write_image(gallery_a / "one.jpg", (200, 20, 20))
    write_image(gallery_b / "two.jpg", (20, 20, 200))
    first = service.create_project("上海测试1", str(gallery_a), checklist_type_id="quality_v1")
    second = service.create_project("上海测试1", str(gallery_b), checklist_type_id="quality_v1")

    with pytest.raises(ValueError):
        service.delete_project(first["id"], "错误项目名")
    assert service.project_root(first["id"]).exists()

    service.delete_project(first["id"], "上海测试1")
    assert not (settings.projects_root / first["id"]).exists()
    assert service.project_root(second["id"]).exists()


def test_vector_search_and_confirmation_never_cross_projects(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    service = ProjectService(settings)
    gallery_a, gallery_b = tmp_path / "a", tmp_path / "b"
    gallery_a.mkdir(); gallery_b.mkdir()
    write_image(gallery_a / "gate.jpg", (210, 30, 30))
    write_image(gallery_a / "line.jpg", (180, 30, 30))
    write_image(gallery_b / "gate.jpg", (30, 30, 210))
    write_image(gallery_b / "line.jpg", (30, 30, 180))
    template = tmp_path / "template.docm"; make_template(template)

    a = service.create_project("Factory A", str(gallery_a), str(template), None)
    b = service.create_project("Factory B", str(gallery_b), str(template), None)
    for project in (a, b):
        job = service.start_index(project["id"])
        service._jobs[job["id"]].join(timeout=10)
        assert service.get_job(project["id"], job["id"])["status"] == "completed"

    b_results = service.search(b["id"], "factory gate", 10)
    assert b_results
    b_root = service.project_root(b["id"])
    for candidate in b_results:
        assert b_root in service.safe_photo_path(b["id"], candidate["photo_id"]).parents

    a_slot = service.list_slots(a["id"])[0]
    b_photo = b_results[0]["photo_id"]
    with pytest.raises(ValueError, match="当前项目"):
        service.confirm(a["id"], a_slot["id"], [b_photo])


def test_high_confidence_candidate_is_automatically_confirmed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    service = ProjectService(settings)
    gallery = tmp_path / "gallery"; gallery.mkdir()
    write_image(gallery / "certificate.jpg", (80, 90, 100))
    template = tmp_path / "template.docm"; make_template(template)
    project = service.create_project("Factory", str(gallery), str(template), None)
    slot = service.list_slots(project["id"])[0]

    with connect(service.db_path(project["id"])) as db:
        photo = db.execute("SELECT id FROM photos LIMIT 1").fetchone()
        vector = np.zeros(1024, dtype=np.float32); vector[0] = 1.0
        db.execute(
            "INSERT INTO embeddings VALUES (?, ?, ?, ?, ?, ?, ?)",
            (photo["id"], settings.embedding_model, settings.embedding_dimension, "test", vector.tobytes(), 0, "now"),
        )
    monkeypatch.setattr(service, "_query_vector", lambda *_: np.r_[1.0, np.zeros(1023, dtype=np.float32)])

    service._compute_candidates(project["id"], slot["id"], slot["label"], 8)
    assert service.list_slots(project["id"])[0]["confirmed_photo_ids"] == [photo["id"]]


def test_confirm_all_top_candidates_preserves_manual_confirmation(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "data", None, True, "test-token")
    service = ProjectService(settings)
    gallery = tmp_path / "gallery"; gallery.mkdir()
    write_image(gallery / "top.jpg", (80, 90, 100))
    template = tmp_path / "template.docm"; make_template(template)
    project = service.create_project("Factory", str(gallery), str(template), None)
    slots = service.list_slots(project["id"])[:2]
    with connect(service.db_path(project["id"])) as db:
        photo_id = db.execute("SELECT id FROM photos LIMIT 1").fetchone()["id"]
        for slot in slots:
            db.execute(
                "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?)",
                (slot["id"], photo_id, 0.8, 1.0, 0.58, 1, "now"),
            )
    service.confirm(project["id"], slots[0]["id"], [photo_id])

    result = service.confirm_all_top_candidates(project["id"])
    assert result["selected_count"] == 1
    assert result["skipped_confirmed_count"] == 1
    assert service.list_slots(project["id"])[1]["confirmed_photo_ids"] == [photo_id]
