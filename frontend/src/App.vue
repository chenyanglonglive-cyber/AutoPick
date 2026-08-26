<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, initSession, type Candidate, type GalleryPhoto, type Project, type ReportCoverage, type Slot } from './api'

const projects = ref<Project[]>([])
const activeProject = ref<Project | null>(null)
const slots = ref<Slot[]>([])
const activeSlot = ref<Slot | null>(null)
const candidates = ref<Candidate[]>([])
const searchText = ref('')
const searchResults = ref<Candidate[]>([])
const error = ref('')
const message = ref('')
const loading = ref(false)
const showCreate = ref(false)
const previewImage = ref<Candidate | GalleryPhoto | null>(null)
const form = ref({ factory_name: '', gallery_path: '', template_path: '', checklist_path: '' })
const job = ref<any>(null)
const reportCoverage = ref<ReportCoverage | null>(null)
const activeView = ref<'checklist' | 'gallery'>('checklist')
const galleryPhotos = ref<GalleryPhoto[]>([])
const galleryResults = ref<GalleryPhoto[]>([])
const galleryQuery = ref('')

type DesktopApi = {
  select_folder: () => Promise<string | null>
  select_word_template: () => Promise<string | null>
  select_checklist: () => Promise<string | null>
}

function desktopApi(): DesktopApi | null {
  return (window as Window & { pywebview?: { api?: DesktopApi } }).pywebview?.api || null
}

async function choose(kind: 'gallery' | 'template' | 'checklist') {
  const bridge = desktopApi()
  if (!bridge) {
    message.value = '浏览器开发模式请直接输入路径；打包后的桌面版会打开Windows选择窗口。'
    return
  }
  const selected = kind === 'gallery'
    ? await bridge.select_folder()
    : kind === 'checklist' ? await bridge.select_checklist() : await bridge.select_word_template()
  if (selected) form.value[`${kind}_path` as keyof typeof form.value] = selected
}

function matchConfidenceLevel(slot: Slot): 'high' | 'medium' | 'low' | 'none' {
  if (slot.top_score == null) return 'none'
  if (slot.top_score >= 0.35) return 'high'
  if (slot.top_score >= 0.22) return 'medium'
  return 'low'
}

function confidenceLevel(slot: Slot): 'confirmed' | 'high' | 'medium' | 'low' | 'none' {
  if (slot.confirmed_photo_ids && slot.confirmed_photo_ids.length > 0) return 'confirmed'
  return matchConfidenceLevel(slot)
}

function confidenceText(slot: Slot): string {
  const level = confidenceLevel(slot)
  if (level === 'confirmed') return '已确认'
  if (level === 'high') return '高置信度'
  if (level === 'medium') return '中置信度'
  if (level === 'low') return '低置信度'
  return '未匹配'
}

const progress = computed(() => job.value?.total ? Math.round((job.value.current / job.value.total) * 100) : 0)

// Ordered candidates: Confirmed photo placed #1 if exists, otherwise Top 1 recommended placed #1, backups follow
const orderedPhotos = computed(() => {
  const list = searchResults.value.length ? searchResults.value : candidates.value
  if (!list.length) return []
  if (!activeSlot.value) return list

  const confirmedIds = new Set(activeSlot.value.confirmed_photo_ids || [])
  if (!confirmedIds.size) {
    return list
  }

  // Put confirmed photo at the very front
  const confirmedList = list.filter(p => confirmedIds.has(p.photo_id))
  const otherList = list.filter(p => !confirmedIds.has(p.photo_id))
  return [...confirmedList, ...otherList]
})

function photoBadge(photo: Candidate, index: number): { text: string; type: 'confirmed' | 'primary' | 'backup' } {
  const isConfirmed = activeSlot.value?.confirmed_photo_ids?.includes(photo.photo_id)
  if (isConfirmed) {
    return { text: '★ 当前已选用', type: 'confirmed' }
  }
  if (!searchResults.value.length && index === 0 && (!activeSlot.value?.confirmed_photo_ids?.length)) {
    return { text: '推荐首选 (Top 1)', type: 'primary' }
  }
  const backupNum = activeSlot.value?.confirmed_photo_ids?.length ? index : index
  return { text: `备选 ${backupNum}`, type: 'backup' }
}

function imageUrl(photoId: string) {
  if (!activeProject.value) return ''
  return api.imageUrl(activeProject.value.id, photoId)
}

async function refreshProjects() {
  projects.value = await api.projects()
  if (activeProject.value) {
    activeProject.value = projects.value.find(project => project.id === activeProject.value?.id) || null
  } else if (projects.value.length) {
    await openProject(projects.value[0])
  }
}

async function openProject(project: Project) {
  activeProject.value = project
  slots.value = await api.checklist(project.id)
  reportCoverage.value = await api.reportCoverage(project.id)
  activeSlot.value = slots.value[0] || null
  if (activeSlot.value) await selectSlot(activeSlot.value)
  if (activeView.value === 'gallery') await openGallery()
}

async function selectSlot(slot: Slot) {
  activeView.value = 'checklist'
  activeSlot.value = slot
  searchResults.value = []
  searchText.value = ''
  candidates.value = await api.candidates(activeProject.value!.id, slot.id)
}

const displayedGallery = computed(() => galleryResults.value.length ? galleryResults.value : galleryPhotos.value)
const indexedGalleryCount = computed(() => galleryPhotos.value.filter(photo => photo.embedding_status === 'indexed').length)
const ocrGalleryCount = computed(() => galleryPhotos.value.filter(photo => photo.ocr_status === 'done').length)

async function openGallery() {
  if (!activeProject.value) return
  activeView.value = 'gallery'
  galleryResults.value = []
  galleryQuery.value = ''
  loading.value = true; error.value = ''
  try { galleryPhotos.value = await api.gallery(activeProject.value.id) }
  catch (e: any) { error.value = e.message } finally { loading.value = false }
}

async function searchGallery() {
  if (!activeProject.value || !galleryQuery.value.trim()) return
  loading.value = true; error.value = ''
  try { galleryResults.value = await api.gallerySearch(activeProject.value.id, galleryQuery.value.trim()) }
  catch (e: any) { error.value = e.message } finally { loading.value = false }
}

async function startOcr() {
  if (!activeProject.value) return
  loading.value = true; error.value = ''
  try {
    job.value = await api.ocr(activeProject.value.id)
    while (job.value.status === 'queued' || job.value.status === 'running') {
      await new Promise(resolve => setTimeout(resolve, 1000))
      job.value = await api.job(activeProject.value.id, job.value.id)
    }
    if (job.value.status !== 'completed') throw new Error(job.value.message)
    galleryPhotos.value = await api.gallery(activeProject.value.id)
    galleryResults.value = []
    message.value = '图库文字识别已完成，可以按证书编号、文件名或现场标识搜索。'
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}

const currentSlotIndex = computed(() => {
  if (!activeSlot.value) return -1
  return slots.value.findIndex(s => s.id === activeSlot.value!.id)
})

async function prevSlot() {
  if (currentSlotIndex.value > 0) {
    await selectSlot(slots.value[currentSlotIndex.value - 1])
  }
}

async function nextSlot() {
  if (currentSlotIndex.value >= 0 && currentSlotIndex.value < slots.value.length - 1) {
    await selectSlot(slots.value[currentSlotIndex.value + 1])
  }
}

async function createProject() {
  loading.value = true; error.value = ''
  try {
    const project = await api.createProject({ ...form.value, checklist_path: form.value.checklist_path || undefined })
    await refreshProjects(); await openProject(project)
    showCreate.value = false
    message.value = '项目已创建，图库已冻结为独立快照。'
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}

async function startIndex() {
  if (!activeProject.value) return
  loading.value = true; error.value = ''
  try {
    job.value = await api.index(activeProject.value.id)
    while (job.value.status === 'queued' || job.value.status === 'running') {
      await new Promise(resolve => setTimeout(resolve, 1000))
      job.value = await api.job(activeProject.value.id, job.value.id)
    }
    if (job.value.status !== 'completed') throw new Error(job.value.message)
    await refreshProjects()
    if (activeProject.value) {
      slots.value = await api.checklist(activeProject.value.id)
      if (activeSlot.value) {
        await selectSlot(activeSlot.value)
      }
    }
    message.value = '图片向量化与全清单自动匹配已完成！'
  } catch (e: any) {
    error.value = `${e.message}；已完成的向量化进度已保留，请检查网络后重试。`
    await refreshProjects()
  } finally { loading.value = false }
}

async function search() {
  if (!activeProject.value || !searchText.value.trim()) return
  loading.value = true; error.value = ''
  try { searchResults.value = await api.search(activeProject.value.id, searchText.value.trim()) }
  catch (e: any) { error.value = e.message } finally { loading.value = false }
}

async function usePhoto(candidate: Candidate | GalleryPhoto) {
  if (!activeProject.value || !activeSlot.value) return
  try {
    await api.confirm(activeProject.value.id, activeSlot.value.id, [candidate.photo_id])
    const slot = slots.value.find(item => item.id === activeSlot.value!.id)
    if (slot) {
      slot.confirmed_photo_ids = [candidate.photo_id]
      if (activeProject.value) {
        activeProject.value.confirmed_count = slots.value.filter(s => s.confirmed_photo_ids.length > 0).length
      }
    }
    message.value = `已确认：${candidate.filename}`
  } catch (e: any) { error.value = e.message }
}

async function confirmAllTop() {
  if (!activeProject.value) return
  loading.value = true; error.value = ''
  try {
    const result = await api.confirmAllTop(activeProject.value.id)
    projects.value = await api.projects()
    activeProject.value = projects.value.find(project => project.id === activeProject.value!.id) || activeProject.value
    slots.value = await api.checklist(activeProject.value.id)
    activeSlot.value = slots.value.find(slot => slot.id === activeSlot.value?.id) || slots.value[0] || null
    if (activeSlot.value) await selectSlot(activeSlot.value)
    message.value = result.message
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}

async function analyzeReportTemplate() {
  if (!activeProject.value) return
  loading.value = true; error.value = ''
  try {
    const result = await api.analyzeTemplate(activeProject.value.id)
    reportCoverage.value = await api.reportCoverage(activeProject.value.id)
    message.value = `已识别 ${result.slot_count} 个报告图片位置，正在按清单检查覆盖关系。`
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}

async function replaceReportTemplate() {
  if (!activeProject.value) return
  const bridge = desktopApi()
  if (!bridge) {
    error.value = '请在桌面版中选择 Word 模板。'
    return
  }
  const selected = await bridge.select_word_template()
  if (!selected) return

  loading.value = true; error.value = ''
  try {
    const projectId = activeProject.value.id
    const result = await api.replaceTemplate(projectId, selected)
    await refreshProjects()
    const analysis = await api.analyzeTemplate(projectId)
    reportCoverage.value = await api.reportCoverage(projectId)
    message.value = `已使用模板“${result.template_name}”，识别到 ${analysis.slot_count} 个图片位置，请重新自动匹配。`
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}

async function matchReport() {
  if (!activeProject.value) return
  loading.value = true; error.value = ''
  try {
    const result = await api.matchReport(activeProject.value.id)
    reportCoverage.value = result.coverage
    message.value = `已自动匹配 ${result.matched_slots}/${result.slot_count} 个报告图片位置。`
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}

async function refreshReportCoverage() {
  if (!activeProject.value) return
  loading.value = true; error.value = ''
  try {
    reportCoverage.value = await api.preflight(activeProject.value.id)
    message.value = reportCoverage.value.ready ? '报告预检通过，可以生成正式 Word 报告。' : '报告预检发现缺口，请先查看右侧清单。'
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}

async function generateReport() {
  if (!activeProject.value) return
  loading.value = true; error.value = ''
  try {
    reportCoverage.value = await api.preflight(activeProject.value.id)
    if (!reportCoverage.value.ready) throw new Error('报告预检未通过：请先补齐右侧显示的模板位置或清单缺口。')
    const result = await api.generate(activeProject.value.id)
    message.value = `报告已生成：${result.output_path}`
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}

onMounted(async () => { await initSession(); await refreshProjects() })
</script>

<template>
  <main class="app-root">
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark">A</span>
        <strong>AutoPick</strong>
        <small>工厂审核报告选图系统</small>
      </div>
      <div class="actions">
        <button class="secondary" @click="showCreate = true">新建工厂项目</button>
        <button :disabled="!activeProject || loading" @click="startIndex">
          {{ loading ? '处理中…' : ((activeProject?.indexed_count ?? 0) >= (activeProject?.photo_count ?? 1) ? '重新匹配清单' : '建立图片向量') }}
        </button>
        <button
          class="export-top"
          :disabled="!activeProject || loading || !reportCoverage?.ready"
          @click="generateReport"
        >
          导出 Word 报告
        </button>
      </div>
    </header>

    <div v-if="error" class="notice error">
      <span>{{ error }}</span>
      <button class="notice-close" @click="error = ''">×</button>
    </div>
    <div v-if="message" class="notice success">
      <span>{{ message }}</span>
      <button class="notice-close" @click="message = ''">×</button>
    </div>

    <div v-if="job && (job.status === 'running' || job.status === 'queued')" class="job-banner">
      <div class="job-info">
        <strong>{{ job.message }}</strong>
        <span>{{ job.current }}/{{ job.total }} · {{ progress }}% · {{ job.actual_tokens || 0 }} Token</span>
      </div>
      <div class="progress"><i :style="{ width: `${progress}%` }"></i></div>
    </div>

    <section v-if="!activeProject" class="empty-state">
      <h1>开始第一个工厂项目</h1>
      <p>导入图库后将自动生成项目独立快照；各工厂照片、向量和搜索记录物理隔离。</p>
      <button class="primary-lg" @click="showCreate = true">创建工厂项目</button>
    </section>

    <section v-else :class="['workspace', { 'gallery-workspace': activeView === 'gallery' }]">
      <!-- 1. 项目列表面板 -->
      <aside class="projects-panel">
        <p class="eyebrow">当前工厂</p>
        <h2>{{ activeProject.factory_name }}</h2>
        <p class="muted">{{ activeProject.photo_count }} 张图 · {{ activeProject.indexed_count }} 已向量化</p>

        <div class="project-nav" aria-label="项目功能">
          <button :class="{ active: activeView === 'checklist' }" @click="activeView = 'checklist'">审核清单</button>
          <button :class="{ active: activeView === 'gallery' }" @click="openGallery">
            图库
            <small>{{ activeProject.photo_count }} 张 · {{ activeProject.indexed_count }} 已向量化</small>
          </button>
        </div>

        <p class="eyebrow mt-16">项目切换</p>
        <div class="project-list">
          <button
            v-for="project in projects"
            :key="project.id"
            :class="{ active: project.id === activeProject.id }"
            @click="openProject(project)"
          >
            <span class="project-name">{{ project.factory_name }}</span>
            <small>{{ project.confirmed_count }}/{{ project.slot_count }} 已确认</small>
          </button>
        </div>
      </aside>

      <!-- 2. 照片清单面板 (支持长清单独立垂直滚动 + 置信度标签) -->
      <aside v-if="activeView === 'checklist'" class="slots-panel">
        <div class="slots-header">
          <p class="eyebrow">照片清单 ({{ slots.length }})</p>
          <span class="slots-stats">{{ activeProject.confirmed_count }}/{{ slots.length }} 已确认</span>
        </div>
        <div class="slots-bulk-action">
          <button class="btn-select-all" :disabled="loading" @click="confirmAllTop">
            全部选中最高匹配
          </button>
          <small>仅补全未确认项，不覆盖人工确认或拒绝项。</small>
        </div>
        <div class="slots-scroll">
          <button
            v-for="(slot, idx) in slots"
            :key="slot.id"
            :class="[
              `confidence-line-${matchConfidenceLevel(slot)}`,
              { active: slot.id === activeSlot?.id, 'is-done': slot.confirmed_photo_ids?.length }
            ]"
            @click="selectSlot(slot)"
          >
            <div class="slot-btn-content">
              <span class="slot-index">{{ idx + 1 }}</span>
              <span class="slot-label" :title="slot.label">{{ slot.label }}</span>
            </div>
            <span :class="['confidence-badge', `confidence-${confidenceLevel(slot)}`]">
              {{ confidenceText(slot) }}
            </span>
          </button>
        </div>
      </aside>

      <!-- 3. 主审阅工作区 (首选/已选放第一位，备选依次排列) -->
      <section class="content-panel">
        <template v-if="activeView === 'checklist'">
        <div class="slot-heading">
          <div>
            <p class="eyebrow">{{ activeSlot?.section || '现场检查项' }} · 第 {{ currentSlotIndex + 1 }} / {{ slots.length }} 项</p>
            <h1>{{ activeSlot?.label }}</h1>
          </div>
          <div class="slot-nav-actions">
            <button class="secondary nav-btn" :disabled="currentSlotIndex <= 0" @click="prevSlot">◀ 上一项</button>
            <button class="secondary nav-btn" :disabled="currentSlotIndex >= slots.length - 1" @click="nextSlot">下一项 ▶</button>
          </div>
        </div>

        <div class="search-bar">
          <input
            v-model="searchText"
            @keyup.enter="search"
            placeholder="自然语言搜图，例如：车间入口的消火栓、特种设备检验合格证..."
          />
          <button @click="search">在当前图库搜索</button>
          <button v-if="searchResults.length" class="secondary" @click="searchResults = []; searchText = ''">
            返回推荐列表
          </button>
        </div>

        <div class="section-title-bar">
          <h3>{{ searchResults.length ? `“${searchText}” 的搜索结果 (${searchResults.length})` : '候选照片匹配结果 (按匹配度排序)' }}</h3>
          <small class="tip">提示：首张为推荐首选/已确认图，点击图片可放大查看细节</small>
        </div>

        <div v-if="!orderedPhotos.length" class="no-photos">
          <p>暂无候选照片。请先点击右上角 <strong>「建立图片向量」</strong> 或使用上方搜索框检索。</p>
        </div>

        <div v-else class="photo-grid">
          <article
            v-for="(photo, index) in orderedPhotos"
            :key="photo.photo_id"
            :class="[
              'photo-card',
              {
                'card-confirmed': activeSlot?.confirmed_photo_ids?.includes(photo.photo_id),
                'card-primary': !activeSlot?.confirmed_photo_ids?.includes(photo.photo_id) && index === 0 && !searchResults.length
              }
            ]"
          >
            <div class="card-badge" :class="`badge-${photoBadge(photo, index).type}`">
              {{ photoBadge(photo, index).text }}
            </div>

            <div class="img-wrapper" @click="previewImage = photo">
              <img :src="imageUrl(photo.photo_id)" :alt="photo.filename" loading="lazy" />
              <div class="img-overlay"><span>🔍 点击放大</span></div>
            </div>

            <div class="photo-meta">
              <strong :title="photo.filename">{{ photo.filename }}</strong>
              <div class="meta-row">
                <span>相似度 {{ photo.semantic_score?.toFixed(3) || '—' }}</span>
                <span>清晰度 {{ Math.round((photo.quality_score || 0) * 100) }}</span>
              </div>
              <em v-if="photo.quality_flags && photo.quality_flags.length">
                {{ photo.quality_flags.join(' · ') }}
              </em>
              <small v-if="photo.used_in_slots && photo.used_in_slots.length > 0">
                ⚠️ 已用于其他 {{ photo.used_in_slots.length }} 个清单项
              </small>

              <button
                v-if="activeSlot?.confirmed_photo_ids?.includes(photo.photo_id)"
                class="btn-confirmed"
                disabled
              >
                ✓ 当前已选定
              </button>
              <button
                v-else
                class="btn-use"
                @click="usePhoto(photo)"
              >
                选用此照片
              </button>
            </div>
          </article>
        </div>
        </template>

        <template v-else>
          <div class="gallery-heading">
            <div>
              <p class="eyebrow">当前工厂专属图库</p>
              <h1>图库浏览</h1>
              <p class="muted">{{ galleryPhotos.length }} 张照片 · {{ indexedGalleryCount }} 已向量化 · {{ ocrGalleryCount }} 已完成文字识别</p>
            </div>
            <button class="secondary" :disabled="loading" @click="openGallery">刷新图库</button>
          </div>

          <div class="gallery-search-bar">
            <input
              v-model="galleryQuery"
              @keyup.enter="searchGallery"
              placeholder="搜索画面内容或图片内文字，例如：ISO9001、营业执照、消防栓"
            />
            <button :disabled="loading || !galleryQuery.trim()" @click="searchGallery">搜索图库</button>
            <button v-if="galleryResults.length" class="secondary" @click="galleryResults = []; galleryQuery = ''">显示全部</button>
          </div>

          <div class="ocr-callout">
            <div>
              <strong>图片内文字搜索</strong>
              <p>OCR 按项目保存且只在本厂图库内检索。未识别照片不会命中文字搜索。</p>
            </div>
            <button :disabled="loading || ocrGalleryCount >= galleryPhotos.length" @click="startOcr">
              {{ ocrGalleryCount >= galleryPhotos.length ? '文字识别已完成' : `识别剩余文字 (${galleryPhotos.length - ocrGalleryCount})` }}
            </button>
          </div>

          <div class="section-title-bar">
            <h3>{{ galleryResults.length ? `“${galleryQuery}” 的搜索结果 (${galleryResults.length})` : `全部图库 (${galleryPhotos.length})` }}</h3>
            <small class="tip">语义搜索与 OCR 文字命中会同时排序；文字精确命中优先显示。</small>
          </div>

          <div v-if="!displayedGallery.length" class="no-photos">
            <p>图库中暂无可显示的照片。</p>
          </div>
          <div v-else class="photo-grid gallery-grid">
            <article v-for="photo in displayedGallery" :key="photo.photo_id" class="photo-card gallery-card">
              <div class="img-wrapper" @click="previewImage = photo">
                <img :src="imageUrl(photo.photo_id)" :alt="photo.filename" loading="lazy" />
                <div class="img-overlay"><span>🔍 点击放大</span></div>
              </div>
              <div class="photo-meta">
                <strong :title="photo.filename">{{ photo.filename }}</strong>
                <div class="gallery-status-row">
                  <span :class="['status-pill', photo.embedding_status]">{{ photo.embedding_status === 'indexed' ? '向量已完成' : '待向量化' }}</span>
                  <span :class="['status-pill', photo.ocr_status]">{{ photo.ocr_status === 'done' ? '文字已识别' : '文字待识别' }}</span>
                </div>
                <div class="meta-row">
                  <span v-if="photo.semantic_score != null">相似度 {{ photo.semantic_score.toFixed(3) }}</span>
                  <span v-else>清晰度 {{ Math.round(photo.quality_score * 100) }}</span>
                  <span v-if="photo.ocr_hit" class="ocr-hit">文字命中</span>
                </div>
                <p v-if="photo.ocr_text_preview" class="ocr-preview" :title="photo.ocr_text_preview">{{ photo.ocr_text_preview }}</p>
                <em v-if="photo.quality_flags.length">{{ photo.quality_flags.join(' · ') }}</em>
                <small v-if="photo.usage_count">已用于 {{ photo.usage_count }} 个报告位置</small>
                <button v-if="activeSlot" class="btn-use" @click="usePhoto(photo)">选为当前清单照片</button>
              </div>
            </article>
          </div>
        </template>
      </section>

      <!-- 4. 报告自动匹配、预检与导出 -->
      <aside class="review-panel">
        <p class="eyebrow">报告交付</p>
        <h3 class="stat-count">{{ reportCoverage?.selected_slots || 0 }}/{{ reportCoverage?.analyzed_slots || 0 }}</h3>
        <p class="muted">已自动匹配报告位置</p>

        <div class="progress-box">
          <div class="progress-bar-wrap">
            <div
              class="progress-bar-fill"
              :style="{ width: `${reportCoverage?.analyzed_slots ? Math.round(((reportCoverage?.selected_slots || 0) / reportCoverage.analyzed_slots) * 100) : 0}%` }"
            ></div>
          </div>
          <span class="progress-text">
            槽位覆盖 {{ reportCoverage?.analyzed_slots ? Math.round(((reportCoverage?.selected_slots || 0) / reportCoverage.analyzed_slots) * 100) : 0 }}%
          </span>
        </div>

        <div class="isolation-card">
          <strong>🔒 物理隔离已启用</strong>
          <p>当前检索与选图严格限制于本厂专属图库与数据库，绝不跨项目串图。</p>
        </div>

        <div class="report-actions">
          <button class="secondary" :disabled="loading" @click="replaceReportTemplate">选择/更换模板</button>
          <small class="template-hint">当前：{{ activeProject.template_name || '未选择模板' }}</small>
          <button class="secondary" :disabled="loading" @click="analyzeReportTemplate">1. 分析报告模板</button>
          <button :disabled="loading || !reportCoverage?.analyzed_slots" @click="matchReport">2. 自动匹配报告图片</button>
          <button class="secondary" :disabled="loading || !reportCoverage?.analyzed_slots" @click="refreshReportCoverage">3. 检查覆盖与缺口</button>
        </div>

        <div v-if="reportCoverage" class="coverage-card" :class="{ ready: reportCoverage.ready }">
          <strong>{{ reportCoverage.ready ? '✓ 报告预检通过' : '⚠ 需要处理的缺口' }}</strong>
          <p>未映射清单 {{ reportCoverage.unmapped_checklist.length }} 项 · 未映射报告位置 {{ reportCoverage.unmapped_report_slots.length }} 项 · 缺图 {{ reportCoverage.missing_images.length }} 项 · 风险 {{ reportCoverage.risks.length }} 项</p>
          <small v-if="reportCoverage.unmapped_checklist.length">例如：{{ reportCoverage.unmapped_checklist.slice(0, 2).map(item => item.label).join('、') }}</small>
          <small v-else-if="reportCoverage.unmapped_report_slots.length">例如：{{ reportCoverage.unmapped_report_slots.slice(0, 2).map(item => item.caption).join('、') }}</small>
          <small v-else-if="reportCoverage.risks.length">低置信度或质量风险会随 Manifest 一并记录。</small>
        </div>

        <button class="btn-generate" :disabled="loading || !reportCoverage?.ready" @click="generateReport">
          {{ reportCoverage?.ready ? '4. 生成 Word 报告' : '预检未通过，不能导出' }}
        </button>
      </aside>
    </section>

    <!-- 图片高清大图预览 Lightbox -->
    <div v-if="previewImage" class="lightbox-wrap" @click="previewImage = null">
      <div class="lightbox-content" @click.stop>
        <div class="lightbox-header">
          <strong>{{ previewImage.filename }}</strong>
          <button class="icon-close" @click="previewImage = null">✕</button>
        </div>
        <div class="lightbox-body">
          <img :src="imageUrl(previewImage.photo_id)" :alt="previewImage.filename" />
        </div>
        <div class="lightbox-footer">
          <span>相似度: {{ previewImage.semantic_score?.toFixed(3) }}</span>
          <span>清晰度评分: {{ Math.round((previewImage.quality_score || 0) * 100) }}</span>
          <button class="primary" @click="usePhoto(previewImage); previewImage = null">
            选用这张照片并返回
          </button>
        </div>
      </div>
    </div>

    <!-- 新建工厂项目弹窗 -->
    <div v-if="showCreate" class="modal-wrap">
      <form class="modal" @submit.prevent="createProject">
        <div class="modal-title">
          <h2>新建工厂项目</h2>
          <button type="button" class="icon-close" @click="showCreate = false">✕</button>
        </div>
        <label>
          工厂名称
          <input v-model="form.factory_name" required placeholder="例如：浙江某某科技有限公司" />
        </label>
        <label>
          本工厂图库文件夹
          <span class="file-input">
            <input v-model="form.gallery_path" required placeholder="D:\\Audit\\Photos" />
            <button type="button" class="secondary" @click="choose('gallery')">浏览</button>
          </span>
        </label>
        <label>
          空白 Word 报告模板
          <span class="file-input">
            <input v-model="form.template_path" required placeholder="D:\\Templates\\audit-template.docm" />
            <button type="button" class="secondary" @click="choose('template')">浏览</button>
          </span>
        </label>
        <label>
          审核照片清单（可选 .docx）
          <span class="file-input">
            <input v-model="form.checklist_path" placeholder="D:\\AutoPick\\Photo report list.docx" />
            <button type="button" class="secondary" @click="choose('checklist')">浏览</button>
          </span>
        </label>
        <p class="modal-tip">
          💡 创建后，图库将自动复制为项目独立快照；其他工厂的照片、向量与搜索历史不会与本项目产生任何交互。
        </p>
        <button :disabled="loading" type="submit" class="modal-submit">创建并初始化图库</button>
      </form>
    </div>
  </main>
</template>
