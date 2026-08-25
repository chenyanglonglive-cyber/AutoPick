from __future__ import annotations

from pathlib import Path
import sys

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.autopick.config import Settings, load_settings
from backend.autopick.reports import ReportService
from backend.autopick.schemas import (
    CandidateResponse,
    ChecklistSlot,
    ConfirmRequest,
    JobResponse,
    ProjectCreate,
    ProjectSummary,
    RejectRequest,
    ReportResponse,
    SearchRequest,
    TemplateMappingRequest,
    HistoryImportRequest,
)
from backend.autopick.services import ProjectNotFoundError, ProjectService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    projects = ProjectService(settings)
    reports = ReportService(projects)
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
        return {"token": settings.session_token, "embedding_model": settings.embedding_model, "demo_embeddings": settings.demo_embeddings}

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "data_root": str(settings.data_root), "qwen_configured": bool(settings.dashscope_api_key)}

    @app.get("/api/projects", response_model=list[ProjectSummary], dependencies=[Depends(require_session)])
    def list_projects() -> list[dict]:
        return projects.list_projects()

    @app.post("/api/projects", response_model=ProjectSummary, dependencies=[Depends(require_session)])
    def create_project(payload: ProjectCreate) -> dict:
        try:
            return projects.create_project(
                payload.factory_name, payload.gallery_path, payload.template_path,
                payload.checklist_path, payload.history_report_path,
            )
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

    @app.get("/api/projects/{project_id}/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(require_session)])
    def get_job(project_id: str, job_id: str) -> dict:
        return projects.get_job(project_id, job_id)

    @app.get("/api/projects/{project_id}/checklist", response_model=list[ChecklistSlot], dependencies=[Depends(require_session)])
    def checklist(project_id: str) -> list[dict]:
        return projects.list_slots(project_id)

    @app.get("/api/projects/{project_id}/slots/{slot_id}/candidates", response_model=list[CandidateResponse], dependencies=[Depends(require_session)])
    def candidates(project_id: str, slot_id: str) -> list[dict]:
        try:
            return projects.candidates(project_id, slot_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/search", response_model=list[CandidateResponse], dependencies=[Depends(require_session)])
    def search(project_id: str, payload: SearchRequest) -> list[dict]:
        try:
            return projects.search(project_id, payload.query, payload.top_k)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/slots/{slot_id}/confirm", dependencies=[Depends(require_session)])
    def confirm(project_id: str, slot_id: str, payload: ConfirmRequest) -> dict:
        try:
            projects.confirm(project_id, slot_id, payload.photo_ids)
            return {"status": "confirmed"}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/slots/{slot_id}/reject", dependencies=[Depends(require_session)])
    def reject(project_id: str, slot_id: str, payload: RejectRequest) -> dict:
        projects.reject(project_id, slot_id, payload.photo_id, payload.reason)
        return {"status": "rejected"}

    @app.post("/api/projects/{project_id}/template/map", dependencies=[Depends(require_session)])
    def map_template(project_id: str, payload: TemplateMappingRequest) -> dict:
        try:
            projects.set_mapping(project_id, payload.slot_id, payload.bookmark)
            return {"status": "mapped"}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/projects/{project_id}/template/bookmarks", dependencies=[Depends(require_session)])
    def template_bookmarks(project_id: str) -> dict:
        try:
            return {"bookmarks": projects.template_bookmarks(project_id)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/history/import", dependencies=[Depends(require_session)])
    def import_history(project_id: str, payload: HistoryImportRequest) -> dict:
        try:
            source = Path(payload.report_path).expanduser().resolve()
            if not source.is_file():
                raise ValueError("历史报告文件不存在")
            root = projects.project_root(project_id)
            target = root / "history" / source.name
            if source != target:
                import shutil
                shutil.copy2(source, target)
            return projects.learn_from_report(project_id, target)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/report/generate", response_model=ReportResponse, dependencies=[Depends(require_session)])
    def generate_report(project_id: str) -> dict:
        try:
            return reports.generate(project_id)
        except (ValueError, RuntimeError) as exc:
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

    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    frontend_dist = bundle_root / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app
