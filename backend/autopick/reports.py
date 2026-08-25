from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook

from backend.autopick.images import make_derivative, sha256_file
from backend.autopick.services import ProjectService, utcnow


class ReportService:
    def __init__(self, projects: ProjectService):
        self.projects = projects

    def generate(self, project_id: str) -> dict:
        root = self.projects.project_root(project_id)
        with self.projects.db_path(project_id).open("rb"):
            pass
        from backend.autopick.db import connect

        with connect(self.projects.db_path(project_id)) as db:
            project = db.execute("SELECT * FROM project LIMIT 1").fetchone()
            slots = db.execute("SELECT * FROM checklist_slots WHERE bookmark IS NOT NULL ORDER BY ordinal").fetchall()
            if not slots:
                raise ValueError("请先为至少一个清单项目配置Word书签")
            selected = {}
            for slot in slots:
                rows = db.execute(
                    """SELECT c.photo_id, c.confirmed_at, p.relative_path, p.sha256, p.source_filename
                       FROM confirmations c JOIN photos p ON p.id=c.photo_id WHERE c.slot_id=?""",
                    (slot["id"],),
                ).fetchall()
                if not rows:
                    raise ValueError(f"清单项目尚未人工确认：{slot['label']}")
                selected[slot["id"]] = rows

        report_id = str(uuid.uuid4())
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        template = self.projects._safe_relative(root, project["template_relative_path"])
        output = root / "outputs" / f"{template.stem}-{stamp}{template.suffix}"
        shutil.copy2(template, output)

        manifest_items = []
        image_by_bookmark = {}
        for slot in slots:
            photos = selected[slot["id"]]
            report_images = []
            for row in photos:
                original = self.projects._safe_relative(root, row["relative_path"])
                if sha256_file(original) != row["sha256"]:
                    raise ValueError(f"照片哈希不一致，报告已阻止：{row['source_filename']}")
                derivative = root / "derived" / "report" / f"{row['photo_id']}.jpg"
                make_derivative(original, derivative, 1600, 88)
                report_images.append(derivative)
                manifest_items.append(
                    {
                        "slot_id": slot["id"],
                        "label": slot["label"],
                        "bookmark": slot["bookmark"],
                        "photo_id": row["photo_id"],
                        "source_filename": row["source_filename"],
                        "sha256": row["sha256"],
                        "confirmed_at": row["confirmed_at"],
                    }
                )
            image_by_bookmark[slot["bookmark"]] = report_images

        warnings = self._insert_with_word(output, image_by_bookmark)
        manifest = {"report_id": report_id, "project_id": project_id, "created_at": utcnow(), "template": template.name, "items": manifest_items}
        manifest_path = root / "manifests" / f"{report_id}.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        export_path = self._write_selection_export(root, report_id, manifest_items)

        with connect(self.projects.db_path(project_id)) as db:
            for item in manifest_items:
                db.execute(
                    "INSERT INTO report_manifest VALUES (?, ?, ?, ?, ?, ?)",
                    (report_id, item["slot_id"], item["photo_id"], item["sha256"], item["bookmark"], item["confirmed_at"]),
                )
        return {"output_path": str(output), "manifest_path": str(manifest_path), "selection_export_path": str(export_path), "warnings": warnings}

    @staticmethod
    def _insert_with_word(output: Path, images: dict[str, list[Path]]) -> list[str]:
        try:
            import pythoncom
            import win32com.client
        except ImportError as exc:
            raise RuntimeError("Word COM 依赖缺失。请在Windows上安装 pywin32 和 Microsoft Word。") from exc
        warnings: list[str] = []
        pythoncom.CoInitialize()
        word = None
        document = None
        try:
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            document = word.Documents.Open(str(output.resolve()))
            for bookmark, paths in images.items():
                if not document.Bookmarks.Exists(bookmark):
                    warnings.append(f"模板中不存在书签：{bookmark}")
                    continue
                bookmark_range = document.Bookmarks(bookmark).Range
                first = paths[0]
                inline = bookmark_range.InlineShapes.AddPicture(str(first.resolve()), False, True)
                inline.LockAspectRatio = True
                inline.Width = min(inline.Width, 420)
                # Recreate the bookmark because Word consumes it when the range is replaced.
                document.Bookmarks.Add(bookmark, inline.Range)
            document.Save()
        finally:
            if document is not None:
                document.Close(SaveChanges=True)
            if word is not None:
                word.Quit()
            pythoncom.CoUninitialize()
        if warnings:
            raise ValueError("；".join(warnings))
        return warnings

    @staticmethod
    def _write_selection_export(root: Path, report_id: str, items: list[dict]) -> Path:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Photo Selections"
        sheet.append(["Checklist item", "Bookmark", "Photo", "SHA-256", "Confirmed at"])
        for item in items:
            sheet.append([item["label"], item["bookmark"], item["source_filename"], item["sha256"], item["confirmed_at"]])
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(55, max(len(str(cell.value or "")) for cell in column) + 2)
        destination = root / "outputs" / f"photo-selections-{report_id}.xlsx"
        workbook.save(destination)
        return destination
