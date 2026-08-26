from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from backend.autopick.db import connect
from backend.autopick.images import make_derivative, sha256_file
from backend.autopick.report_layout import best_checklist_match, extract_report_slots, template_fingerprint
from backend.autopick.services import ProjectService, utcnow


class ReportService:
    """Build an audit report from discovered Word table image slots.

    All data reads go through the current project database. There is no
    cross-project image lookup in this service by design.
    """

    def __init__(self, projects: ProjectService):
        self.projects = projects

    def _template(self, project_id: str) -> tuple[Path, sqlite3.Row]:
        root = self.projects.project_root(project_id)
        with connect(self.projects.db_path(project_id)) as db:
            project = db.execute("SELECT * FROM project LIMIT 1").fetchone()
        if not project:
            raise ValueError("项目数据不存在")
        return self.projects._safe_relative(root, project["template_relative_path"]), project

    def analyze_template(self, project_id: str) -> dict:
        """Extract a project-local set of report slots from the template."""
        template, _ = self._template(project_id)
        fingerprint = template_fingerprint(template)
        discovered = extract_report_slots(template)
        if not discovered:
            raise ValueError("未在模板中发现图片位置。请使用包含表格图片框的审核报告模板。")

        # The global database is intentionally supplier-blind. It retains only
        # structural template facts; captions and media names remain project data.
        serialized = [
            {
                "table_index": slot.table_index, "row_index": slot.row_index, "cell_index": slot.cell_index,
                "image_kind": slot.image_kind, "width_emu": slot.width_emu, "height_emu": slot.height_emu,
            }
            for slot in discovered
        ]
        with connect(self.projects.settings.global_db) as global_db:
            global_db.execute(
                "INSERT OR REPLACE INTO template_blueprints(fingerprint, template_name, slots_json, created_at) VALUES (?, ?, ?, ?)",
                (fingerprint, f"report-template{template.suffix.lower()}", json.dumps(serialized, ensure_ascii=False), utcnow()),
            )

        with connect(self.projects.db_path(project_id)) as db:
            checklist = [(row["id"], row["label"]) for row in db.execute("SELECT id, label FROM checklist_slots ORDER BY ordinal")]
            with connect(self.projects.settings.global_db) as global_db:
                aliases = {
                    row["label"]: json.loads(row["aliases_json"])
                    for row in global_db.execute("SELECT label, aliases_json FROM checklist_catalog")
                }
            checklist_with_aliases = [
                (slot_id, " ".join([label, *aliases.get(label, [])])) for slot_id, label in checklist
            ]
            db.execute("DELETE FROM report_slot_candidates")
            db.execute("DELETE FROM report_slot_selections")
            db.execute("DELETE FROM report_slots")
            for item in discovered:
                checklist_slot_id, confidence = best_checklist_match(item.caption, checklist_with_aliases)
                ignored_caption = item.caption.strip().lower()
                mandatory = 0 if ignored_caption in {"", "nil", "n/a"} or any(marker in ignored_caption for marker in (
                    "factory disclaimer", "confirmation of compliance", "corrective action plan",
                    "original signature", "auditor:", "number of days spent",
                )) else 1
                db.execute(
                    "INSERT INTO report_slots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()), fingerprint, item.key, item.table_index, item.row_index, item.cell_index,
                        item.image_kind, item.media_name, item.caption, item.section, item.width_emu, item.height_emu,
                        checklist_slot_id, confidence, mandatory, utcnow(),
                    ),
                )
        return {"template": template.name, "fingerprint": fingerprint, "slot_count": len(discovered)}

    def _slot_rows(self, project_id: str) -> list[sqlite3.Row]:
        with connect(self.projects.db_path(project_id)) as db:
            return db.execute("SELECT * FROM report_slots ORDER BY table_index, row_index, cell_index, id").fetchall()

    def auto_match(self, project_id: str) -> dict:
        """Select one current-project photo for every discovered report slot."""
        if not self._slot_rows(project_id):
            self.analyze_template(project_id)
        matrix, photos = self.projects._vectors_and_photo_rows(project_id)
        with connect(self.projects.db_path(project_id)) as db:
            slots = db.execute("SELECT * FROM report_slots ORDER BY table_index, row_index, cell_index, id").fetchall()
            ocr_text = {row["photo_id"]: row["text"] for row in db.execute("SELECT photo_id, text FROM ocr_results")}
            db.execute("DELETE FROM report_slot_candidates")
            db.execute("DELETE FROM report_slot_selections")

            usage: dict[str, int] = {}
            matched = 0
            for slot in slots:
                query_vector = self.projects._query_vector(project_id, slot["caption"])
                semantic = matrix @ query_vector
                desired_ratio = None
                if slot["width_emu"] and slot["height_emu"]:
                    desired_ratio = float(slot["width_emu"]) / float(slot["height_emu"])
                ranked: list[tuple[float, float, float, float, float, sqlite3.Row]] = []
                for index, photo in enumerate(photos):
                    semantic_score = float(semantic[index])
                    ocr_score = self.projects._ocr_match_score(slot["caption"], ocr_text.get(photo["id"], ""))
                    quality_score = float(photo["quality_score"])
                    photo_ratio = float(photo["width"]) / max(1.0, float(photo["height"]))
                    aspect_score = 1.0 if not desired_ratio else min(photo_ratio / desired_ratio, desired_ratio / photo_ratio)
                    duplicate_penalty = 0.05 if photo["near_duplicate_group"] else 0.0
                    reuse_penalty = min(0.12, 0.035 * usage.get(photo["id"], 0))
                    total = 0.60 * semantic_score + 0.20 * ocr_score + 0.12 * quality_score + 0.08 * aspect_score - duplicate_penalty - reuse_penalty
                    ranked.append((total, semantic_score, ocr_score, quality_score, aspect_score, photo))
                ranked.sort(key=lambda item: item[0], reverse=True)
                for rank, (total, semantic_score, ocr_score, quality_score, aspect_score, photo) in enumerate(ranked[:8], start=1):
                    db.execute(
                        "INSERT INTO report_slot_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (slot["id"], photo["id"], semantic_score, ocr_score, quality_score, aspect_score, total, rank, utcnow()),
                    )
                if ranked:
                    best = ranked[0]
                    db.execute(
                        "INSERT INTO report_slot_selections VALUES (?, ?, ?, ?, 'automatic')",
                        (slot["id"], best[5]["id"], best[0], utcnow()),
                    )
                    usage[best[5]["id"]] = usage.get(best[5]["id"], 0) + 1
                    matched += 1
        coverage = self.coverage(project_id)
        return {"matched_slots": matched, "slot_count": len(slots), "coverage": coverage}

    def coverage(self, project_id: str) -> dict:
        self.projects.project_root(project_id)
        with connect(self.projects.db_path(project_id)) as db:
            slots = db.execute(
                """SELECT rs.*, css.label AS checklist_label, sel.photo_id, sel.confidence, p.quality_flags_json
                   FROM report_slots rs
                   LEFT JOIN checklist_slots css ON css.id=rs.checklist_slot_id
                   LEFT JOIN report_slot_selections sel ON sel.report_slot_id=rs.id
                   LEFT JOIN photos p ON p.id=sel.photo_id
                   ORDER BY rs.table_index, rs.row_index, rs.cell_index"""
            ).fetchall()
            checklist = db.execute("SELECT id, label FROM checklist_slots ORDER BY ordinal").fetchall()
        mapped_ids = {row["checklist_slot_id"] for row in slots if row["checklist_slot_id"]}
        unmapped_checklist = [{"id": row["id"], "label": row["label"]} for row in checklist if row["id"] not in mapped_ids]
        unmapped_report_slots = [
            {"id": row["id"], "caption": row["caption"], "mapping_confidence": row["mapping_confidence"]}
            for row in slots if row["mandatory"] and not row["checklist_slot_id"]
        ]
        missing_images = [
            {"id": row["id"], "caption": row["caption"]}
            for row in slots if row["mandatory"] and not row["photo_id"]
        ]
        risks = [
            {
                "id": row["id"], "caption": row["caption"], "confidence": round(float(row["confidence"]), 4),
                "quality_flags": json.loads(row["quality_flags_json"] or "[]"),
            }
            for row in slots
            if row["photo_id"] and (float(row["confidence"]) < 0.30 or json.loads(row["quality_flags_json"] or "[]"))
        ]
        return {
            "analyzed_slots": len(slots),
            "selected_slots": sum(bool(row["photo_id"]) for row in slots),
            "unmapped_checklist": unmapped_checklist,
            "unmapped_report_slots": unmapped_report_slots,
            "missing_images": missing_images,
            "risks": risks,
            "ready": bool(slots) and not unmapped_checklist and not unmapped_report_slots and not missing_images,
        }

    def preflight(self, project_id: str) -> dict:
        template, _ = self._template(project_id)
        coverage = self.coverage(project_id)
        if not template.exists():
            coverage["ready"] = False
            coverage["template_error"] = "模板文件不存在"
        return coverage

    def generate(self, project_id: str) -> dict:
        root = self.projects.project_root(project_id)
        template, _ = self._template(project_id)
        preflight = self.preflight(project_id)
        if not preflight["ready"]:
            problems: list[str] = []
            if not preflight["analyzed_slots"]:
                problems.append("尚未分析报告模板")
            if preflight["unmapped_checklist"]:
                problems.append(f"{len(preflight['unmapped_checklist'])} 个必需清单项没有模板位置")
            if preflight["unmapped_report_slots"]:
                problems.append(f"{len(preflight['unmapped_report_slots'])} 个报告图片位置未映射到清单")
            if preflight["missing_images"]:
                problems.append(f"{len(preflight['missing_images'])} 个报告图片位置没有匹配图片")
            raise ValueError("；".join(problems) or "报告预检未通过")

        with connect(self.projects.db_path(project_id)) as db:
            rows = db.execute(
                """SELECT rs.*, css.label AS checklist_label, sel.photo_id, sel.confidence, sel.selected_at,
                          p.relative_path, p.sha256, p.source_filename
                   FROM report_slots rs
                   JOIN report_slot_selections sel ON sel.report_slot_id=rs.id
                   JOIN photos p ON p.id=sel.photo_id
                   LEFT JOIN checklist_slots css ON css.id=rs.checklist_slot_id
                   WHERE rs.mandatory=1
                   ORDER BY rs.table_index, rs.row_index, rs.cell_index"""
            ).fetchall()

        report_id = str(uuid.uuid4())
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = root / "outputs" / f"{template.stem}-autopick-{stamp}{template.suffix}"
        shutil.copy2(template, output)
        insertions: list[dict] = []
        manifest_items: list[dict] = []
        for row in rows:
            original = self.projects._safe_relative(root, row["relative_path"])
            if sha256_file(original) != row["sha256"]:
                raise ValueError(f"照片哈希不一致，报告已阻止：{row['source_filename']}")
            derivative = root / "derived" / "report" / f"{report_id}-{row['photo_id']}.jpg"
            make_derivative(original, derivative, 1600, 88)
            insertions.append({**dict(row), "image_path": derivative})
            manifest_items.append(
                {
                    "report_slot_id": row["id"], "checklist_slot_id": row["checklist_slot_id"],
                    "checklist_label": row["checklist_label"], "caption": row["caption"],
                    "table_index": row["table_index"], "row_index": row["row_index"], "cell_index": row["cell_index"],
                    "photo_id": row["photo_id"], "source_filename": row["source_filename"], "sha256": row["sha256"],
                    "confidence": round(float(row["confidence"]), 4), "selected_at": row["selected_at"],
                }
            )

        qa_pdf = output.with_suffix(".pdf")
        warnings = self._insert_with_word(output, insertions, qa_pdf)
        manifest = {
            "report_id": report_id, "project_id": project_id, "created_at": utcnow(),
            "template": template.name, "output": output.name, "qa_pdf": qa_pdf.name if qa_pdf.exists() else None,
            "items": manifest_items, "warnings": warnings,
        }
        manifest_path = root / "manifests" / f"report-manifest-{report_id}.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        export_path = self._write_selection_export(root, report_id, manifest_items)
        fingerprint = template_fingerprint(template)
        with connect(self.projects.db_path(project_id)) as db:
            db.execute(
                "INSERT INTO report_runs VALUES (?, ?, ?, ?, ?)",
                (report_id, fingerprint, output.relative_to(root).as_posix(), qa_pdf.relative_to(root).as_posix() if qa_pdf.exists() else None, utcnow()),
            )
            for item in manifest_items:
                db.execute(
                    "INSERT INTO report_slot_manifest VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (report_id, item["report_slot_id"], item["checklist_slot_id"], item["photo_id"], item["sha256"], item["caption"], item["confidence"], item["selected_at"]),
                )
        return {
            "output_path": str(output), "manifest_path": str(manifest_path),
            "selection_export_path": str(export_path), "qa_pdf_path": str(qa_pdf) if qa_pdf.exists() else None,
            "warnings": warnings,
        }

    @staticmethod
    def _insert_with_word(output: Path, insertions: list[dict], qa_pdf: Path) -> list[str]:
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise RuntimeError("Word COM 依赖缺失。请在Windows上安装 pywin32 和 Microsoft Word。") from exc
        warnings: list[str] = []
        pythoncom.CoInitialize()
        word = document = None
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            document = word.Documents.Open(str(output.resolve()))
            for item in insertions:
                try:
                    cell = document.Tables(item["table_index"]).Cell(item["row_index"], item["cell_index"])
                    target = cell.Range.Duplicate
                    target.End = max(target.Start, target.End - 1)
                    while target.InlineShapes.Count:
                        target.InlineShapes(1).Delete()
                    for index in range(document.Shapes.Count, 0, -1):
                        shape = document.Shapes(index)
                        try:
                            if target.Start <= shape.Anchor.Start <= target.End:
                                shape.Delete()
                        except Exception:
                            continue
                    target.Collapse(1)  # wdCollapseStart
                    inline = target.InlineShapes.AddPicture(str(Path(item["image_path"]).resolve()), False, True)
                    inline.LockAspectRatio = True
                    max_width = min(300.0, float(cell.Width) * 0.92) if float(cell.Width) > 0 else 260.0
                    max_height = 210.0
                    if float(inline.Width) > max_width:
                        inline.Width = max_width
                    if float(inline.Height) > max_height:
                        inline.Height = max_height
                    cell.Range.ParagraphFormat.Alignment = 1
                except Exception as exc:
                    raise ValueError(f"无法写入报告图片位置 {item['caption']}：{exc}") from exc
            document.Save()
            try:
                document.ExportAsFixedFormat(str(qa_pdf.resolve()), 17)
            except Exception as exc:
                warnings.append(f"PDF版式检查未生成：{exc}")
        finally:
            if document is not None:
                document.Close(SaveChanges=True)
            if word is not None:
                word.Quit()
            pythoncom.CoUninitialize()
        return warnings

    @staticmethod
    def _write_selection_export(root: Path, report_id: str, items: list[dict]) -> Path:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Report Photo Manifest"
        sheet.append(["Report caption", "Checklist item", "Table", "Row", "Cell", "Photo", "SHA-256", "Confidence", "Selected at"])
        for item in items:
            sheet.append([
                item["caption"], item["checklist_label"], item["table_index"], item["row_index"], item["cell_index"],
                item["source_filename"], item["sha256"], item["confidence"], item["selected_at"],
            ])
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(55, max(len(str(cell.value or "")) for cell in column) + 2)
        destination = root / "outputs" / f"report-photo-manifest-{report_id}.xlsx"
        workbook.save(destination)
        return destination
