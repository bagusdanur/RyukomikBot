<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import Tag from "primevue/tag";
import {
  api,
  type ProjectRawChapter,
  type ProjectRawChaptersResponse,
  type ProjectTrackerItem,
  type ProjectTrackerResponse,
  type ProjectTrackerSummary,
} from "../api";

const emit = defineEmits<{
  (e: "create-task", payload: { manga: string; chapter: string }): void;
}>();

const rows = ref<ProjectTrackerItem[]>([]);
const summary = ref<ProjectTrackerSummary>({
  total_projects: 0,
  raw_available_count: 0,
  in_progress_count: 0,
  up_to_date_count: 0,
  unlinked_count: 0,
});
const search = ref("");
const statusFilter = ref("all");
const sourceFilter = ref("all");
const viewMode = ref<"grid" | "table">("grid");
const page = ref(1);
const pageSize = ref(24);
const pages = ref(1);
const total = ref(0);

const loading = ref(false);
const syncingAll = ref(false);
const syncingMap = ref<Record<string, boolean>>({});
const error = ref("");
const success = ref("");

// Modal States
const rawConfigTarget = ref<ProjectTrackerItem | null>(null);
const rawConfigForm = ref({
  source: "omega",
  source_id: "",
});
const savingRawConfig = ref(false);

const rawChaptersTarget = ref<ProjectTrackerItem | null>(null);
const rawChaptersData = ref<ProjectRawChaptersResponse | null>(null);
const loadingRawChapters = ref(false);

const availableSources = [
  { id: "asura", label: "Asura Scans" },
  { id: "omega", label: "Omega Scans" },
  { id: "doujiva", label: "Doujiva" },
  { id: "evascan", label: "EvaScan" },
  { id: "thunder", label: "Thunder Scans" },
  { id: "vortex", label: "Vortex Scans" },
  { id: "qimanga", label: "QiManga" },
  { id: "demon", label: "Demon Scans" },
];

const statusLabels: Record<string, string> = {
  raw_available: "⚡ RAW Baru",
  in_progress: "⏳ Dikerjakan",
  up_to_date: "✅ Up to Date",
  unlinked: "⚠️ Belum Link RAW",
};

function statusSeverity(status: string) {
  switch (status) {
    case "raw_available":
      return "danger";
    case "in_progress":
      return "warn";
    case "up_to_date":
      return "success";
    default:
      return "secondary";
  }
}

function fmtCh(val: number | null | undefined): string {
  if (val === null || val === undefined) return "—";
  return Number.isInteger(val) ? String(val) : String(val);
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const res: ProjectTrackerResponse = await api.projects(
      search.value.trim(),
      statusFilter.value,
      sourceFilter.value,
      page.value,
      pageSize.value,
    );
    rows.value = res.items;
    summary.value = res.summary;
    total.value = res.total;
    pages.value = res.total_pages;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal memuat data project.";
  } finally {
    loading.value = false;
  }
}

async function syncAll() {
  syncingAll.value = true;
  error.value = "";
  success.value = "";
  try {
    const res = await api.syncProjects();
    success.value = res.message || "Sinkronisasi RAW seluruh project selesai.";
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal sinkronisasi RAW.";
  } finally {
    syncingAll.value = false;
  }
}

async function syncSingle(item: ProjectTrackerItem) {
  const key = item.slug || item.title;
  syncingMap.value[key] = true;
  error.value = "";
  success.value = "";
  try {
    const res = await api.syncSingleProject(key);
    success.value = res.message;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : `Gagal cek RAW untuk ${item.title}.`;
  } finally {
    syncingMap.value[key] = false;
  }
}

function openRawConfig(item: ProjectTrackerItem) {
  rawConfigTarget.value = item;
  rawConfigForm.value = {
    source: item.raw_source || "omega",
    source_id: item.raw_source_id || item.slug || "",
  };
}

async function saveRawConfig() {
  if (!rawConfigTarget.value) return;
  if (!rawConfigForm.value.source_id.trim()) {
    error.value = "Slug / ID sumber RAW wajib diisi.";
    return;
  }
  savingRawConfig.value = true;
  error.value = "";
  success.value = "";
  try {
    const key = rawConfigTarget.value.slug || rawConfigTarget.value.title;
    const res = await api.setProjectRawSource(key, {
      source: rawConfigForm.value.source,
      source_id: rawConfigForm.value.source_id.trim(),
    });
    success.value = res.message;
    rawConfigTarget.value = null;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal mengatur sumber RAW.";
  } finally {
    savingRawConfig.value = false;
  }
}

async function openRawChapters(item: ProjectTrackerItem) {
  rawChaptersTarget.value = item;
  rawChaptersData.value = null;
  loadingRawChapters.value = true;
  error.value = "";
  try {
    const key = item.slug || item.title;
    rawChaptersData.value = await api.projectRawChapters(key);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal mengambil daftar chapter RAW.";
  } finally {
    loadingRawChapters.value = false;
  }
}

function handleCreateTask(manga: string, chapter: string) {
  emit("create-task", { manga, chapter });
}

function handleCreateTaskFromModal(chapterTitleOrId: string) {
  if (!rawChaptersTarget.value) return;
  const match = chapterTitleOrId.match(/\d+(?:\.\d+)?/);
  const ch = match ? match[0] : chapterTitleOrId;
  const mangaTitle = rawChaptersTarget.value.title;
  rawChaptersTarget.value = null;
  emit("create-task", { manga: mangaTitle, chapter: ch });
}

function changePage(direction: number) {
  page.value = Math.min(pages.value, Math.max(1, page.value + direction));
  load();
}

let searchDebounce: number | undefined;
watch(search, () => {
  clearTimeout(searchDebounce);
  searchDebounce = window.setTimeout(() => {
    page.value = 1;
    load();
  }, 350);
});

watch([statusFilter, sourceFilter], () => {
  page.value = 1;
  load();
});

onMounted(load);
</script>

<template>
  <div class="projects-page">
    <!-- Hero / Stats Section -->
    <section class="hero-card projects-hero">
      <div>
        <p class="eyebrow"><i class="pi pi-compass"></i> RYUKOMIK PROJECT TRACKER</p>
        <h3>Daftar Project & Tracker RAW</h3>
        <p>
          Pantau perbandingan chapter project Ryukomik vs rilis RAW terbaru (Asura, Omega, Doujiva, dll) dan buat tugas staff secara instan.
        </p>
      </div>
      <div class="hero-actions">
        <Button
          label="Sinkronkan Semua RAW"
          icon="pi pi-sync"
          :loading="syncingAll"
          severity="primary"
          @click="syncAll"
        />
      </div>
    </section>

    <!-- Quick Stat Cards -->
    <section class="stats-grid">
      <article @click="statusFilter = 'all'" :class="{ 'stat-active': statusFilter === 'all' }">
        <span class="stat-icon blue"><i class="pi pi-book"></i></span>
        <div>
          <small>Total Project</small>
          <strong>{{ summary.total_projects }}</strong>
        </div>
      </article>

      <article
        @click="statusFilter = 'raw_available'"
        :class="{ 'stat-active': statusFilter === 'raw_available' }"
      >
        <span class="stat-icon red"><i class="pi pi-bolt"></i></span>
        <div>
          <small>RAW Baru (Perlu Tugas)</small>
          <strong>{{ summary.raw_available_count }}</strong>
        </div>
      </article>

      <article
        @click="statusFilter = 'in_progress'"
        :class="{ 'stat-active': statusFilter === 'in_progress' }"
      >
        <span class="stat-icon amber"><i class="pi pi-clock"></i></span>
        <div>
          <small>Sedang Dikerjakan</small>
          <strong>{{ summary.in_progress_count }}</strong>
        </div>
      </article>

      <article
        @click="statusFilter = 'up_to_date'"
        :class="{ 'stat-active': statusFilter === 'up_to_date' }"
      >
        <span class="stat-icon violet"><i class="pi pi-check-circle"></i></span>
        <div>
          <small>Up to Date</small>
          <strong>{{ summary.up_to_date_count }}</strong>
        </div>
      </article>
    </section>

    <!-- Alert Notices -->
    <div v-if="error" class="notice error">
      <i class="pi pi-exclamation-circle"></i> {{ error }}
    </div>
    <div v-if="success" class="notice success">
      <i class="pi pi-check-circle"></i> {{ success }}
    </div>

    <!-- Toolbar Filters & Search -->
    <section class="toolbar projects-toolbar">
      <div class="search">
        <i class="pi pi-search"></i>
        <input
          v-model="search"
          placeholder="Cari judul project atau slug..."
          @keyup.enter="page = 1; load()"
        />
      </div>

      <select v-model="statusFilter">
        <option value="all">Semua Status</option>
        <option value="raw_available">⚡ RAW Baru Rilis</option>
        <option value="in_progress">⏳ Sedang Dikerjakan</option>
        <option value="up_to_date">✅ Up to Date</option>
        <option value="unlinked">⚠️ Belum Link RAW</option>
      </select>

      <select v-model="sourceFilter">
        <option value="all">Semua Sumber RAW</option>
        <option v-for="src in availableSources" :key="src.id" :value="src.id">
          {{ src.label }}
        </option>
      </select>

      <div class="view-toggle">
        <Button
          icon="pi pi-th-large"
          :severity="viewMode === 'grid' ? 'primary' : 'secondary'"
          text
          @click="viewMode = 'grid'"
          title="Grid Tampilan Card"
        />
        <Button
          icon="pi pi-list"
          :severity="viewMode === 'table' ? 'primary' : 'secondary'"
          text
          @click="viewMode = 'table'"
          title="Tampilan Tabel"
        />
      </div>
    </section>

    <!-- Loading Skeleton or Empty State -->
    <div v-if="loading && !rows.length" class="loading-box">
      <i class="pi pi-spin pi-spinner"></i>
      <p>Memuat daftar project dan status RAW...</p>
    </div>

    <div v-else-if="!rows.length" class="empty-box panel">
      <i class="pi pi-inbox"></i>
      <h3>Tidak ada project ditemukan</h3>
      <p>Coba sesuaikan kata kunci pencarian atau filter status yang dipilih.</p>
    </div>

    <!-- GRID VIEW -->
    <section v-else-if="viewMode === 'grid'" class="projects-grid">
      <article
        v-for="item in rows"
        :key="item.slug || item.title"
        class="project-card"
        :class="`status-${item.status}`"
      >
        <!-- Cover & Badges -->
        <div class="project-cover-wrap">
          <img
            v-if="item.cover_url"
            :src="item.cover_url"
            :alt="item.title"
            class="project-cover"
            loading="lazy"
            referrerpolicy="no-referrer"
          />
          <div v-else class="project-cover-placeholder">
            <i class="pi pi-book"></i>
          </div>

          <div class="project-badges">
            <Tag
              :value="statusLabels[item.status] || item.status"
              :severity="statusSeverity(item.status)"
              class="status-tag"
            />
            <span v-if="item.type_genre && item.type_genre !== '-'" class="genre-tag">
              {{ item.type_genre }}
            </span>
          </div>

          <div v-if="item.chapter_gap && item.chapter_gap > 0" class="gap-indicator">
            <i class="pi pi-bolt"></i> +{{ item.chapter_gap }} RAW Baru
          </div>
        </div>

        <!-- Project Content -->
        <div class="project-body">
          <div class="project-title-row">
            <h4 :title="item.title">
              <a
                v-if="item.project_url"
                :href="item.project_url"
                target="_blank"
                rel="noopener"
                class="title-link"
              >
                {{ item.title }}
                <i class="pi pi-external-link mini-link-icon"></i>
              </a>
              <span v-else>{{ item.title }}</span>
            </h4>
            <span class="pub-status">{{ item.publication_status }}</span>
          </div>

          <!-- Comparison Widget -->
          <div class="compare-box">
            <div class="compare-item">
              <small>Ryukomik</small>
              <b class="ch-val">Ch. {{ fmtCh(item.effective_chapter) }}</b>
            </div>

            <div class="compare-divider">
              <i class="pi pi-arrow-right"></i>
            </div>

            <div class="compare-item">
              <small>
                RAW
                <span v-if="item.raw_source" class="source-name">({{ item.raw_source }})</span>
              </small>
              <b class="ch-val raw-ch-val" :class="{ 'has-update': item.status === 'raw_available' }">
                Ch. {{ fmtCh(item.raw_chapter) }}
              </b>
            </div>
          </div>

          <!-- Missing Chapters / Active Tasks Info -->
          <div v-if="item.missing_chapters && item.missing_chapters.length" class="missing-row">
            <span class="missing-label">RAW belum di-post:</span>
            <div class="missing-chips">
              <span
                v-for="ch in item.missing_chapters.slice(0, 4)"
                :key="ch"
                class="ch-chip"
                @click="handleCreateTask(item.title, ch)"
                :title="`Klik untuk buat tugas Ch. ${ch}`"
              >
                Ch. {{ ch }}
              </span>
              <span v-if="item.missing_chapters.length > 4" class="ch-chip-more">
                +{{ item.missing_chapters.length - 4 }} lagi
              </span>
            </div>
          </div>

          <!-- Active Assignment Chips -->
          <div v-if="item.active_tasks && item.active_tasks.length" class="active-tasks-row">
            <small class="active-tasks-label">Tugas aktif:</small>
            <div class="active-task-list">
              <span
                v-for="task in item.active_tasks"
                :key="task.id"
                class="active-task-chip"
                :title="`Tugas #${task.id}: ${task.role} • ${task.staff_name}`"
              >
                Ch. {{ task.chapter }} ({{ task.role }}) · {{ task.staff_name }}
              </span>
            </div>
          </div>

          <!-- Action Buttons -->
          <div class="project-actions">
            <Button
              v-if="item.status === 'raw_available'"
              :label="`⚡ Buat Tugas Ch. ${item.next_task_chapter}`"
              icon="pi pi-bolt"
              severity="danger"
              class="btn-quick-task"
              @click="handleCreateTask(item.title, item.next_task_chapter)"
            />
            <Button
              v-else
              :label="`+ Buat Tugas Ch. ${item.next_task_chapter}`"
              icon="pi pi-plus"
              severity="primary"
              class="btn-quick-task"
              @click="handleCreateTask(item.title, item.next_task_chapter)"
            />

            <div class="sub-actions">
              <Button
                icon="pi pi-refresh"
                severity="secondary"
                text
                size="small"
                :loading="syncingMap[item.slug || item.title]"
                @click="syncSingle(item)"
                title="Cek RAW Sekarang"
              />
              <Button
                v-if="item.raw_source"
                icon="pi pi-list"
                severity="secondary"
                text
                size="small"
                @click="openRawChapters(item)"
                title="Lihat Semua Chapter RAW"
              />
              <Button
                icon="pi pi-cog"
                severity="secondary"
                text
                size="small"
                @click="openRawConfig(item)"
                title="Atur Sumber RAW"
              />
            </div>
          </div>
        </div>
      </article>
    </section>

    <!-- TABLE VIEW -->
    <section v-else class="table-section panel">
      <div class="table-card">
        <DataTable :value="rows" :loading="loading" responsiveLayout="scroll">
          <Column header="Cover" style="width: 70px">
            <template #body="{ data }">
              <img
                v-if="data.cover_url"
                :src="data.cover_url"
                :alt="data.title"
                class="mini-table-cover"
                referrerpolicy="no-referrer"
              />
              <div v-else class="mini-table-placeholder"><i class="pi pi-book"></i></div>
            </template>
          </Column>

          <Column field="title" header="Judul Project" sortable>
            <template #body="{ data }">
              <div class="table-project-cell">
                <strong class="table-title">{{ data.title }}</strong>
                <small class="table-genre">{{ data.type_genre || "-" }} · {{ data.publication_status }}</small>
              </div>
            </template>
          </Column>

          <Column header="Status" style="width: 140px">
            <template #body="{ data }">
              <Tag :value="statusLabels[data.status] || data.status" :severity="statusSeverity(data.status)" />
            </template>
          </Column>

          <Column header="Ryukomik" style="width: 110px">
            <template #body="{ data }">
              <b>Ch. {{ fmtCh(data.effective_chapter) }}</b>
            </template>
          </Column>

          <Column header="RAW Terbaru" style="width: 130px">
            <template #body="{ data }">
              <div v-if="data.raw_chapter !== null">
                <b>Ch. {{ fmtCh(data.raw_chapter) }}</b>
                <small class="table-sub">{{ data.raw_source }}</small>
              </div>
              <span v-else class="table-muted">Belum ada</span>
            </template>
          </Column>

          <Column header="Selisih" style="width: 100px">
            <template #body="{ data }">
              <span
                v-if="data.chapter_gap && data.chapter_gap > 0"
                class="table-gap-badge"
              >
                +{{ data.chapter_gap }} Ch
              </span>
              <span v-else-if="data.raw_chapter !== null" class="table-muted">0</span>
              <span v-else class="table-muted">—</span>
            </template>
          </Column>

          <Column header="Tugas Berjalan" style="width: 150px">
            <template #body="{ data }">
              <span v-if="data.active_tasks && data.active_tasks.length" class="table-task-count">
                {{ data.active_tasks.length }} tugas aktif
              </span>
              <span v-else class="table-muted">Tidak ada</span>
            </template>
          </Column>

          <Column header="Aksi" style="width: 180px">
            <template #body="{ data }">
              <div class="table-actions">
                <Button
                  :label="`+ Ch. ${data.next_task_chapter}`"
                  icon="pi pi-bolt"
                  size="small"
                  :severity="data.status === 'raw_available' ? 'danger' : 'primary'"
                  @click="handleCreateTask(data.title, data.next_task_chapter)"
                />
                <Button
                  icon="pi pi-refresh"
                  size="small"
                  severity="secondary"
                  text
                  @click="syncSingle(data)"
                  title="Cek RAW"
                />
                <Button
                  icon="pi pi-cog"
                  size="small"
                  severity="secondary"
                  text
                  @click="openRawConfig(data)"
                  title="Atur RAW"
                />
              </div>
            </template>
          </Column>
        </DataTable>
      </div>
    </section>

    <!-- Pagination -->
    <div v-if="pages > 1" class="server-pager">
      <Button
        icon="pi pi-chevron-left"
        severity="secondary"
        :disabled="page <= 1"
        @click="changePage(-1)"
      />
      <span>Halaman {{ page }} / {{ pages }} (Total {{ total }} project)</span>
      <Button
        icon="pi pi-chevron-right"
        severity="secondary"
        :disabled="page >= pages"
        @click="changePage(1)"
      />
    </div>

    <!-- MODAL: ATUR SUMBER RAW -->
    <div v-if="rawConfigTarget" class="modal-backdrop" @click.self="rawConfigTarget = null">
      <section class="modal-card project-modal">
        <div class="modal-head">
          <div>
            <p class="eyebrow">PENGATURAN RAW WATCH</p>
            <h3>Atur Sumber RAW: {{ rawConfigTarget.title }}</h3>
          </div>
          <button type="button" @click="rawConfigTarget = null">×</button>
        </div>

        <div class="modal-form">
          <label>
            <span>Pilih Scraper / Sumber RAW</span>
            <select v-model="rawConfigForm.source">
              <option v-for="src in availableSources" :key="src.id" :value="src.id">
                {{ src.label }}
              </option>
            </select>
          </label>

          <label>
            <span>Slug / ID Komik di Sumber RAW</span>
            <input
              v-model="rawConfigForm.source_id"
              placeholder="Contoh: get-out atau secret-class"
            />
            <small class="form-hint">
              ID ini biasanya berupa bagian akhir dari URL detail komik pada situs RAW target (misal: /manga/<strong>get-out</strong>).
            </small>
          </label>

          <div v-if="rawConfigTarget.raw_chapter !== null" class="current-raw-info">
            <i class="pi pi-info-circle"></i>
            <span>
              Terakhir dicek: <strong>Ch. {{ fmtCh(rawConfigTarget.raw_chapter) }}</strong>
              (Sumber: {{ rawConfigTarget.raw_source }})
            </span>
          </div>

          <div class="modal-buttons">
            <Button
              label="Batal"
              severity="secondary"
              text
              @click="rawConfigTarget = null"
            />
            <Button
              label="Simpan & Cek RAW"
              icon="pi pi-check"
              :loading="savingRawConfig"
              @click="saveRawConfig"
            />
          </div>
        </div>
      </section>
    </div>

    <!-- MODAL: DAFTAR CHAPTER RAW -->
    <div v-if="rawChaptersTarget" class="modal-backdrop" @click.self="rawChaptersTarget = null">
      <section class="modal-card raw-chapters-modal">
        <div class="modal-head">
          <div>
            <p class="eyebrow">DAFTAR CHAPTER RAW</p>
            <h3>{{ rawChaptersTarget.title }}</h3>
          </div>
          <button type="button" @click="rawChaptersTarget = null">×</button>
        </div>

        <div v-if="loadingRawChapters" class="loading-box">
          <i class="pi pi-spin pi-spinner"></i>
          <p>Mengambil daftar chapter dari scraper...</p>
        </div>

        <div v-else-if="rawChaptersData" class="raw-chapters-content">
          <div class="raw-meta-bar">
            <span>Sumber: <strong>{{ rawChaptersData.source.toUpperCase() }}</strong></span>
            <span>ID: <code>{{ rawChaptersData.source_id }}</code></span>
            <span>Total: <strong>{{ rawChaptersData.chapters.length }} Chapter</strong></span>
          </div>

          <div class="chapters-scroll-list">
            <article
              v-for="ch in rawChaptersData.chapters"
              :key="ch.id"
              class="raw-chapter-item"
            >
              <div class="raw-chapter-info">
                <strong>{{ ch.title }}</strong>
                <small v-if="ch.date">{{ ch.date }}</small>
              </div>
              <Button
                label="Buat Tugas"
                icon="pi pi-plus"
                size="small"
                severity="primary"
                @click="handleCreateTaskFromModal(ch.title || ch.id)"
              />
            </article>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.projects-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.projects-hero {
  background: linear-gradient(125deg, #18223c, #131929 60%, #2b1836);
  border: 1px solid #7787ff35;
}

.eyebrow {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.1em;
  color: #8c98ff;
  text-transform: uppercase;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.stat-active {
  border-color: #7787ff !important;
  box-shadow: 0 0 0 2px #7787ff30;
}

.projects-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.view-toggle {
  display: flex;
  gap: 4px;
  background: #0b0f17;
  padding: 4px;
  border-radius: 10px;
  border: 1px solid #293244;
}

/* GRID LAYOUT */
.projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 18px;
}

.project-card {
  border: 1px solid var(--line);
  border-radius: 18px;
  background: linear-gradient(145deg, #141a26, #10141e);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
  box-shadow: 0 8px 24px #00000030;
}

.project-card:hover {
  transform: translateY(-3px);
  border-color: #5d6eff60;
  box-shadow: 0 14px 32px #00000055;
}

.project-card.status-raw_available {
  border-color: #ff5b6b45;
}

.project-card.status-in_progress {
  border-color: #ffaf3f45;
}

.project-cover-wrap {
  position: relative;
  height: 170px;
  background: #0d121c;
  overflow: hidden;
}

.project-cover {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s ease;
}

.project-card:hover .project-cover {
  transform: scale(1.04);
}

.project-cover-placeholder {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  color: #3b4661;
  font-size: 42px;
  background: linear-gradient(135deg, #131a29, #0d121c);
}

.project-badges {
  position: absolute;
  top: 12px;
  left: 12px;
  display: flex;
  gap: 6px;
  z-index: 2;
}

.genre-tag {
  background: #0b0f17bb;
  backdrop-filter: blur(8px);
  color: #c4d0ea;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 6px;
  border: 1px solid #ffffff15;
}

.gap-indicator {
  position: absolute;
  bottom: 10px;
  right: 10px;
  background: linear-gradient(135deg, #ff495c, #d92038);
  color: #ffffff;
  font-weight: 800;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 20px;
  box-shadow: 0 4px 14px #ff223366;
  display: flex;
  align-items: center;
  gap: 5px;
  z-index: 2;
}

.project-body {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
}

.project-title-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.project-title-row h4 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  line-height: 1.3;
}

.title-link {
  color: inherit;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.title-link:hover {
  color: #8c98ff;
}

.mini-link-icon {
  font-size: 11px;
  opacity: 0.7;
}

.pub-status {
  font-size: 11px;
  color: var(--muted);
  text-transform: capitalize;
  white-space: nowrap;
}

/* COMPARE BOX */
.compare-box {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  background: #0b0f17aa;
  border: 1px solid #232c3e;
  border-radius: 12px;
  padding: 10px 14px;
}

.compare-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.compare-item small {
  color: var(--muted);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.source-name {
  color: #8c98ff;
  text-transform: capitalize;
}

.ch-val {
  font-size: 15px;
  font-weight: 800;
  color: #e4eaf8;
}

.raw-ch-val.has-update {
  color: #ff6b7a;
}

.compare-divider {
  padding: 0 10px;
  color: #4b5873;
}

/* MISSING & ACTIVE TASKS */
.missing-row {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.missing-label, .active-tasks-label {
  font-size: 11px;
  color: var(--muted);
  font-weight: 600;
}

.missing-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.ch-chip {
  background: #ff5b6b22;
  border: 1px solid #ff5b6b55;
  color: #ff8b97;
  font-size: 11px;
  font-weight: 800;
  padding: 3px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.ch-chip:hover {
  background: #ff5b6b44;
  transform: scale(1.05);
}

.ch-chip-more {
  font-size: 11px;
  color: var(--muted);
  align-self: center;
}

.active-task-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.active-task-chip {
  background: #25223c;
  border: 1px solid #6b5c9e44;
  color: #c9b8ff;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ACTIONS */
.project-actions {
  margin-top: auto;
  display: flex;
  gap: 8px;
  align-items: center;
  padding-top: 8px;
  border-top: 1px solid #202738;
}

.btn-quick-task {
  flex: 1;
  font-weight: 700 !important;
  border-radius: 10px !important;
}

.sub-actions {
  display: flex;
  gap: 2px;
}

/* TABLE VIEW STYLES */
.mini-table-cover {
  width: 44px;
  height: 60px;
  object-fit: cover;
  border-radius: 6px;
}

.mini-table-placeholder {
  width: 44px;
  height: 60px;
  border-radius: 6px;
  background: #192030;
  display: grid;
  place-items: center;
  color: #55627f;
}

.table-project-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.table-title {
  font-size: 14px;
  color: var(--text);
}

.table-genre {
  color: var(--muted);
  font-size: 12px;
}

.table-sub {
  display: block;
  font-size: 11px;
  color: #8c98ff;
  text-transform: capitalize;
}

.table-gap-badge {
  display: inline-block;
  background: #ff5b6b22;
  color: #ff7d8a;
  border: 1px solid #ff5b6b44;
  font-weight: 800;
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 12px;
}

.table-task-count {
  font-size: 12px;
  color: #c9b8ff;
  font-weight: 600;
}

.table-muted {
  color: var(--muted);
  font-size: 13px;
}

.table-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* MODALS */
.project-modal {
  max-width: 520px;
}

.raw-chapters-modal {
  max-width: 580px;
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-top: 10px;
}

.modal-form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.modal-form label span {
  font-size: 13px;
  font-weight: 700;
  color: #d6def0;
}

.form-hint {
  color: var(--muted);
  font-size: 11px;
  line-height: 1.4;
  margin-top: 2px;
}

.current-raw-info {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 10px;
  background: #1a2233;
  border: 1px solid #2d3954;
  color: #adc0e6;
  font-size: 12px;
}

.modal-buttons {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 10px;
}

.raw-meta-bar {
  display: flex;
  gap: 16px;
  padding: 10px 14px;
  background: #0f1420;
  border-radius: 10px;
  border: 1px solid #252e42;
  font-size: 12px;
  color: #adbcd9;
  margin-bottom: 12px;
}

.raw-meta-bar code {
  color: #8c98ff;
  background: #1a2238;
  padding: 2px 6px;
  border-radius: 4px;
}

.chapters-scroll-list {
  max-height: 380px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-right: 4px;
}

.raw-chapter-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: #141a26;
  border: 1px solid #222b3d;
  border-radius: 10px;
}

.raw-chapter-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.raw-chapter-info strong {
  font-size: 14px;
  color: #e4eaf8;
}

.raw-chapter-info small {
  color: var(--muted);
  font-size: 11px;
}

.loading-box, .empty-box {
  padding: 40px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--muted);
}

.loading-box i {
  font-size: 32px;
  color: #8c98ff;
}

.empty-box i {
  font-size: 40px;
  color: #4b5873;
}

.empty-box h3 {
  margin: 0;
  color: var(--text);
}
</style>
