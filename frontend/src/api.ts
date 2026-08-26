export type Project = {
  id: string
  factory_name: string
  created_at: string
  status: string
  photo_count: number
  indexed_count: number
  confirmed_count: number
  slot_count: number
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
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(body.detail || '请求失败')
  }
  return response.json() as Promise<T>
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
  mapBookmark: (projectId: string, slotId: string, bookmark: string) => request(`/api/projects/${projectId}/template/map`, { method: 'POST', body: JSON.stringify({ slot_id: slotId, bookmark }) }),
  bookmarks: (projectId: string) => request<{ bookmarks: string[] }>(`/api/projects/${projectId}/template/bookmarks`),
  generate: (projectId: string) => request<any>(`/api/projects/${projectId}/report/generate`, { method: 'POST' }),
  imageUrl: (projectId: string, photoId: string) => `/api/projects/${projectId}/photos/${photoId}/file?token=${encodeURIComponent(token)}`,
}
