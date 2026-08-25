<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, initSession, type Candidate, type Project, type Slot } from './api'

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
const previewImage = ref<Candidate | null>(null)
const form = ref({ factory_name: '', gallery_path: '', template_path: '', checklist_path: '', history_report_path: '' })
const job = ref<any>(null)
const bookmark = ref('')
const bookmarks = ref<string[]>([])

type DesktopApi = {
  select_folder: () => Promise<string | null>
  select_word_template: () => Promise<string | null>
  select_checklist: () => Promise<string | null>
}

function desktopApi(): DesktopApi | null {
  return (window as Window & { pywebview?: { api?: DesktopApi } }).pywebview?.api || null
}

async function choose(kind: 'gallery' | 'template' | 'checklist' | 'history_report') {
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

function confidenceLevel(slot: Slot): 'confirmed' | 'high' | 'medium' | 'low' | 'none' {
  if (slot.confirmed_photo_ids && slot.confirmed_photo_ids.length > 0) return 'confirmed'
  if (slot.top_score == null) return 'none'
  if (slot.top_score >= 0.35) return 'high'
  if (slot.top_score >= 0.22) return 'medium'
  return 'low'
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
  if (!activeProject.value && projects.value.length) await openProject(projects.value[0])
}

async function openProject(project: Project) {
  activeProject.value = project
  slots.value = await api.checklist(project.id)
  bookmarks.value = (await api.bookmarks(project.id)).bookmarks
  activeSlot.value = slots.value[0] || null
  if (activeSlot.value) await selectSlot(activeSlot.value)
}

async function selectSlot(slot: Slot) {
  activeSlot.value = slot
  searchResults.value = []
  searchText.value = ''
  candidates.value = await api.candidates(activeProject.value!.id, slot.id)
  bookmark.value = slot.bookmark || ''
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
    const project = await api.createProject({ ...form.value, checklist_path: form.value.checklist_path || undefined, history_report_path: form.value.history_report_path || undefined })
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
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}

async function search() {
  if (!activeProject.value || !searchText.value.trim()) return
  loading.value = true; error.value = ''
  try { searchResults.value = await api.search(activeProject.value.id, searchText.value.trim()) }
  catch (e: any) { error.value = e.message } finally { loading.value = false }
}

async function usePhoto(candidate: Candidate) {
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

async function saveBookmark() {
  if (!activeProject.value || !activeSlot.value || !bookmark.value.trim()) return
  try {
    await api.mapBookmark(activeProject.value.id, activeSlot.value.id, bookmark.value.trim())
    activeSlot.value.bookmark = bookmark.value.trim()
    message.value = 'Word书签映射已保存。'
  } catch (e: any) { error.value = e.message }
}

async function generateReport() {
  if (!activeProject.value) return
  loading.value = true; error.value = ''
  try {
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
          {{ loading ? '处理中…' : '建立图片向量' }}
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
        <span>{{ job.current }}/{{ job.total }} · {{ job.actual_tokens || 0 }} Token</span>
      </div>
      <div class="progress"><i :style="{ width: `${progress}%` }"></i></div>
    </div>

    <section v-if="!activeProject" class="empty-state">
      <h1>开始第一个工厂项目</h1>
      <p>导入图库后将自动生成项目独立快照；各工厂照片、向量和搜索记录物理隔离。</p>
      <button class="primary-lg" @click="showCreate = true">创建工厂项目</button>
    </section>

    <section v-else class="workspace">
      <!-- 1. 项目列表面板 -->
      <aside class="projects-panel">
        <p class="eyebrow">当前工厂</p>
        <h2>{{ activeProject.factory_name }}</h2>
        <p class="muted">{{ activeProject.photo_count }} 张图 · {{ activeProject.indexed_count }} 已向量化</p>

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
      <aside class="slots-panel">
        <div class="slots-header">
          <p class="eyebrow">照片清单 ({{ slots.length }})</p>
          <span class="slots-stats">{{ activeProject.confirmed_count }}/{{ slots.length }} 已确认</span>
        </div>
        <div class="slots-scroll">
          <button
            v-for="(slot, idx) in slots"
            :key="slot.id"
            :class="{ active: slot.id === activeSlot?.id, 'is-done': slot.confirmed_photo_ids?.length }"
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

        <div class="mapping-bar">
          <span class="mapping-title">Word 模板书签位置：</span>
          <input v-model="bookmark" list="template-bookmarks" placeholder="例如 PHOTO_GATE" />
          <datalist id="template-bookmarks">
            <option v-for="name in bookmarks" :key="name" :value="name" />
          </datalist>
          <button class="secondary" @click="saveBookmark">保存位置</button>
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
      </section>

      <!-- 4. 报告导出与隔离检查面板 -->
      <aside class="review-panel">
        <p class="eyebrow">审核进度</p>
        <h3 class="stat-count">{{ activeProject.confirmed_count }}/{{ activeProject.slot_count }}</h3>
        <p class="muted">已确认清单项</p>

        <div class="progress-box">
          <div class="progress-bar-wrap">
            <div
              class="progress-bar-fill"
              :style="{ width: `${activeProject.slot_count ? Math.round((activeProject.confirmed_count / activeProject.slot_count) * 100) : 0}%` }"
            ></div>
          </div>
          <span class="progress-text">
            完成度 {{ activeProject.slot_count ? Math.round((activeProject.confirmed_count / activeProject.slot_count) * 100) : 0 }}%
          </span>
        </div>

        <div class="isolation-card">
          <strong>🔒 物理隔离已启用</strong>
          <p>当前检索与选图严格限制于本厂专属图库与数据库，绝不跨项目串图。</p>
        </div>

        <button
          class="btn-generate"
          :disabled="loading || activeProject.confirmed_count < activeProject.slot_count"
          @click="generateReport"
        >
          {{ activeProject.confirmed_count < activeProject.slot_count ? `待确认全部项 (${activeProject.confirmed_count}/${activeProject.slot_count})` : '一键生成 Word 报告' }}
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
        <label>
          历史报告学习（可选往期 .docm 案例）
          <span class="file-input">
            <input v-model="form.history_report_path" placeholder="D:\\Report\\previous-audit.docm" />
            <button type="button" class="secondary" @click="choose('history_report')">浏览</button>
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
