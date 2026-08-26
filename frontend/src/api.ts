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
}

export type Slot = {
  id: string
  label: string
  section?: string
  confirmed_photo_ids: string[]
  bookmark?: string
  candidate_count: number
  top_score?: number | null
}

export type Candidate = {
  photo_id: string
  filename: string
  preview_url: string
  score: number
  semantic_score: number
  quality_score: number
  ocr_hit: boolean
  used_in_slots: string[]
  quality_flags: string[]
}

export type GalleryPhoto = {
  photo_id: string
  filename: string
  preview_url: string
  quality_score: number
  quality_flags: string[]
  embedding_status: 'indexed' | 'pending'
  ocr_status: 'done' | 'pending'
  ocr_text_preview: string
  usage_count: number
  score?: number | null
  semantic_score?: number | null
  ocr_hit: boolean
}

export type ReportCoverage = {
  analyzed_slots: number
  selected_slots: number
  unmapped_checklist: { id: string; label: string }[]
  unmapped_report_slots: { id: string; caption: string; mapping_confidence: number }[]
  missing_images: { id: string; caption: string }[]
  risks: { id: string; caption: string; confidence: number; quality_flags: string[] }[]
  ready: boolean
  template_error?: string
}

let token = ''

export async function initSession() {
  const response = await fetch('/api/session')
  const data = await response.json()
  token = data.token
  return data
}

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-AutoPick-Token': token, ...(options.headers || {}) },
  })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    throw new Error(formatApiError(body, response.statusText || `HTTP ${response.status}`))
  }
  return response.json() as Promise<T>
}

function formatApiError(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object') return fallback || '请求失败'
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const messages = detail.map(item => {
      if (!item || typeof item !== 'object') return String(item)
      const error = item as { loc?: unknown[]; msg?: unknown }
      const field = Array.isArray(error.loc) ? error.loc.at(-1) : null
      const message = typeof error.msg === 'string' ? error.msg : JSON.stringify(item)
      return field ? `${String(field)}：${message}` : message
    }).filter(Boolean)
    if (messages.length) return `请求参数有误：${messages.join('；')}`
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return fallback || '请求失败'
}

export const api = {
  projects: () => request<Project[]>('/api/projects'),
  createProject: (payload: { factory_name: string; gallery_path: string; template_path: string; checklist_path?: string; history_report_path?: string }) =>
    request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(payload) }),
  index: (projectId: string) => request<any>(`/api/projects/${projectId}/index`, { method: 'POST' }),
  job: (projectId: string, jobId: string) => request<any>(`/api/projects/${projectId}/jobs/${jobId}`),
  checklist: (projectId: string) => request<Slot[]>(`/api/projects/${projectId}/checklist`),
  gallery: (projectId: string) => request<GalleryPhoto[]>(`/api/projects/${projectId}/gallery`),
  gallerySearch: (projectId: string, query: string, top_k = 120) => request<GalleryPhoto[]>(`/api/projects/${projectId}/gallery/search`, { method: 'POST', body: JSON.stringify({ query, top_k }) }),
  ocr: (projectId: string) => request<any>(`/api/projects/${projectId}/ocr`, { method: 'POST' }),
  candidates: (projectId: string, slotId: string) => request<Candidate[]>(`/api/projects/${projectId}/slots/${slotId}/candidates`),
  search: (projectId: string, query: string, top_k = 30) => request<Candidate[]>(`/api/projects/${projectId}/search`, { method: 'POST', body: JSON.stringify({ query, top_k }) }),
  confirm: (projectId: string, slotId: string, photoIds: string[]) => request(`/api/projects/${projectId}/slots/${slotId}/confirm`, { method: 'POST', body: JSON.stringify({ photo_ids: photoIds }) }),
  confirmAllTop: (projectId: string) => request<{ selected_count: number; skipped_confirmed_count: number; unmatched_count: number; message: string }>(`/api/projects/${projectId}/slots/confirm-top`, { method: 'POST' }),
  analyzeTemplate: (projectId: string) => request<{ template: string; fingerprint: string; slot_count: number }>(`/api/projects/${projectId}/template/analyze`, { method: 'POST' }),
  replaceTemplate: (projectId: string, templatePath: string) => request<{ template_name: string }>(`/api/projects/${projectId}/template/replace`, { method: 'POST', body: JSON.stringify({ template_path: templatePath }) }),
  matchReport: (projectId: string) => request<{ matched_slots: number; slot_count: number; coverage: ReportCoverage }>(`/api/projects/${projectId}/report/match`, { method: 'POST' }),
  reportCoverage: (projectId: string) => request<ReportCoverage>(`/api/projects/${projectId}/report/coverage`),
  preflight: (projectId: string) => request<ReportCoverage>(`/api/projects/${projectId}/report/preflight`, { method: 'POST' }),
  generate: (projectId: string) => request<any>(`/api/projects/${projectId}/report/generate`, { method: 'POST' }),
  imageUrl: (projectId: string, photoId: string) => `/api/projects/${projectId}/photos/${photoId}/file?token=${encodeURIComponent(token)}`,
}
