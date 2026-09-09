export type Project = {
  id: string
  factory_name: string
  created_at: string
  status: string
  photo_count: number
  indexed_count: number
  confirmed_count: number
  slot_count: number
  template_name: string
  checklist_type_id: string
}
export type ChecklistType = { id: string; label: string; version: string; slot_count: number; sha256: string }
export type Slot = { id: string; item_key: string; ordinal: number; label: string; section?: string; confirmed_photo_ids: string[]; candidate_count: number; top_score?: number | null }
export type Candidate = { photo_id: string; filename: string; preview_url: string; score: number; semantic_score: number; quality_score: number; ocr_hit: boolean; used_in_slots: string[]; quality_flags: string[] }
export type GalleryPhoto = { photo_id: string; filename: string; preview_url: string; quality_score: number; quality_flags: string[]; embedding_status: 'indexed' | 'pending'; ocr_status: 'done' | 'pending'; ocr_text_preview: string; usage_count: number; score?: number | null; semantic_score?: number | null; ocr_hit: boolean }
export type Preflight = { ready: boolean; total_slots: number; selected_slots: number; missing_slots: number; active_overrides: number; pending_aliases: number; feedback_records: number; training_data_count: number; training_feedback_count: number; training_history_count: number; training_data_threshold: number; training_remaining: number; training_progress_percent: number; training_ready: boolean; message: string; checklist_type_id: string; factory_name: string }

let token = ''
export async function initSession() { const data = await fetch('/api/session').then(r => r.json()); token = data.token; return data }
async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', 'X-AutoPick-Token': token, ...(options.headers || {}) } })
  if (!response.ok) { const body = await response.json().catch(() => null); const detail = body?.detail; throw new Error(typeof detail === 'string' ? detail : `请求失败 (${response.status})`) }
  return response.json() as Promise<T>
}
export const api = {
  projects: () => request<Project[]>('/api/projects'),
  checklistTypes: () => request<ChecklistType[]>('/api/checklist-types'),
  createProject: (payload: { factory_name: string; gallery_path: string; checklist_type_id: string }) => request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(payload) }),
  deleteProject: (id: string, factory_name: string) => request<any>(`/api/projects/${id}`, { method: 'DELETE', body: JSON.stringify({ factory_name }) }),
  index: (id: string) => request<any>(`/api/projects/${id}/index`, { method: 'POST' }),
  match: (id: string, checklistTypeId: string) => request<any>(`/api/projects/${id}/match?checklist_type_id=${encodeURIComponent(checklistTypeId)}`, { method: 'POST' }),
  job: (id: string, jobId: string) => request<any>(`/api/projects/${id}/jobs/${jobId}`),
  checklist: (id: string, checklistTypeId: string) => request<Slot[]>(`/api/projects/${id}/checklist?checklist_type_id=${encodeURIComponent(checklistTypeId)}`),
  gallery: (id: string) => request<GalleryPhoto[]>(`/api/projects/${id}/gallery`),
  gallerySearch: (id: string, query: string) => request<GalleryPhoto[]>(`/api/projects/${id}/gallery/search`, { method: 'POST', body: JSON.stringify({ query, top_k: 120 }) }),
  ocr: (id: string) => request<any>(`/api/projects/${id}/ocr`, { method: 'POST' }),
  candidates: (id: string, slotId: string) => request<Candidate[]>(`/api/projects/${id}/slots/${slotId}/candidates`),
  search: (id: string, query: string, checklistTypeId: string) => request<Candidate[]>(`/api/projects/${id}/search?checklist_type_id=${encodeURIComponent(checklistTypeId)}`, { method: 'POST', body: JSON.stringify({ query, top_k: 30 }) }),
  confirm: (id: string, slotId: string, photoId: string, searchQuery?: string) => request(`/api/projects/${id}/slots/${slotId}/confirm`, { method: 'POST', body: JSON.stringify({ photo_id: photoId, source: 'manual', search_query: searchQuery || null }) }),
  confirmAllTop: (id: string, checklistTypeId: string) => request<any>(`/api/projects/${id}/slots/confirm-top?checklist_type_id=${encodeURIComponent(checklistTypeId)}`, { method: 'POST' }),
  preflight: (id: string, checklistTypeId: string) => request<Preflight>(`/api/projects/${id}/export/preflight?checklist_type_id=${encodeURIComponent(checklistTypeId)}`),
  exportExcel: (id: string, checklistTypeId: string) => request<any>(`/api/projects/${id}/export?allow_partial=true&checklist_type_id=${encodeURIComponent(checklistTypeId)}`, { method: 'POST' }),
  clearGallery: (id: string, factory_name: string) => request<any>(`/api/projects/${id}/gallery/clear`, { method: 'POST', body: JSON.stringify({ factory_name }) }),
  importFeedback: (id: string, feedback_path: string) => request<any>(`/api/projects/${id}/feedback/import`, { method: 'POST', body: JSON.stringify({ feedback_path }) }),
  imageUrl: (id: string, photoId: string) => `/api/projects/${id}/photos/${photoId}/file?token=${encodeURIComponent(token)}`,
}
