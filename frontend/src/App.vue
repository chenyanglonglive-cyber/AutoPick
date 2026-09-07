<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, initSession, type Candidate, type ChecklistType, type GalleryPhoto, type Project, type Slot, type Preflight } from './api'

const projects = ref<Project[]>([])
const activeProject = ref<Project | null>(null)
const checklistTypes = ref<ChecklistType[]>([])
const slots = ref<Slot[]>([])
const activeSlot = ref<Slot | null>(null)
const candidates = ref<Candidate[]>([])
const galleryPhotos = ref<GalleryPhoto[]>([])
const galleryResults = ref<GalleryPhoto[]>([])
const searchResults = ref<Candidate[]>([])
const searchText = ref('')
const galleryQuery = ref('')
const activeView = ref<'checklist' | 'gallery'>('checklist')
const loading = ref(false)
const error = ref('')
const message = ref('')
const showCreate = ref(false)
const previewImage = ref<Candidate | GalleryPhoto | null>(null)
const preflight = ref<Preflight | null>(null)
const job = ref<any>(null)
const form = ref({ factory_name: '', gallery_path: '', checklist_type_id: 'quality_v1' })

type DesktopApi = { select_folder: () => Promise<string | null>; select_feedback_file?: () => Promise<string | null>; open_data_folder?: (projectId: string) => Promise<boolean> }
function desktopApi(): DesktopApi | null { return (window as any).pywebview?.api || null }
async function chooseFolder() { const selected = await desktopApi()?.select_folder(); if (selected) form.value.gallery_path = selected }
async function openDataFolder() { if (activeProject.value && desktopApi()?.open_data_folder) await desktopApi()!.open_data_folder!(activeProject.value.id) }
function imageUrl(photoId: string) { return activeProject.value ? api.imageUrl(activeProject.value.id, photoId) : '' }
function confidenceClass(slot: Slot) { if (slot.top_score == null) return 'none'; if (slot.top_score >= .35) return 'high'; if (slot.top_score >= .22) return 'medium'; return 'low' }
const displayedCandidates = computed(() => searchResults.value.length ? searchResults.value : candidates.value)
const displayedGallery = computed(() => galleryResults.value.length ? galleryResults.value : galleryPhotos.value)
const progress = computed(() => job.value?.total ? Math.round(job.value.current / job.value.total * 100) : 0)
const activeIndex = computed(() => activeSlot.value ? slots.value.findIndex(slot => slot.id === activeSlot.value?.id) : -1)
const coverageWidth = computed(() => preflight.value?.total_slots ? Math.round((preflight.value.selected_slots / preflight.value.total_slots) * 100) + '%' : '0%')

async function refreshProjects() { projects.value = await api.projects(); if (!activeProject.value && projects.value.length) await openProject(projects.value[0]); else if (activeProject.value) activeProject.value = projects.value.find(project => project.id === activeProject.value?.id) || null }
async function openProject(project: Project) { activeProject.value = project; slots.value = await api.checklist(project.id); activeSlot.value = slots.value[0] || null; preflight.value = await api.preflight(project.id); if (activeSlot.value) await selectSlot(activeSlot.value) }
async function selectSlot(slot: Slot) { activeView.value = 'checklist'; activeSlot.value = slot; searchResults.value = []; searchText.value = ''; candidates.value = activeProject.value ? await api.candidates(activeProject.value.id, slot.id) : [] }
async function createProject() { loading.value = true; error.value = ''; try { const project = await api.createProject(form.value); await refreshProjects(); await openProject(project); showCreate.value = false; message.value = '项目已创建，已使用固定 Excel 清单。' } catch (e: any) { error.value = e.message } finally { loading.value = false } }
async function startIndex() { if (!activeProject.value) return; loading.value = true; error.value = ''; try { job.value = await api.index(activeProject.value.id); while (['queued', 'running'].includes(job.value.status)) { await new Promise(resolve => setTimeout(resolve, 800)); job.value = await api.job(activeProject.value.id, job.value.id) } if (job.value.status !== 'completed') throw new Error(job.value.message); await openProject(activeProject.value); message.value = '图片向量化和清单匹配已完成。' } catch (e: any) { error.value = e.message } finally { loading.value = false } }
async function startMatch() { if (!activeProject.value) return; loading.value = true; error.value = ''; try { job.value = await api.match(activeProject.value.id); while (['queued', 'running'].includes(job.value.status)) { await new Promise(resolve => setTimeout(resolve, 800)); job.value = await api.job(activeProject.value.id, job.value.id) } if (job.value.status !== 'completed') throw new Error(job.value.message); await openProject(activeProject.value); message.value = job.value.message } catch (e: any) { error.value = e.message } finally { loading.value = false } }
async function search() { if (!activeProject.value || !searchText.value.trim()) return; loading.value = true; try { searchResults.value = await api.search(activeProject.value.id, searchText.value.trim()) } catch (e: any) { error.value = e.message } finally { loading.value = false } }
async function usePhoto(photo: Candidate | GalleryPhoto) { if (!activeProject.value || !activeSlot.value) return; try { await api.confirm(activeProject.value.id, activeSlot.value.id, photo.photo_id, searchText.value); activeSlot.value.confirmed_photo_ids = [photo.photo_id]; slots.value = slots.value.map(slot => slot.id === activeSlot.value?.id ? activeSlot.value! : slot); preflight.value = await api.preflight(activeProject.value.id); message.value = '已确认：' + photo.filename } catch (e: any) { error.value = e.message } }
async function confirmAll() { if (!activeProject.value) return; try { const result = await api.confirmAllTop(activeProject.value.id); await openProject(activeProject.value); message.value = result.message } catch (e: any) { error.value = e.message } }
async function exportExcel() { if (!activeProject.value) return; loading.value = true; try { const result = await api.exportExcel(activeProject.value.id); preflight.value = result; if (result.download_url) window.open(result.download_url, '_blank'); message.value = '已导出 Excel；' + (result.missing_count || 0) + ' 项缺图已留空。' } catch (e: any) { error.value = e.message } finally { loading.value = false } }
async function clearGallery() { if (!activeProject.value) return; const name = window.prompt('请输入“' + activeProject.value.factory_name + '”确认清空当前项目图库'); if (name !== activeProject.value.factory_name) return; try { const result = await api.clearGallery(activeProject.value.id, name); await openProject(activeProject.value); message.value = result.message } catch (e: any) { error.value = e.message } }
async function deleteProject() { if (!activeProject.value) return; const project = activeProject.value; const name = window.prompt('删除会移除“' + project.factory_name + '”的项目数据和已导出清单。请输入项目名称确认删除'); if (name !== project.factory_name) return; loading.value = true; try { const result = await api.deleteProject(project.id, name); projects.value = await api.projects(); activeProject.value = null; slots.value = []; activeSlot.value = null; candidates.value = []; galleryPhotos.value = []; preflight.value = null; if (projects.value.length) await openProject(projects.value[0]); message.value = result.message } catch (e: any) { error.value = e.message } finally { loading.value = false } }
async function importFeedback() { if (!activeProject.value || !desktopApi()?.select_feedback_file) return; const path = await desktopApi()!.select_feedback_file!(); if (!path) return; loading.value = true; try { const result = await api.importFeedback(activeProject.value.id, path); await openProject(activeProject.value); message.value = result.message } catch (e: any) { error.value = e.message } finally { loading.value = false } }
async function openGallery() { if (!activeProject.value) return; activeView.value = 'gallery'; galleryPhotos.value = await api.gallery(activeProject.value.id); galleryResults.value = [] }
async function searchGallery() { if (!activeProject.value || !galleryQuery.value.trim()) return; galleryResults.value = await api.gallerySearch(activeProject.value.id, galleryQuery.value.trim()) }
async function startOcr() { if (!activeProject.value) return; loading.value = true; try { job.value = await api.ocr(activeProject.value.id); while (['queued', 'running'].includes(job.value.status)) { await new Promise(resolve => setTimeout(resolve, 800)); job.value = await api.job(activeProject.value.id, job.value.id) }; galleryPhotos.value = await api.gallery(activeProject.value.id); message.value = '本地文字索引已完成；点击“重新匹配清单”即可将 OCR 结果加入排序。' } catch (e: any) { error.value = e.message } finally { loading.value = false } }
onMounted(async () => { try { await initSession(); checklistTypes.value = await api.checklistTypes(); await refreshProjects() } catch (e: any) { error.value = e.message } })
</script>

<template>
  <main class="app-root">
    <header class="topbar">
      <div class="brand"><div class="brand-mark">A</div><strong>AutoPick</strong><small>工厂审核清单选图系统</small></div>
      <div class="actions"><button class="secondary" @click="showCreate = true">新建工厂项目</button><button class="secondary" :disabled="loading || !activeProject" @click="startMatch">重新匹配清单</button><button class="export-top" :disabled="loading || !activeProject" @click="exportExcel">导出 Excel 清单</button></div>
    </header>
    <div v-if="error" class="notice error">{{ error }}<button class="notice-close" @click="error = ''">×</button></div>
    <div v-if="message" class="notice success">{{ message }}<button class="notice-close" @click="message = ''">×</button></div>
    <div v-if="job && (job.status === 'queued' || job.status === 'running')" class="job-banner"><div class="job-info"><strong>{{ job.message }}</strong><span>{{ progress }}%</span></div><div class="progress"><i :style="{ width: progress + '%' }"></i></div></div>

    <section v-if="activeProject" :class="['workspace', { 'gallery-workspace': activeView === 'gallery' }]">
      <aside class="projects-panel">
        <section class="project-switcher"><p class="eyebrow">项目切换</p><nav class="project-list"><button v-for="project in projects" :key="project.id" :class="{ active: project.id === activeProject.id }" @click="openProject(project)"><strong>{{ project.factory_name }}</strong><small>{{ project.confirmed_count }}/{{ project.slot_count }} 已确认</small></button></nav></section>
        <div class="project-section-divider" aria-hidden="true"></div>
        <section class="current-project-overview"><p class="eyebrow">当前项目</p><h2>{{ activeProject.factory_name }}</h2><p class="muted">{{ activeProject.photo_count }} 张图 · {{ activeProject.slot_count }} 个清单字段</p><nav class="project-nav project-views"><button :class="{ active: activeView === 'checklist' }" @click="activeView = 'checklist'">审核清单</button><button :class="{ active: activeView === 'gallery' }" @click="openGallery">图库<small>{{ activeProject.photo_count }} 张 · {{ activeProject.indexed_count }} 已向量化</small></button></nav></section>
        <section class="current-project-actions"><p class="eyebrow">当前项目操作</p><nav class="project-nav"><button @click="openDataFolder">打开项目数据文件夹</button><button :disabled="loading" @click="importFeedback">导入该项目最终结果（用于学习）</button><button @click="clearGallery">清空当前项目图库</button><button class="danger-button" :disabled="loading" @click="deleteProject">删除当前项目</button></nav></section>
      </aside>

      <aside v-if="activeView === 'checklist'" class="slots-panel">
        <div class="slots-header"><strong>照片清单（{{ slots.length }}）</strong><span class="slots-stats">{{ preflight?.selected_slots || 0 }}/{{ slots.length }} 已确认</span></div>
        <div class="slots-bulk-action"><div class="checklist-actions"><button class="btn-select-all" :disabled="loading" @click="startMatch">重新匹配并自动选最佳</button><button class="btn-rematch" :disabled="loading" @click="confirmAll">仅自动选最佳</button></div><small>重新匹配会使用已有向量计算候选；两种操作都不覆盖人工确认或拒绝项。</small></div>
        <div class="slots-scroll"><button v-for="slot in slots" :key="slot.id" :class="[{ active: slot.id === activeSlot?.id }, 'confidence-line-' + confidenceClass(slot)]" @click="selectSlot(slot)"><span class="slot-btn-content"><span class="slot-index">{{ slot.ordinal }}</span><span class="slot-label">{{ slot.label }}</span></span></button></div>
      </aside>

      <section v-if="activeView === 'checklist'" class="content-panel">
        <div class="slot-heading"><div><p class="eyebrow">{{ activeProject.checklist_type_id }} · 第 {{ activeIndex + 1 }}/{{ slots.length }} 项</p><h1>{{ activeSlot?.label || '审核清单' }}</h1></div><div class="slot-nav-actions"><button class="secondary nav-btn" :disabled="activeIndex <= 0" @click="selectSlot(slots[activeIndex - 1])">◀ 上一项</button><button class="secondary nav-btn" :disabled="activeIndex >= slots.length - 1" @click="selectSlot(slots[activeIndex + 1])">下一项 ▶</button></div></div>
        <div class="search-bar"><input v-model="searchText" @keyup.enter="search" placeholder="自然语言搜图，例如：车间入口的消火栓、特种设备检验合格证..." /><button @click="search">在当前图库搜索</button><button v-if="searchResults.length" class="secondary" @click="searchResults = []; searchText = ''">返回推荐</button></div>
        <div class="section-title-bar"><h3>{{ searchResults.length ? '搜索结果（' + searchResults.length + '）' : '候选照片匹配结果（按匹配度排序）' }}</h3><small class="tip">首张为系统首选，点击图片可放大查看。</small></div>
        <div v-if="!displayedCandidates.length" class="no-photos">暂无候选照片。请先建立图片向量。</div>
        <div v-else class="photo-grid"><article v-for="(photo, index) in displayedCandidates" :key="photo.photo_id" :class="['photo-card', { 'card-confirmed': activeSlot?.confirmed_photo_ids.includes(photo.photo_id), 'card-primary': index === 0 && !activeSlot?.confirmed_photo_ids.length }]"><div :class="['card-badge', activeSlot?.confirmed_photo_ids.includes(photo.photo_id) ? 'badge-confirmed' : index === 0 ? 'badge-primary' : 'badge-backup']">{{ activeSlot?.confirmed_photo_ids.includes(photo.photo_id) ? '★ 当前已选用' : index === 0 ? '推荐首选' : '备选 ' + index }}</div><div class="img-wrapper" @click="previewImage = photo"><img :src="imageUrl(photo.photo_id)" :alt="photo.filename" loading="lazy" /><div class="img-overlay">🔍 点击放大</div></div><div class="photo-meta"><strong :title="photo.filename">{{ photo.filename }}</strong><div class="meta-row"><span>相似度 {{ photo.semantic_score.toFixed(3) }}</span><span>清晰度 {{ Math.round(photo.quality_score * 100) }}</span></div><small v-if="photo.used_in_slots.length">⚠️ 已用于其他 {{ photo.used_in_slots.length }} 个清单项</small><button v-if="activeSlot?.confirmed_photo_ids.includes(photo.photo_id)" class="btn-confirmed" disabled>✓ 当前已选定</button><button v-else class="btn-use" @click="usePhoto(photo)">选用此照片</button></div></article></div>
      </section>

      <section v-else class="content-panel">
        <div class="gallery-heading"><div><p class="eyebrow">当前工厂专属图库</p><h1>图库浏览</h1><p class="muted">{{ galleryPhotos.length }} 张照片 · {{ galleryPhotos.filter(photo => photo.embedding_status === 'indexed').length }} 已向量化</p></div><div class="gallery-heading-actions"><div class="gallery-processing" aria-label="图库处理"><p>图库处理</p><div><button class="gallery-process-button" :disabled="loading" @click="startIndex">建立图片向量</button><button class="gallery-process-button" :disabled="loading" @click="startOcr">建立文字索引（本地 OCR）</button></div></div><button class="secondary" @click="openGallery">刷新图库</button></div></div>
        <div class="gallery-search-bar"><input v-model="galleryQuery" @keyup.enter="searchGallery" placeholder="搜索画面内容或图片内文字" /><button @click="searchGallery">搜索图库</button></div>
        <div class="photo-grid gallery-grid"><article v-for="photo in displayedGallery" :key="photo.photo_id" class="photo-card"><div class="img-wrapper" @click="previewImage = photo"><img :src="imageUrl(photo.photo_id)" :alt="photo.filename" loading="lazy" /></div><div class="photo-meta"><strong>{{ photo.filename }}</strong><div class="meta-row"><span>清晰度 {{ Math.round(photo.quality_score * 100) }}</span><span>{{ photo.embedding_status === 'indexed' ? '向量已完成' : '待向量化' }}</span></div></div></article></div>
      </section>

      <aside class="review-panel">
        <p class="eyebrow">Excel 清单交付</p><h3 class="stat-count">{{ preflight?.selected_slots || 0 }}/{{ preflight?.total_slots || activeProject.slot_count }}</h3><p class="muted">已确认清单项</p>
        <div class="progress-box"><div class="progress-bar-wrap"><div class="progress-bar-fill" :style="{ width: coverageWidth }"></div></div><span class="progress-text">缺图 {{ preflight?.missing_slots || 0 }} 项</span></div>
        <div class="isolation-card"><strong>🔒 项目数据隔离</strong><p>图库、向量和 OCR 仅属于当前项目；外部源图库不会被清理。</p></div>
        <div class="report-actions"><button class="secondary" @click="confirmAll">全选中最高匹配</button><button class="btn-generate" :disabled="loading" @click="exportExcel">导出 .xlsx 清单</button></div>
        <div class="coverage-card"><strong>反馈积累</strong><p>有效反馈 {{ preflight?.feedback_records || 0 }} 条 · 待确认别名 {{ preflight?.pending_aliases || 0 }} 个</p><small>导出与导入反馈清单会保存样本；当前仍使用既有匹配规则。</small></div>
      </aside>
    </section>

    <section v-else class="empty-state"><h1>开始一个工厂项目</h1><p>选择图库后，系统会复制照片到项目目录并使用固定 Excel 清单匹配。</p><button class="primary-lg" @click="showCreate = true">新建工厂项目</button></section>
    <div v-if="previewImage" class="lightbox-wrap" @click="previewImage = null"><div class="lightbox-content" @click.stop><div class="lightbox-header"><strong>{{ previewImage.filename }}</strong><button class="icon-close" @click="previewImage = null">✕</button></div><div class="lightbox-body"><img :src="imageUrl(previewImage.photo_id)" :alt="previewImage.filename" /></div><button class="btn-use" @click="usePhoto(previewImage); previewImage = null">选用这张照片</button></div></div>
    <div v-if="showCreate" class="modal-wrap"><form class="modal" @submit.prevent="createProject"><div class="modal-title"><h2>新建工厂项目</h2><button type="button" class="icon-close" @click="showCreate = false">✕</button></div><label>工厂名称<input v-model="form.factory_name" required placeholder="例如：浙江某某科技有限公司" /></label><label>本工厂图库文件夹<span class="file-input"><input v-model="form.gallery_path" required placeholder="D:\\Audit\\Photos" /><button type="button" class="secondary" @click="chooseFolder">浏览</button></span></label><label>清单类型<select v-model="form.checklist_type_id"><option v-for="type in checklistTypes" :key="type.id" :value="type.id">{{ type.label }}（{{ type.slot_count }} 项）</option></select></label><p class="modal-tip">固定清单模板随程序分发；创建后会复制图库到项目专属目录。</p><button :disabled="loading" type="submit" class="modal-submit">创建并初始化图库</button></form></div>
  </main>
</template>
