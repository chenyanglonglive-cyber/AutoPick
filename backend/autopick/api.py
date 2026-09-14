from __future__ import annotations

from pathlib import Path
import sys

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.autopick.config import Settings, load_settings
from backend.autopick.schemas import (
    CandidateResponse,
    GalleryImportRequest,
    GalleryPhotoResponse,
    ChecklistSlot,
    ConfirmRequest,
    FeedbackImportRequest,
    JobResponse,
    ProjectCreate,
    ProjectDeleteRequest,
    ProjectSummary,
    RejectRequest,
    SearchRequest,
)
from backend.autopick.services import ProjectNotFoundError, ProjectService
from backend.autopick.excel_checklist import type_payload
from backend.autopick.version import current_version


API_VERSION = "2026-08-26"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    projects = ProjectService(settings)
    app = FastAPI(title="AutoPick", version="0.1.0")
    app.state.settings = settings
    app.state.projects = projects
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_session(x_autopick_token: str | None = Header(default=None)) -> None:
        if x_autopick_token != settings.session_token:
            raise HTTPException(status_code=401, detail="Invalid local session token")

    @app.exception_handler(ProjectNotFoundError)
    async def project_not_found(_: Request, exc: ProjectNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.get("/api/session")
    def session() -> dict:
        # Bound to loopback only; the UI immediately keeps this value in memory.
        return {
            "token": settings.session_token,
            "embedding_model": settings.embedding_model,
            "demo_embeddings": settings.demo_embeddings,
            "version": current_version(),
        }

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "api_version": API_VERSION,
            "data_root": str(settings.data_root),
            "qwen_configured": bool(settings.dashscope_api_key),
        }

    @app.get("/api/checklist-types", dependencies=[Depends(require_session)])
    def checklist_types() -> list[dict]:
        return type_payload()

    @app.get("/api/projects", response_model=list[ProjectSummary], dependencies=[Depends(require_session)])
    def list_projects() -> list[dict]:
        return projects.list_projects()

    @app.post("/api/projects", response_model=ProjectSummary, dependencies=[Depends(require_session)])
    def create_project(payload: ProjectCreate) -> dict:
        try:
            return projects.create_project(
                payload.factory_name, payload.gallery_path,
                checklist_type_id=payload.checklist_type_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/projects/{project_id}", dependencies=[Depends(require_session)])
    def delete_project(project_id: str, payload: ProjectDeleteRequest) -> dict:
        try:
            return projects.delete_project(project_id, payload.factory_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}", response_model=ProjectSummary, dependencies=[Depends(require_session)])
    def get_project(project_id: str) -> dict:
        return projects.get_project(project_id)

    @app.post("/api/projects/{project_id}/index", response_model=JobResponse, dependencies=[Depends(require_session)])
    def index_project(project_id: str) -> dict:
        try:
            return projects.start_index(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/gallery/process", response_model=JobResponse, dependencies=[Depends(require_session)])
    def process_gallery(project_id: str) -> dict:
        try:
            return projects.start_gallery_processing(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/match", response_model=JobResponse, dependencies=[Depends(require_session)])
    def match_project(project_id: str, checklist_type_id: str | None = None) -> dict:
        try:
            return projects.start_match(project_id, checklist_type_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(require_session)])
    def get_job(project_id: str, job_id: str) -> dict:
        return projects.get_job(project_id, job_id)

    @app.post("/api/projects/{project_id}/jobs/{job_id}/cancel", response_model=JobResponse, dependencies=[Depends(require_session)])
    def cancel_job(project_id: str, job_id: str) -> dict:
        try:
            return projects.cancel_job(project_id, job_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/checklist", response_model=list[ChecklistSlot], dependencies=[Depends(require_session)])
    def checklist(project_id: str, checklist_type_id: str | None = None) -> list[dict]:
        return projects.list_slots(project_id, checklist_type_id)

    @app.get("/api/projects/{project_id}/gallery", response_model=list[GalleryPhotoResponse], dependencies=[Depends(require_session)])
    def gallery(project_id: str) -> list[dict]:
        return projects.list_gallery(project_id)

    @app.post("/api/projects/{project_id}/gallery/search", response_model=list[GalleryPhotoResponse], dependencies=[Depends(require_session)])
    def search_gallery(project_id: str, payload: SearchRequest) -> list[dict]:
        return projects.search_gallery(project_id, payload.query, payload.top_k)

    @app.post("/api/projects/{project_id}/ocr", response_model=JobResponse, dependencies=[Depends(require_session)])
    def ocr_project(project_id: str) -> dict:
        return projects.start_ocr(project_id)

    @app.post("/api/projects/{project_id}/gallery/import", dependencies=[Depends(require_session)])
    def import_gallery(project_id: str, payload: GalleryImportRequest) -> dict:
        gallery = Path(payload.gallery_path).expanduser().resolve()
        if not gallery.is_dir():
            raise HTTPException(status_code=400, detail="图库路径不是有效文件夹")
        return projects.import_gallery(project_id, gallery)

    @app.get("/api/projects/{project_id}/slots/{slot_id}/candidates", response_model=list[CandidateResponse], dependencies=[Depends(require_session)])
    def candidates(project_id: str, slot_id: str) -> list[dict]:
        try:
            return projects.candidates(project_id, slot_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/search", response_model=list[CandidateResponse], dependencies=[Depends(require_session)])
    def search(project_id: str, payload: SearchRequest, checklist_type_id: str | None = None) -> list[dict]:
        try:
            return projects.search(project_id, payload.query, payload.top_k, checklist_type_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/slots/{slot_id}/confirm", dependencies=[Depends(require_session)])
    def confirm(project_id: str, slot_id: str, payload: ConfirmRequest) -> dict:
        try:
            projects.confirm(project_id, slot_id, [payload.photo_id], payload.source, payload.search_query)
            return {"status": "confirmed"}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/slots/confirm-top", dependencies=[Depends(require_session)])
    def confirm_top_candidates(project_id: str, checklist_type_id: str | None = None) -> dict:
        try:
            return projects.confirm_all_top_candidates(project_id, checklist_type_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/slots/{slot_id}/reject", dependencies=[Depends(require_session)])
    def reject(project_id: str, slot_id: str, payload: RejectRequest) -> dict:
        projects.reject(project_id, slot_id, payload.photo_id, payload.reason)
        return {"status": "rejected"}

    @app.get("/api/projects/{project_id}/export/preflight", dependencies=[Depends(require_session)])
    def export_preflight(project_id: str, checklist_type_id: str | None = None) -> dict:
        return projects.export_preflight(project_id, checklist_type_id)

    @app.post("/api/projects/{project_id}/export", dependencies=[Depends(require_session)])
    def export_excel(project_id: str, allow_partial: bool = True, checklist_type_id: str | None = None) -> dict:
        try:
            result = projects.export_excel(project_id, allow_partial=allow_partial, checklist_type_id=checklist_type_id)
            result["download_url"] = f"/api/projects/{project_id}/outputs/{Path(result['output_path']).name}?token={settings.session_token}"
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/gallery/clear", dependencies=[Depends(require_session)])
    def clear_gallery(project_id: str, payload: dict) -> dict:
        try:
            return projects.clear_gallery(project_id, str(payload.get("factory_name", "")))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/feedback/import", dependencies=[Depends(require_session)])
    def import_feedback(project_id: str, payload: FeedbackImportRequest) -> dict:
        try:
            return projects.import_excel_feedback(project_id, payload.feedback_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/convert", response_model=ProjectSummary, dependencies=[Depends(require_session)])
    def convert_project(project_id: str, checklist_type_id: str = "quality_v1") -> dict:
        try:
            return projects.convert_project(project_id, checklist_type_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/photos/{photo_id}/file")
    def photo_file(project_id: str, photo_id: str, token: str):
        if token != settings.session_token:
            raise HTTPException(status_code=401, detail="Invalid local session token")
        try:
            path = projects.safe_photo_path(project_id, photo_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path)

    @app.get("/api/projects/{project_id}/outputs/{filename}")
    def output_file(project_id: str, filename: str, token: str):
        if token != settings.session_token:
            raise HTTPException(status_code=401, detail="Invalid local session token")
        if Path(filename).name != filename or not filename.lower().endswith(".xlsx"):
            raise HTTPException(status_code=404, detail="导出文件不存在")
        root = projects.project_root(project_id)
        path = root / "outputs" / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="导出文件不存在")
        return FileResponse(path, filename=filename, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    frontend_dist = bundle_root / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app
