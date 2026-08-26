from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    factory_name: str = Field(min_length=2, max_length=160)
    gallery_path: str
    template_path: str
    checklist_path: str | None = None
    history_report_path: str | None = None


class ProjectSummary(BaseModel):
    id: str
    factory_name: str
    created_at: datetime
    status: str
    photo_count: int = 0
    indexed_count: int = 0
    confirmed_count: int = 0
    slot_count: int = 0
    template_name: str = ""


class TemplateReplaceRequest(BaseModel):
    template_path: str = Field(min_length=1)


class JobResponse(BaseModel):
    id: str
    project_id: str
    kind: str
    status: str
    current: int = 0
    total: int = 0
    message: str | None = None
    estimated_tokens: int = 0
    actual_tokens: int = 0


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=30, ge=1, le=200)
    target_slot_id: str | None = None


class ConfirmRequest(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=8)


class RejectRequest(BaseModel):
    photo_id: str
    reason: str | None = Field(default=None, max_length=500)


class HistoryImportRequest(BaseModel):
    report_path: str


class CandidateResponse(BaseModel):
    photo_id: str
    filename: str
    preview_url: str
    score: float
    semantic_score: float
    quality_score: float
    ocr_hit: bool = False
    used_in_slots: list[str] = []
    quality_flags: list[str] = []


class GalleryPhotoResponse(BaseModel):
    photo_id: str
    filename: str
    preview_url: str
    quality_score: float
    quality_flags: list[str] = []
    embedding_status: str
    ocr_status: str
    ocr_text_preview: str = ""
    usage_count: int = 0
    score: float | None = None
    semantic_score: float | None = None
    ocr_hit: bool = False


class ChecklistSlot(BaseModel):
    id: str
    label: str
    section: str | None = None
    confirmed_photo_ids: list[str] = []
    bookmark: str | None = None
    candidate_count: int = 0
    top_score: float | None = None


class ReportResponse(BaseModel):
    output_path: str
    manifest_path: str
    selection_export_path: str
    qa_pdf_path: str | None = None
    warnings: list[str] = []


JsonDict = dict[str, Any]
