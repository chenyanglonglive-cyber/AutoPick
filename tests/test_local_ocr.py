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
