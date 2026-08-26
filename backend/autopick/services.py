from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

import numpy as np

from backend.autopick.checklist import extract_checklist_items, fallback_checklist
from backend.autopick.config import Settings
from backend.autopick.db import connect, initialize_global, initialize_project
from backend.autopick.images import (
    IMAGE_SUFFIXES,
    PREPROCESS_VERSION,
    estimated_visual_tokens,
    flags_json,
    hamming_distance,
    inspect_image,
    make_derivative,
    sha256_file,
)
from backend.autopick.history import extract_history_media
from backend.autopick.qwen import QwenEmbeddingClient, QwenOcrClient


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectNotFoundError(FileNotFoundError):
    pass


class ProjectService:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.data_root.mkdir(parents=True, exist_ok=True)
        settings.projects_root.mkdir(parents=True, exist_ok=True)
        initialize_global(settings.global_db)
        self._jobs: dict[str, threading.Thread] = {}

    def project_root(self, project_id: str) -> Path:
        if not project_id or any(value in project_id for value in ("/", "\\", "..")):
            raise ProjectNotFoundError("Invalid project identifier")
        root = self.settings.projects_root / project_id
        if not (root / "project.sqlite").exists():
            raise ProjectNotFoundError(f"Project {project_id} was not found")
        return root

    def db_path(self, project_id: str) -> Path:
        return self.project_root(project_id) / "project.sqlite"

    def create_project(
        self,
        factory_name: str,
        gallery_path: str,
        template_path: str,
        checklist_path: str | None,
        history_report_path: str | None = None,
    ) -> dict:
        gallery = Path(gallery_path).expanduser().resolve()
        template = Path(template_path).expanduser().resolve()
        checklist = Path(checklist_path).expanduser().resolve() if checklist_path else None
        history = Path(history_report_path).expanduser().resolve() if history_report_path else None
        if not gallery.is_dir():
            raise ValueError("图库路径不是有效文件夹")
        if template.suffix.lower() not in {".docx", ".docm"} or not template.is_file():
            raise ValueError("模板必须是存在的 .docx 或 .docm 文件")
        if checklist and (not checklist.is_file() or checklist.suffix.lower() != ".docx"):
            raise ValueError("清单必须是存在的 .docx 文件")
        if history and (not history.is_file() or history.suffix.lower() not in {".docx", ".docm"}):
            raise ValueError("历史报告必须是存在的 .docx 或 .docm 文件")

        project_id = str(uuid.uuid4())
        root = self.settings.projects_root / project_id
        for child in ("originals", "derived/embedding", "derived/ocr", "derived/report", "templates", "history", "outputs", "manifests"):
            (root / child).mkdir(parents=True, exist_ok=True)
        copied_template = root / "templates" / template.name
        shutil.copy2(template, copied_template)
        copied_checklist: Path | None = None
        if checklist:
            copied_checklist = root / "templates" / checklist.name
            shutil.copy2(checklist, copied_checklist)
        copied_history: Path | None = None
        if history:
            copied_history = root / "history" / history.name
            shutil.copy2(history, copied_history)
        initialize_project(root / "project.sqlite")

        with connect(root / "project.sqlite") as db:
            db.execute(
                "INSERT INTO project VALUES (?, ?, ?, 'created', ?, ?, ?, ?, ?)",
                (
                    project_id,
                    factory_name.strip(),
                    utcnow(),
                    copied_template.relative_to(root).as_posix(),
                    copied_checklist.relative_to(root).as_posix() if copied_checklist else None,
                    self.settings.embedding_model,
                    self.settings.embedding_dimension,
                    PREPROCESS_VERSION,
                ),
            )
            items = extract_checklist_items(copied_checklist) if copied_checklist else []
            if not items:
                items = fallback_checklist()
            for ordinal, (label, section) in enumerate(items, start=1):
                db.execute(
                    "INSERT INTO checklist_slots VALUES (?, ?, ?, ?, NULL, ?)",
                    (str(uuid.uuid4()), label, section, ordinal, utcnow()),
                )
        self._sync_catalog(items)
        self.import_gallery(project_id, gallery)
        if copied_history:
            self.learn_from_report(project_id, copied_history)
        return self.get_project(project_id)

    def _sync_catalog(self, items: Iterable[tuple[str, str | None]]) -> None:
        with connect(self.settings.global_db) as db:
            for label, _ in items:
                db.execute("INSERT OR IGNORE INTO checklist_catalog(label, aliases_json) VALUES (?, '[]')", (label,))

    def import_gallery(self, project_id: str, gallery: Path) -> None:
        root = self.project_root(project_id)
        images = sorted(path for path in gallery.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
        if not images:
            raise ValueError("图库中没有可用图片")
        with connect(self.db_path(project_id)) as db:
            known_hashes = {row["sha256"]: row["id"] for row in db.execute("SELECT id, sha256 FROM photos")}
            known_dhashes = [(row["id"], row["dhash"]) for row in db.execute("SELECT id, dhash FROM photos")]
            for source in images:
                inspection = inspect_image(source)
                existing = known_hashes.get(inspection.sha256)
                photo_id = str(uuid.uuid4())
                target_name = f"{photo_id}_{source.name}"
                target = root / "originals" / target_name
                shutil.copy2(source, target)
                duplicate_of = existing
                nearby = [known_id for known_id, known_hash in known_dhashes if hamming_distance(inspection.dhash, known_hash) <= 4]
                near_group = nearby[0] if nearby else None
                db.execute(
                    """INSERT INTO photos(id,relative_path,source_filename,sha256,dhash,width,height,byte_size,blur_score,dark_ratio,bright_ratio,quality_score,quality_flags_json,duplicate_of,near_duplicate_group,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        photo_id,
                        target.relative_to(root).as_posix(),
                        source.name,
                        inspection.sha256,
                        inspection.dhash,
                        inspection.width,
                        inspection.height,
                        inspection.byte_size,
                        inspection.blur_score,
                        inspection.dark_ratio,
                        inspection.bright_ratio,
                        inspection.quality_score,
                        flags_json(inspection.flags),
                        duplicate_of,
                        near_group,
                        utcnow(),
                    ),
                )
                known_hashes[inspection.sha256] = photo_id
                known_dhashes.append((photo_id, inspection.dhash))

    def list_projects(self) -> list[dict]:
        projects = []
        for root in self.settings.projects_root.iterdir():
            if root.is_dir() and (root / "project.sqlite").exists():
                projects.append(self.get_project(root.name))
        return sorted(projects, key=lambda project: project["created_at"], reverse=True)

    def get_project(self, project_id: str) -> dict:
        with connect(self.db_path(project_id)) as db:
            project = dict(db.execute("SELECT * FROM project LIMIT 1").fetchone())
            counts = db.execute(
                """SELECT (SELECT COUNT(*) FROM photos) AS photo_count,
                          (SELECT COUNT(*) FROM embeddings) AS indexed_count,
                          (SELECT COUNT(DISTINCT slot_id) FROM confirmations) AS confirmed_count,
                          (SELECT COUNT(*) FROM checklist_slots) AS slot_count"""
            ).fetchone()
        return {**project, **dict(counts)}

    def start_index(self, project_id: str) -> dict:
        root = self.project_root(project_id)
        with connect(self.db_path(project_id)) as db:
            running = db.execute("SELECT * FROM jobs WHERE kind='index' AND status='running' ORDER BY created_at DESC LIMIT 1").fetchone()
            if running:
                return self._job_dict(running, project_id)
            photos = db.execute(
                "SELECT p.* FROM photos p LEFT JOIN embeddings e ON e.photo_id=p.id WHERE e.photo_id IS NULL AND p.duplicate_of IS NULL"
            ).fetchall()
            estimate = sum(estimated_visual_tokens(row["width"], row["height"]) for row in photos)
            if estimate > self.settings.token_budget:
                raise ValueError(f"预计 {estimate} Token，超过当前项目 {self.settings.token_budget} Token 预算")
            job_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO jobs VALUES (?, 'index', 'queued', 0, ?, '等待开始', ?, 0, ?, ?)",
                (job_id, len(photos), estimate, utcnow(), utcnow()),
            )
        thread = threading.Thread(target=self._index_worker, args=(project_id, job_id), daemon=True)
        self._jobs[job_id] = thread
        thread.start()
        return self.get_job(project_id, job_id)

    def _index_worker(self, project_id: str, job_id: str) -> None:
        root = self.project_root(project_id)
        with QwenEmbeddingClient(
            self.settings.dashscope_api_key,
            self.settings.embedding_model,
            self.settings.embedding_dimension,
            self.settings.demo_embeddings,
            max_retries=self.settings.qwen_max_retries,
        ) as client:
            try:
                with connect(self.db_path(project_id)) as db:
                    db.execute("UPDATE jobs SET status='running', message='正在生成图片向量', updated_at=? WHERE id=?", (utcnow(), job_id))
                    rows = db.execute(
                        "SELECT p.* FROM photos p LEFT JOIN embeddings e ON e.photo_id=p.id WHERE e.photo_id IS NULL AND p.duplicate_of IS NULL ORDER BY p.created_at"
                    ).fetchall()
                for ordinal, row in enumerate(rows, start=1):
                    original = self.safe_photo_path(project_id, row["id"])
                    derivative = root / "derived" / "embedding" / f"{row['id']}.jpg"
                    make_derivative(original, derivative, 1024, 82)
                    result = client.embed_image(derivative)
                    with connect(self.db_path(project_id)) as db:
                        db.execute(
                            "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                row["id"],
                                self.settings.embedding_model,
                                self.settings.embedding_dimension,
                                PREPROCESS_VERSION,
                                result.vector.astype(np.float32).tobytes(),
                                result.input_tokens,
                                utcnow(),
                            ),
                        )
                        db.execute(
                            "UPDATE photos SET embedding_relative_path=?, indexed_at=? WHERE id=?",
                            (derivative.relative_to(root).as_posix(), utcnow(), row["id"]),
                        )
                        db.execute(
                            "INSERT INTO api_usage VALUES (?, ?, ?, 'image_embedding', ?, ?, 'success', NULL, ?)",
                            (str(uuid.uuid4()), job_id, row["id"], self.settings.embedding_model, result.input_tokens, utcnow()),
                        )
                        db.execute(
                            "UPDATE jobs SET current=?, actual_tokens=actual_tokens+?, message=?, updated_at=? WHERE id=?",
                            (ordinal, result.input_tokens, f"已处理 {ordinal}/{len(rows)} 张图片", utcnow(), job_id),
                        )
                self._copy_exact_duplicate_vectors(project_id)
                with connect(self.db_path(project_id)) as db:
                    db.execute("UPDATE jobs SET message='正在按照清单自动匹配推荐候选照片...', updated_at=? WHERE id=?", (utcnow(), job_id))
                    slots = db.execute("SELECT id, label FROM checklist_slots ORDER BY ordinal").fetchall()
                for slot in slots:
                    try:
                        self._compute_candidates(project_id, slot["id"], slot["label"], 8)
                    except Exception:
                        pass
                with connect(self.db_path(project_id)) as db:
                    db.execute("UPDATE jobs SET status='completed', message='图片向量化与清单匹配已全部完成', updated_at=? WHERE id=?", (utcnow(), job_id))
                    db.execute("UPDATE project SET status='indexed'")
            except Exception as exc:
                with connect(self.db_path(project_id)) as db:
                    db.execute("UPDATE jobs SET status='failed', message=?, updated_at=? WHERE id=?", (str(exc)[:1000], utcnow(), job_id))

    def _copy_exact_duplicate_vectors(self, project_id: str) -> None:
        with connect(self.db_path(project_id)) as db:
            duplicates = db.execute("SELECT id, duplicate_of FROM photos WHERE duplicate_of IS NOT NULL").fetchall()
            for row in duplicates:
                source = db.execute("SELECT * FROM embeddings WHERE photo_id=?", (row["duplicate_of"],)).fetchone()
                if source:
                    db.execute(
                        "INSERT OR REPLACE INTO embeddings VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (row["id"], source["model"], source["dimension"], source["preprocess_version"], source["vector"], 0, utcnow()),
                    )

    def start_ocr(self, project_id: str) -> dict:
        """Recognize gallery text only after the user explicitly requests it."""
        root = self.project_root(project_id)
        with connect(self.db_path(project_id)) as db:
            running = db.execute("SELECT * FROM jobs WHERE kind='ocr' AND status='running' ORDER BY created_at DESC LIMIT 1").fetchone()
            if running:
                return self._job_dict(running, project_id)
            photos = db.execute(
                "SELECT p.* FROM photos p LEFT JOIN ocr_results o ON o.photo_id=p.id WHERE o.photo_id IS NULL"
            ).fetchall()
            job_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO jobs VALUES (?, 'ocr', 'queued', 0, ?, '等待开始文字识别', 0, 0, ?, ?)",
                (job_id, len(photos), utcnow(), utcnow()),
            )
        thread = threading.Thread(target=self._ocr_worker, args=(project_id, job_id), daemon=True)
        self._jobs[job_id] = thread
        thread.start()
        return self.get_job(project_id, job_id)

    def _ocr_worker(self, project_id: str, job_id: str) -> None:
        root = self.project_root(project_id)
        client = QwenOcrClient(self.settings.dashscope_api_key, self.settings.ocr_model, self.settings.demo_embeddings)
        try:
            with connect(self.db_path(project_id)) as db:
                db.execute("UPDATE jobs SET status='running', message='正在识别图库中的文字', updated_at=? WHERE id=?", (utcnow(), job_id))
                rows = db.execute(
                    "SELECT p.* FROM photos p LEFT JOIN ocr_results o ON o.photo_id=p.id WHERE o.photo_id IS NULL ORDER BY p.created_at"
                ).fetchall()
            for ordinal, row in enumerate(rows, start=1):
                original = self.safe_photo_path(project_id, row["id"])
                derivative = root / "derived" / "ocr" / f"{row['id']}.jpg"
                make_derivative(original, derivative, 1600, 90)
                result = client.extract_text(derivative)
                with connect(self.db_path(project_id)) as db:
                    db.execute("INSERT OR REPLACE INTO ocr_results VALUES (?, ?, ?)", (row["id"], result.text, utcnow()))
                    db.execute(
                        "INSERT INTO api_usage VALUES (?, ?, ?, 'image_ocr', ?, ?, 'success', NULL, ?)",
                        (str(uuid.uuid4()), job_id, row["id"], self.settings.ocr_model, result.input_tokens, utcnow()),
                    )
                    db.execute(
                        "UPDATE jobs SET current=?, actual_tokens=actual_tokens+?, message=?, updated_at=? WHERE id=?",
                        (ordinal, result.input_tokens, f"已识别 {ordinal}/{len(rows)} 张图片中的文字", utcnow(), job_id),
                    )
            with connect(self.db_path(project_id)) as db:
                db.execute("UPDATE jobs SET status='completed', message='图库文字识别已完成', updated_at=? WHERE id=?", (utcnow(), job_id))
        except Exception as exc:
            with connect(self.db_path(project_id)) as db:
                db.execute("UPDATE jobs SET status='failed', message=?, updated_at=? WHERE id=?", (str(exc)[:1000], utcnow(), job_id))

    def get_job(self, project_id: str, job_id: str) -> dict:
        with connect(self.db_path(project_id)) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise ValueError("任务不存在")
            return self._job_dict(row, project_id)

    @staticmethod
    def _job_dict(row: sqlite3.Row, project_id: str) -> dict:
        return {"id": row["id"], "project_id": project_id, **dict(row)}

    def list_slots(self, project_id: str) -> list[dict]:
        with connect(self.db_path(project_id)) as db:
            rows = db.execute(
                """SELECT s.*,
                          COALESCE((SELECT COUNT(*) FROM candidates c WHERE c.slot_id=s.id),0) candidate_count,
                          (SELECT MAX(c.total_score) FROM candidates c WHERE c.slot_id=s.id) top_score
                   FROM checklist_slots s ORDER BY ordinal"""
            ).fetchall()
            result = []
            for row in rows:
                confirmed = db.execute("SELECT photo_id FROM confirmations WHERE slot_id=?", (row["id"],)).fetchall()
                result.append({**dict(row), "confirmed_photo_ids": [value["photo_id"] for value in confirmed]})
            return result

    def list_gallery(self, project_id: str) -> list[dict]:
        with connect(self.db_path(project_id)) as db:
            rows = db.execute(
                """SELECT p.*, e.photo_id AS embedding_id, o.text AS ocr_text,
                          (SELECT COUNT(*) FROM confirmations c WHERE c.photo_id=p.id) AS usage_count
                   FROM photos p
                   LEFT JOIN embeddings e ON e.photo_id=p.id AND e.model=? AND e.dimension=?
                   LEFT JOIN ocr_results o ON o.photo_id=p.id
                   ORDER BY p.created_at, p.source_filename""",
                (self.settings.embedding_model, self.settings.embedding_dimension),
            ).fetchall()
        return [self._present_gallery_photo(project_id, row) for row in rows]

    @staticmethod
    def _ocr_match_score(query: str, text: str) -> float:
        normalized_query = "".join(query.lower().split())
        normalized_text = "".join(text.lower().split())
        if not normalized_query or not normalized_text:
            return 0.0
        if normalized_query in normalized_text:
            return 1.0
        tokens = re.findall(r"[a-z0-9][a-z0-9._-]{1,}|[\u4e00-\u9fff]{2,}", normalized_query)
        if not tokens:
            return 0.0
        hits = sum(token in normalized_text for token in tokens)
        return hits / len(tokens)

    def search_gallery(self, project_id: str, query: str, top_k: int = 120) -> list[dict]:
        self.project_root(project_id)
        with connect(self.db_path(project_id)) as db:
            rows = db.execute(
                """SELECT p.*, e.vector, e.photo_id AS embedding_id, o.text AS ocr_text,
                          (SELECT COUNT(*) FROM confirmations c WHERE c.photo_id=p.id) AS usage_count
                   FROM photos p
                   LEFT JOIN embeddings e ON e.photo_id=p.id AND e.model=? AND e.dimension=?
                   LEFT JOIN ocr_results o ON o.photo_id=p.id""",
                (self.settings.embedding_model, self.settings.embedding_dimension),
            ).fetchall()
        vector_rows = [row for row in rows if row["vector"] is not None]
        semantic: dict[str, float] = {}
        if vector_rows:
            query_vector = self._query_vector(project_id, query)
            matrix = np.vstack([np.frombuffer(row["vector"], dtype=np.float32) for row in vector_rows])
            semantic = {row["id"]: float(score) for row, score in zip(vector_rows, matrix @ query_vector)}
        ranked: list[tuple[float, sqlite3.Row, float, bool]] = []
        for row in rows:
            ocr_score = self._ocr_match_score(query, row["ocr_text"] or "")
            semantic_score = semantic.get(row["id"], -1.0)
            if semantic_score < -0.99 and not ocr_score:
                continue
            total = semantic_score + 0.02 * float(row["quality_score"])
            if ocr_score:
                total += 1.2 + 0.25 * ocr_score
            ranked.append((total, row, semantic_score, bool(ocr_score)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            self._present_gallery_photo(project_id, row, score=score, semantic_score=semantic_score, ocr_hit=ocr_hit)
            for score, row, semantic_score, ocr_hit in ranked[:top_k]
        ]

    def _present_gallery_photo(
        self, project_id: str, row: sqlite3.Row, score: float | None = None,
        semantic_score: float | None = None, ocr_hit: bool = False,
    ) -> dict:
        text = row["ocr_text"] or ""
        return {
            "photo_id": row["id"],
            "filename": row["source_filename"],
            "preview_url": f"/api/projects/{project_id}/photos/{row['id']}/file",
            "quality_score": round(float(row["quality_score"]), 4),
            "quality_flags": json.loads(row["quality_flags_json"]),
            "embedding_status": "indexed" if row["embedding_id"] else "pending",
            "ocr_status": "done" if row["ocr_text"] is not None else "pending",
            "ocr_text_preview": text[:240],
            "usage_count": int(row["usage_count"]),
            "score": round(float(score), 4) if score is not None else None,
            "semantic_score": round(float(semantic_score), 4) if semantic_score is not None else None,
            "ocr_hit": ocr_hit,
        }

    def candidates(self, project_id: str, slot_id: str, top_k: int = 8) -> list[dict]:
        with connect(self.db_path(project_id)) as db:
            slot = db.execute("SELECT * FROM checklist_slots WHERE id=?", (slot_id,)).fetchone()
            if not slot:
                raise ValueError("清单项目不存在")
            cached = db.execute("SELECT * FROM candidates WHERE slot_id=? ORDER BY rank LIMIT ?", (slot_id, top_k)).fetchall()
        if not cached:
            self._compute_candidates(project_id, slot_id, slot["label"], max(8, top_k))
            with connect(self.db_path(project_id)) as db:
                cached = db.execute("SELECT * FROM candidates WHERE slot_id=? ORDER BY rank LIMIT ?", (slot_id, top_k)).fetchall()
        return self._present_candidates(project_id, cached)

    def _query_vector(self, project_id: str, query: str) -> np.ndarray:
        normalized = " ".join(query.split()).strip().lower()
        with connect(self.db_path(project_id)) as db:
            cached = db.execute("SELECT vector, dimension FROM search_cache WHERE query=?", (normalized,)).fetchone()
            if cached:
                return np.frombuffer(cached["vector"], dtype=np.float32)
        with QwenEmbeddingClient(
            self.settings.dashscope_api_key,
            self.settings.embedding_model,
            self.settings.embedding_dimension,
            self.settings.demo_embeddings,
            max_retries=self.settings.qwen_max_retries,
        ) as client:
            result = client.embed_text(query)
        with connect(self.db_path(project_id)) as db:
            db.execute(
                "INSERT OR REPLACE INTO search_cache VALUES (?, ?, ?, ?, ?)",
                (normalized, result.vector.astype(np.float32).tobytes(), self.settings.embedding_model, self.settings.embedding_dimension, utcnow()),
            )
            db.execute(
                "INSERT INTO api_usage VALUES (?, NULL, NULL, 'text_embedding', ?, ?, 'success', NULL, ?)",
                (str(uuid.uuid4()), self.settings.embedding_model, result.input_tokens, utcnow()),
            )
        return result.vector

    def _vectors_and_photo_rows(self, project_id: str) -> tuple[np.ndarray, list[sqlite3.Row]]:
        with connect(self.db_path(project_id)) as db:
            rows = db.execute(
                """SELECT p.*, e.vector FROM photos p JOIN embeddings e ON e.photo_id=p.id
                   WHERE e.model=? AND e.dimension=?""",
                (self.settings.embedding_model, self.settings.embedding_dimension),
            ).fetchall()
        if not rows:
            raise ValueError("当前项目尚未完成图片向量化")
        matrix = np.vstack([np.frombuffer(row["vector"], dtype=np.float32) for row in rows])
        return matrix, rows

    def _compute_candidates(self, project_id: str, slot_id: str, query: str, top_k: int) -> None:
        query_vector = self._query_vector(project_id, query)
        matrix, rows = self._vectors_and_photo_rows(project_id)
        semantic = matrix @ query_vector
        ranked: list[tuple[float, float, sqlite3.Row]] = []
        for index, row in enumerate(rows):
            quality = float(row["quality_score"])
            duplicate_penalty = 0.05 if row["near_duplicate_group"] else 0.0
            total = 0.60 * float(semantic[index]) + 0.10 * quality - duplicate_penalty
            ranked.append((total, float(semantic[index]), row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        with connect(self.db_path(project_id)) as db:
            db.execute("DELETE FROM candidates WHERE slot_id=?", (slot_id,))
            for rank, (total, semantic_score, row) in enumerate(ranked[:top_k], start=1):
                db.execute(
                    "INSERT INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (slot_id, row["id"], semantic_score, row["quality_score"], total, rank, utcnow()),
                )

    def search(self, project_id: str, query: str, top_k: int) -> list[dict]:
        query_vector = self._query_vector(project_id, query)
        matrix, rows = self._vectors_and_photo_rows(project_id)
        semantic = matrix @ query_vector
        query_terms = {term.lower() for term in query.split() if len(term.strip()) > 1}
        ranked: list[tuple[float, float, sqlite3.Row]] = []
        with connect(self.db_path(project_id)) as db:
            ocr = {row["photo_id"]: row["text"].lower() for row in db.execute("SELECT photo_id, text FROM ocr_results")}
        for index, row in enumerate(rows):
            text = ocr.get(row["id"], "")
            ocr_hit = bool(query_terms and any(term in text for term in query_terms))
            score = float(semantic[index]) + (0.08 if ocr_hit else 0.0) + 0.02 * float(row["quality_score"])
            ranked.append((score, float(semantic[index]), row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        synthetic = []
        for rank, (score, semantic_score, row) in enumerate(ranked[:top_k], start=1):
            synthetic.append({"photo_id": row["id"], "total_score": score, "semantic_score": semantic_score, "quality_score": row["quality_score"], "rank": rank})
        return self._present_candidates(project_id, synthetic)

    def _present_candidates(self, project_id: str, candidates: Iterable[sqlite3.Row | dict]) -> list[dict]:
        result: list[dict] = []
        with connect(self.db_path(project_id)) as db:
            for candidate in candidates:
                photo_id = candidate["photo_id"]
                photo = db.execute("SELECT * FROM photos WHERE id=?", (photo_id,)).fetchone()
                if not photo:
                    continue
                used = db.execute("SELECT slot_id FROM confirmations WHERE photo_id=?", (photo_id,)).fetchall()
                result.append(
                    {
                        "photo_id": photo_id,
                        "filename": photo["source_filename"],
                        "preview_url": f"/api/projects/{project_id}/photos/{photo_id}/file",
                        "score": round(float(candidate["total_score"]), 4),
                        "semantic_score": round(float(candidate["semantic_score"]), 4),
                        "quality_score": round(float(candidate["quality_score"]), 4),
                        "ocr_hit": False,
                        "used_in_slots": [row["slot_id"] for row in used],
                        "quality_flags": json.loads(photo["quality_flags_json"]),
                    }
                )
        return result

    def confirm(self, project_id: str, slot_id: str, photo_ids: list[str]) -> None:
        root = self.project_root(project_id)
        with connect(self.db_path(project_id)) as db:
            if not db.execute("SELECT 1 FROM checklist_slots WHERE id=?", (slot_id,)).fetchone():
                raise ValueError("清单项目不存在")
            for photo_id in photo_ids:
                photo = db.execute("SELECT relative_path, sha256 FROM photos WHERE id=?", (photo_id,)).fetchone()
                if not photo:
                    raise ValueError("照片不属于当前项目")
                path = self._safe_relative(root, photo["relative_path"])
                if not path.exists() or sha256_file(path) != photo["sha256"]:
                    raise ValueError("照片文件校验失败，无法确认")
            db.execute("DELETE FROM confirmations WHERE slot_id=?", (slot_id,))
            for photo_id in photo_ids:
                db.execute("INSERT INTO confirmations VALUES (?, ?, ?)", (slot_id, photo_id, utcnow()))

    def reject(self, project_id: str, slot_id: str, photo_id: str, reason: str | None) -> None:
        with connect(self.db_path(project_id)) as db:
            db.execute(
                "INSERT OR REPLACE INTO rejections VALUES (?, ?, ?, ?)",
                (slot_id, photo_id, reason, utcnow()),
            )

    def set_mapping(self, project_id: str, slot_id: str, bookmark: str) -> None:
        with connect(self.db_path(project_id)) as db:
            changed = db.execute("UPDATE checklist_slots SET bookmark=? WHERE id=?", (bookmark, slot_id)).rowcount
            if changed != 1:
                raise ValueError("清单项目不存在")

    def template_bookmarks(self, project_id: str) -> list[str]:
        root = self.project_root(project_id)
        with connect(self.db_path(project_id)) as db:
            project = db.execute("SELECT template_relative_path FROM project LIMIT 1").fetchone()
        template = self._safe_relative(root, project["template_relative_path"])
        try:
            with zipfile.ZipFile(template) as package:
                document = ET.fromstring(package.read("word/document.xml"))
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            raise ValueError("模板不是可读取的Word文件") from exc
        namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        names = [node.attrib.get(f"{{{namespace}}}name", "") for node in document.iter(f"{{{namespace}}}bookmarkStart")]
        return sorted(name for name in names if name and not name.startswith("_"))

    def learn_from_report(self, project_id: str, report_path: Path) -> dict:
        """Associate embedded historical-report media with this project's photos only."""
        root = self.project_root(project_id)
        report = report_path.resolve()
        if root.resolve() not in report.parents:
            raise ValueError("历史报告必须先复制到当前项目目录")
        media = extract_history_media(report)
        with connect(self.db_path(project_id)) as db:
            photos = db.execute("SELECT id, sha256, dhash FROM photos").fetchall()
            slots = db.execute("SELECT id, label FROM checklist_slots").fetchall()
            db.execute("DELETE FROM history_matches WHERE report_relative_path=?", (report.relative_to(root).as_posix(),))
            matched = 0
            for item in media:
                exact = next((photo for photo in photos if photo["sha256"] == item.sha256), None)
                nearest = None
                distance = None
                if exact:
                    nearest, distance = exact, 0
                elif item.dhash:
                    options = sorted(
                        ((hamming_distance(item.dhash, photo["dhash"]), photo) for photo in photos),
                        key=lambda value: value[0],
                    )
                    if options and options[0][0] <= 8:
                        distance, nearest = options[0]
                slot_id = self._context_slot(item.context_text, slots)
                confidence = 1.0 if distance == 0 else (max(0.0, 1 - (distance or 99) / 16) if distance is not None else 0.0)
                if nearest:
                    matched += 1
                db.execute(
                    "INSERT INTO history_matches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        report.relative_to(root).as_posix(),
                        item.media_name,
                        nearest["id"] if nearest else None,
                        slot_id,
                        item.context_text,
                        distance,
                        confidence,
                        utcnow(),
                    ),
                )
        return {"media_count": len(media), "matched_count": matched}

    @staticmethod
    def _context_slot(context: str, slots: Iterable[sqlite3.Row]) -> str | None:
        normalized = " ".join(context.lower().split())
        matches = [slot for slot in slots if slot["label"].lower() in normalized]
        return matches[0]["id"] if matches else None

    def safe_photo_path(self, project_id: str, photo_id: str) -> Path:
        root = self.project_root(project_id)
        with connect(self.db_path(project_id)) as db:
            photo = db.execute("SELECT relative_path FROM photos WHERE id=?", (photo_id,)).fetchone()
            if not photo:
                raise ValueError("照片不属于当前项目")
        return self._safe_relative(root, photo["relative_path"])

    @staticmethod
    def _safe_relative(root: Path, relative_path: str) -> Path:
        candidate = (root / relative_path).resolve()
        if root.resolve() not in candidate.parents:
            raise ValueError("检测到跨项目文件路径，操作已阻止")
        return candidate
