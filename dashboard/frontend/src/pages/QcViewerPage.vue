<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import Button from "primevue/button";
import Tag from "primevue/tag";
import InputText from "primevue/inputtext";
import {
  api,
  type QcDetailResponse,
  type QcPageAnnotation,
} from "../api";

const props = defineProps<{
  assignmentId: number;
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "approved", id: number): void;
  (e: "revised", id: number): void;
}>();

const loading = ref(true);
const actionLoading = ref(false);
const error = ref("");
const success = ref("");
const data = ref<QcDetailResponse | null>(null);

// Layout Modes:
// - "webtoon-dual": Dual continuous vertical strip (RAW kiri, Edit kanan) - DEFAULT
// - "webtoon-single": Single continuous vertical strip
// - "single-page": One page at a time with slider before/after
const layoutMode = ref<"webtoon-dual" | "webtoon-single" | "single-page">("webtoon-dual");

// Strip Width Configuration (for comfortable Webtoon reading)
const stripWidth = ref(640); // in pixels
const syncScroll = ref(true);

// Active Page & Annotations
const activePage = ref(1);
const generalNotes = ref("");
const pageAnnotations = ref<QcPageAnnotation[]>([]);
const newAnnotationComment = ref("");

// Slices / Local Overrides
const localSubmissionPages = ref<Record<number, string>>({});
const customImageInput = ref("");

// DOM element references for synchronized scrolling
const rawScrollContainer = ref<HTMLElement | null>(null);
const editScrollContainer = ref<HTMLElement | null>(null);
let isSyncingScroll = false;

const totalPages = computed(() => {
  if (!data.value) return 1;
  const rawCount = data.value.raw_pages.length;
  const subCount = Math.max(
    data.value.submission_pages.length,
    Object.keys(localSubmissionPages.value).length,
  );
  return Math.max(rawCount, subCount, 1);
});

async function loadQc() {
  loading.value = true;
  error.value = "";
  try {
    data.value = await api.qcDetail(props.assignmentId);
    activePage.value = 1;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal memuat data QC.";
  } finally {
    loading.value = false;
  }
}

// Synchronized Webtoon Scrolling
function onRawScroll() {
  if (!syncScroll.value || isSyncingScroll || !rawScrollContainer.value || !editScrollContainer.value) return;
  isSyncingScroll = true;
  const rawElem = rawScrollContainer.value;
  const editElem = editScrollContainer.value;
  const scrollPercentage = rawElem.scrollTop / Math.max(rawElem.scrollHeight - rawElem.clientHeight, 1);
  editElem.scrollTop = scrollPercentage * (editElem.scrollHeight - editElem.clientHeight);
  requestAnimationFrame(() => {
    isSyncingScroll = false;
  });
}

function onEditScroll() {
  if (!syncScroll.value || isSyncingScroll || !rawScrollContainer.value || !editScrollContainer.value) return;
  isSyncingScroll = true;
  const rawElem = rawScrollContainer.value;
  const editElem = editScrollContainer.value;
  const scrollPercentage = editElem.scrollTop / Math.max(editElem.scrollHeight - editElem.clientHeight, 1);
  rawElem.scrollTop = scrollPercentage * (rawElem.scrollHeight - rawElem.clientHeight);
  requestAnimationFrame(() => {
    isSyncingScroll = false;
  });
}

function scrollToPage(pageNumber: number) {
  activePage.value = pageNumber;
  const elem = document.getElementById(`page-slice-${pageNumber}`);
  if (elem) {
    elem.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function addPresetComment(tag: string) {
  if (newAnnotationComment.value) {
    newAnnotationComment.value += `, ${tag}`;
  } else {
    newAnnotationComment.value = tag;
  }
}

function addAnnotation() {
  if (!newAnnotationComment.value.trim()) return;
  const existingIndex = pageAnnotations.value.findIndex(
    (a) => a.page === activePage.value,
  );
  if (existingIndex >= 0) {
    pageAnnotations.value[existingIndex].comment = newAnnotationComment.value.trim();
  } else {
    pageAnnotations.value.push({
      page: activePage.value,
      comment: newAnnotationComment.value.trim(),
    });
  }
  newAnnotationComment.value = "";
}

function removeAnnotation(page: number) {
  pageAnnotations.value = pageAnnotations.value.filter((a) => a.page !== page);
}

function handlePasteOrDrop(e: ClipboardEvent | DragEvent) {
  let files: FileList | null = null;
  if ("clipboardData" in e && e.clipboardData?.files.length) {
    files = e.clipboardData.files;
  } else if ("dataTransfer" in e && e.dataTransfer?.files.length) {
    files = e.dataTransfer.files;
  }
  if (files && files.length > 0) {
    const file = files[0];
    if (file.type.startsWith("image/")) {
      const reader = new FileReader();
      reader.onload = (event) => {
        if (event.target?.result) {
          localSubmissionPages.value[activePage.value] = String(event.target.result);
          success.value = `Gambar editan Halaman ${activePage.value} berhasil dipasang.`;
        }
      };
      reader.readAsDataURL(file);
    }
  }
}

function setCustomImageUrl() {
  if (!customImageInput.value.trim()) return;
  localSubmissionPages.value[activePage.value] = customImageInput.value.trim();
  customImageInput.value = "";
  success.value = `URL gambar Halaman ${activePage.value} diterapkan.`;
}

function handleImageError(event: Event, originalUrl: string) {
  const img = event.target as HTMLImageElement;
  if (!img || !originalUrl) return;
  const proxyUrl = `/api/qc/proxy-image?url=${encodeURIComponent(originalUrl)}`;
  if (img.src !== proxyUrl && !img.src.includes("/api/qc/proxy-image")) {
    img.src = proxyUrl;
  }
}

async function approveAssignment() {
  if (!confirm(`Setujui tugas #${props.assignmentId} (${data.value?.assignment.manga} Ch. ${data.value?.assignment.chapter})?`)) return;
  actionLoading.value = true;
  error.value = "";
  try {
    await api.qcApprove(props.assignmentId);
    emit("approved", props.assignmentId);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal menyetujui tugas.";
  } finally {
    actionLoading.value = false;
  }
}

async function requestRevision() {
  if (!generalNotes.value.trim() && pageAnnotations.value.length === 0) {
    error.value = "Tuliskan catatan revisi atau beri tanda catatan pada halaman sebelum mengirim.";
    return;
  }
  actionLoading.value = true;
  error.value = "";
  try {
    await api.qcRevise(props.assignmentId, {
      notes: generalNotes.value.trim(),
      page_notes: pageAnnotations.value,
    });
    emit("revised", props.assignmentId);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal mengirim revisi.";
  } finally {
    actionLoading.value = false;
  }
}

onMounted(() => {
  loadQc();
});
</script>

<template>
  <div class="qc-modal-backdrop" @paste="handlePasteOrDrop">
    <div class="qc-studio-window">
      <!-- HEADER TOOLBAR -->
      <header class="qc-header">
        <div class="qc-header-left">
          <Button
            icon="pi pi-arrow-left"
            label="Tutup QC"
            severity="secondary"
            size="small"
            @click="emit('close')"
          />
          <div v-if="data" class="qc-title-box">
            <h2>{{ data.assignment.manga }}</h2>
            <div class="qc-meta-tags">
              <span class="chapter-badge">Chapter {{ data.assignment.chapter }}</span>
              <Tag :value="data.assignment.role" severity="info" />
              <span class="staff-tag">
                <i class="pi pi-user"></i>
                {{ data.assignment.staff_name || 'Staff' }}
              </span>
              <span v-if="data.raw_source" class="raw-source-badge">
                RAW: {{ data.raw_source.toUpperCase() }} ({{ data.raw_page_count }} Hal)
              </span>
            </div>
          </div>
        </div>

        <!-- LAYOUT SWITCHER -->
        <div class="qc-mode-switch">
          <button
            :class="{ active: layoutMode === 'webtoon-dual' }"
            title="Scroll Webtoon Berdampingan (RAW kiri, Edit kanan)"
            @click="layoutMode = 'webtoon-dual'"
          >
            <i class="pi pi-columns"></i>
            <span>Webtoon Dual Strip</span>
          </button>
          <button
            :class="{ active: layoutMode === 'webtoon-single' }"
            title="Scroll Webtoon Tunggal"
            @click="layoutMode = 'webtoon-single'"
          >
            <i class="pi pi-bars"></i>
            <span>Webtoon RAW</span>
          </button>
        </div>

        <!-- STRIP WIDTH & CONTROLS -->
        <div class="qc-header-right">
          <div class="strip-width-controls">
            <span class="control-label"><i class="pi pi-arrows-h"></i> Lebar:</span>
            <button
              :class="{ active: stripWidth === 520 }"
              @click="stripWidth = 520"
            >
              520px
            </button>
            <button
              :class="{ active: stripWidth === 640 }"
              @click="stripWidth = 640"
            >
              640px
            </button>
            <button
              :class="{ active: stripWidth === 800 }"
              @click="stripWidth = 800"
            >
              800px
            </button>
            <button
              :class="{ active: stripWidth === 1000 }"
              @click="stripWidth = 1000"
            >
              Lebar
            </button>
          </div>

          <label v-if="layoutMode === 'webtoon-dual'" class="sync-checkbox" title="Kunci scroll agar bergerak bersamaan">
            <input v-model="syncScroll" type="checkbox" />
            <span>Sync Scroll</span>
          </label>
        </div>
      </header>

      <!-- NOTICES -->
      <div v-if="error" class="qc-notice error">
        <i class="pi pi-exclamation-circle"></i>
        <span>{{ error }}</span>
        <button @click="error = ''">×</button>
      </div>
      <div v-if="success" class="qc-notice success">
        <i class="pi pi-check-circle"></i>
        <span>{{ success }}</span>
        <button @click="success = ''">×</button>
      </div>

      <!-- MAIN WEBTOON VIEWER CANVAS -->
      <main class="qc-main-canvas">
        <div v-if="loading" class="qc-loading-state">
          <i class="pi pi-spin pi-spinner" style="font-size: 2.2rem; color: #38bdf8;"></i>
          <p>Memuat potongan gambar RAW Webtoon...</p>
        </div>

        <template v-else-if="data">
          <!-- 1. DUAL-COLUMN CONTINUOUS WEBTOON SCROLL (DEFAULT) -->
          <div v-if="layoutMode === 'webtoon-dual'" class="qc-webtoon-dual-layout">
            <!-- Left Column: Full RAW Webtoon Strip -->
            <div
              ref="rawScrollContainer"
              class="webtoon-column raw-column"
              @scroll="onRawScroll"
            >
              <div class="column-sticky-header">
                <span class="strip-badge raw">
                  <i class="pi pi-image"></i> RAW ASLI ({{ data.raw_source?.toUpperCase() || 'Scraper' }})
                </span>
                <span class="strip-count">{{ data.raw_pages.length }} Potongan Halaman</span>
              </div>

              <div class="webtoon-strip" :style="{ width: `${stripWidth}px` }">
                <div
                  v-for="(rawUrl, idx) in data.raw_pages"
                  :id="`page-slice-${idx + 1}`"
                  :key="idx"
                  class="webtoon-slice-wrapper"
                  :class="{ active: activePage === idx + 1 }"
                  @click="activePage = idx + 1"
                >
                  <div class="slice-marker">
                    <span>Hal. {{ idx + 1 }}</span>
                    <a
                      :href="rawUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="slice-direct-link"
                      title="Buka gambar RAW asli di tab baru"
                      @click.stop
                    >
                      <i class="pi pi-external-link"></i>
                    </a>
                    <button
                      type="button"
                      title="Beri catatan pada halaman ini"
                      @click.stop="activePage = idx + 1"
                    >
                      <i class="pi pi-pencil"></i>
                    </button>
                  </div>
                  <img
                    :src="rawUrl"
                    :alt="`RAW Hal ${idx + 1}`"
                    class="webtoon-slice-img"
                    referrerpolicy="no-referrer"
                    crossorigin="anonymous"
                    loading="lazy"
                    @error="handleImageError($event, rawUrl)"
                  />
                </div>
              </div>
            </div>

            <!-- Right Column: Staff Edit Webtoon Strip / Drive Embed -->
            <div
              ref="editScrollContainer"
              class="webtoon-column edit-column"
              @scroll="onEditScroll"
            >
              <div class="column-sticky-header">
                <span class="strip-badge edit">
                  <i class="pi pi-check-circle"></i> HASIL STAFF ({{ data.assignment.staff_name || 'Staff' }})
                </span>
                <div class="header-tools">
                  <a
                    v-if="data.gdrive_link"
                    :href="data.gdrive_link"
                    target="_blank"
                    rel="noopener"
                    class="gdrive-pill-link"
                  >
                    <i class="pi pi-external-link"></i> Buka Google Drive
                  </a>
                </div>
              </div>

              <!-- When staff uploaded or local images are available -->
              <div
                v-if="Object.keys(localSubmissionPages).length > 0 || data.submission_pages.length > 0"
                class="webtoon-strip"
                :style="{ width: `${stripWidth}px` }"
              >
                <div
                  v-for="(_, idx) in Array(totalPages)"
                  :key="idx"
                  class="webtoon-slice-wrapper"
                  :class="{ active: activePage === idx + 1 }"
                  @click="activePage = idx + 1"
                >
                  <div class="slice-marker edit">
                    <span>Edit Hal. {{ idx + 1 }}</span>
                    <a
                      v-if="localSubmissionPages[idx + 1] || data.submission_pages[idx]"
                      :href="localSubmissionPages[idx + 1] || data.submission_pages[idx]"
                      target="_blank"
                      rel="noopener noreferrer"
                      class="slice-direct-link"
                      title="Buka gambar hasil staff di tab baru"
                      @click.stop
                    >
                      <i class="pi pi-external-link"></i>
                    </a>
                  </div>
                  <img
                    v-if="localSubmissionPages[idx + 1] || data.submission_pages[idx]"
                    :src="localSubmissionPages[idx + 1] || data.submission_pages[idx]"
                    :alt="`Edit Hal ${idx + 1}`"
                    class="webtoon-slice-img"
                    referrerpolicy="no-referrer"
                    crossorigin="anonymous"
                    loading="lazy"
                    @error="handleImageError($event, localSubmissionPages[idx + 1] || data.submission_pages[idx])"
                  />
                  <div v-else class="slice-empty-placeholder">
                    <span>Halaman {{ idx + 1 }} belum ditempel</span>
                  </div>
                </div>
              </div>

              <!-- Interactive Google Drive Embed View -->
              <div v-else-if="data.gdrive_embed_url" class="gdrive-full-embed">
                <div class="embed-top-bar">
                  <span>Folder Google Drive Pengumpulan Staff:</span>
                  <a :href="data.gdrive_link" target="_blank" rel="noopener">Tab Baru ↗</a>
                </div>
                <iframe
                  :src="data.gdrive_embed_url"
                  title="Google Drive Folder Preview"
                  class="gdrive-iframe-view"
                  allowfullscreen
                ></iframe>
              </div>

              <!-- Drop & Paste Prompt Area -->
              <div v-else class="webtoon-drop-zone" @drop.prevent="handlePasteOrDrop" @dragover.prevent>
                <i class="pi pi-cloud-upload"></i>
                <h3>Tempel / Drag & Drop Gambar Hasil Edit Staff</h3>
                <p>Kamu bisa langsung tekan <b>Ctrl + V</b> untuk menempelkan gambar hasil TS halaman terpilih (Hal. {{ activePage }}).</p>
                <div class="quick-url-input">
                  <InputText v-model="customImageInput" placeholder="Atau paste URL gambar langsung..." size="small" @keyup.enter="setCustomImageUrl" />
                  <Button label="Terapkan" size="small" @click="setCustomImageUrl" />
                </div>
                <a v-if="data.gdrive_link" :href="data.gdrive_link" target="_blank" rel="noopener" class="p-button p-button-sm p-button-secondary">
                  Buka Folder Google Drive Staff
                </a>
              </div>
            </div>
          </div>

          <!-- 2. SINGLE COLUMN CONTINUOUS WEBTOON SCROLL -->
          <div v-else-if="layoutMode === 'webtoon-single'" class="qc-webtoon-single-layout">
            <div class="webtoon-strip" :style="{ width: `${stripWidth}px` }">
              <div
                v-for="(rawUrl, idx) in data.raw_pages"
                :id="`page-slice-${idx + 1}`"
                :key="idx"
                class="webtoon-slice-wrapper"
                :class="{ active: activePage === idx + 1 }"
                @click="activePage = idx + 1"
              >
                <div class="slice-marker">
                  <span>Halaman {{ idx + 1 }}</span>
                  <a
                    :href="rawUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="slice-direct-link"
                    title="Buka gambar RAW asli di tab baru"
                    @click.stop
                  >
                    <i class="pi pi-external-link"></i>
                  </a>
                  <button type="button" @click.stop="activePage = idx + 1">
                    <i class="pi pi-pencil"></i> Beri Catatan
                  </button>
                </div>
                <img
                  :src="rawUrl"
                  :alt="`RAW Hal ${idx + 1}`"
                  class="webtoon-slice-img"
                  referrerpolicy="no-referrer"
                  crossorigin="anonymous"
                  loading="lazy"
                  @error="handleImageError($event, rawUrl)"
                />
              </div>
            </div>
          </div>
        </template>
      </main>

      <!-- BOTTOM REVIEW & DECISION PANEL -->
      <footer class="qc-footer">
        <!-- Annotation Box for selected page -->
        <div class="qc-annotation-box">
          <div class="annotation-head">
            <span class="page-tag">
              <i class="pi pi-tag"></i> Catatan Halaman {{ activePage }}:
            </span>
            <div class="preset-tags">
              <button type="button" @click="addPresetComment('Typo terjemahan')">Typo</button>
              <button type="button" @click="addPresetComment('Font tidak sesuai SOP')">Font Salah</button>
              <button type="button" @click="addPresetComment('Balon teks terlewat')">Balon Terlewat</button>
              <button type="button" @click="addPresetComment('Redraw kotor/bocor')">Redraw Kotor</button>
              <button type="button" @click="addPresetComment('Ukuran font kekecilan')">Font Kecil</button>
            </div>
          </div>
          <div class="annotation-input-row">
            <InputText
              v-model="newAnnotationComment"
              :placeholder="`Contoh catatan untuk Hal. ${activePage}: Balon tengah typo 'meraka'`"
              size="small"
              @keyup.enter="addAnnotation"
            />
            <Button
              label="Tandai Hal. Ini"
              icon="pi pi-bookmark"
              size="small"
              severity="secondary"
              @click="addAnnotation"
            />
          </div>

          <!-- Active Page Notes List -->
          <div v-if="pageAnnotations.length" class="active-annotations-pills">
            <span
              v-for="note in pageAnnotations"
              :key="note.page"
              class="annotation-pill"
              @click="scrollToPage(note.page)"
            >
              <b>Hal. {{ note.page }}:</b> {{ note.comment }}
              <button type="button" @click.stop="removeAnnotation(note.page)">×</button>
            </span>
          </div>
        </div>

        <!-- Decision Box -->
        <div class="qc-decision-box">
          <textarea
            v-model="generalNotes"
            placeholder="Catatan umum tambahan untuk staff di Discord (opsional)..."
            class="qc-general-textarea"
            rows="2"
          ></textarea>

          <div class="qc-decision-buttons">
            <Button
              label="Minta Revisi"
              icon="pi pi-refresh"
              severity="danger"
              :loading="actionLoading"
              @click="requestRevision"
            />
            <Button
              label="Setujui (Approve)"
              icon="pi pi-check"
              severity="success"
              :loading="actionLoading"
              @click="approveAssignment"
            />
          </div>
        </div>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.qc-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(4, 7, 18, 0.96);
  backdrop-filter: blur(14px);
  z-index: 9999;
  display: flex;
  flex-direction: column;
}

.qc-studio-window {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  color: var(--text, #f1f5f9);
}

/* HEADER */
.qc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 18px;
  background: rgba(15, 23, 42, 0.95);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  gap: 16px;
  flex-shrink: 0;
}

.qc-header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.qc-title-box h2 {
  font-size: 16px;
  font-weight: 700;
  margin: 0;
  color: #fff;
}

.qc-meta-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 2px;
  font-size: 12px;
}

.chapter-badge {
  background: rgba(99, 102, 241, 0.2);
  color: #818cf8;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
}

.staff-tag {
  color: var(--muted, #94a3b8);
  display: flex;
  align-items: center;
  gap: 4px;
}

.raw-source-badge {
  background: rgba(16, 185, 129, 0.15);
  color: #34d399;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
}

/* MODE SWITCH */
.qc-mode-switch {
  display: flex;
  background: rgba(0, 0, 0, 0.4);
  padding: 3px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.qc-mode-switch button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.15s ease;
}

.qc-mode-switch button.active {
  background: #3b82f6;
  color: #fff;
}

/* STRIP WIDTH CONTROLS */
.qc-header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.strip-width-controls {
  display: flex;
  align-items: center;
  gap: 4px;
  background: rgba(0, 0, 0, 0.3);
  padding: 3px 6px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.control-label {
  font-size: 11px;
  color: #94a3b8;
  margin-right: 4px;
}

.strip-width-controls button {
  background: transparent;
  border: none;
  color: #94a3b8;
  font-size: 11px;
  font-weight: 600;
  padding: 4px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}

.strip-width-controls button.active {
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
}

.sync-checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #94a3b8;
  cursor: pointer;
  user-select: none;
}

/* NOTICES */
.qc-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  font-size: 13px;
}

.qc-notice.error {
  background: rgba(239, 68, 68, 0.2);
  color: #fca5a5;
  border-bottom: 1px solid rgba(239, 68, 68, 0.3);
}

.qc-notice.success {
  background: rgba(16, 185, 129, 0.2);
  color: #6ee7b7;
  border-bottom: 1px solid rgba(16, 185, 129, 0.3);
}

.qc-notice button {
  margin-left: auto;
  background: transparent;
  border: none;
  color: inherit;
  font-size: 16px;
  cursor: pointer;
}

/* MAIN CANVAS */
.qc-main-canvas {
  flex: 1;
  overflow: hidden;
  position: relative;
  background: #080c14;
}

.qc-loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 14px;
  color: #94a3b8;
}

/* DUAL WEBTOON LAYOUT */
.qc-webtoon-dual-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  height: 100%;
  gap: 2px;
  background: rgba(255, 255, 255, 0.04);
}

.webtoon-column {
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: #080c14;
  scroll-behavior: smooth;
}

.column-sticky-header {
  position: sticky;
  top: 0;
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  background: rgba(15, 23, 42, 0.9);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  z-index: 20;
}

.strip-badge.raw {
  color: #38bdf8;
  font-weight: 700;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.strip-badge.edit {
  color: #a78bfa;
  font-weight: 700;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.strip-count {
  font-size: 11px;
  color: #64748b;
}

.gdrive-pill-link {
  color: #38bdf8;
  font-size: 11px;
  text-decoration: none;
  background: rgba(56, 189, 248, 0.1);
  padding: 4px 10px;
  border-radius: 12px;
  border: 1px solid rgba(56, 189, 248, 0.2);
  display: flex;
  align-items: center;
  gap: 4px;
}

/* WEBTOON STRIP */
.webtoon-strip {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px 0;
}

.webtoon-slice-wrapper {
  position: relative;
  width: 100%;
  display: block;
  line-height: 0;
  cursor: pointer;
  transition: all 0.15s ease;
}

.webtoon-slice-wrapper.active {
  outline: 2px solid #38bdf8;
  box-shadow: 0 0 20px rgba(56, 189, 248, 0.3);
}

.slice-marker {
  position: absolute;
  top: 8px;
  left: 8px;
  background: rgba(15, 23, 42, 0.85);
  backdrop-filter: blur(6px);
  color: #38bdf8;
  border: 1px solid rgba(56, 189, 248, 0.3);
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 6px;
  z-index: 10;
  opacity: 0.8;
  transition: opacity 0.2s;
}

.slice-marker.edit {
  color: #a78bfa;
  border-color: rgba(167, 139, 250, 0.3);
}

.slice-direct-link {
  color: #38bdf8;
  font-size: 11px;
  display: flex;
  align-items: center;
  text-decoration: none;
  opacity: 0.8;
  transition: opacity 0.15s;
}

.slice-direct-link:hover {
  opacity: 1;
  color: #fff;
}

.webtoon-slice-wrapper:hover .slice-marker {
  opacity: 1;
}

.slice-marker button {
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
}

.webtoon-slice-img {
  width: 100%;
  display: block;
  height: auto;
}

.slice-empty-placeholder {
  width: 100%;
  height: 300px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.02);
  border: 1px dashed rgba(255, 255, 255, 0.1);
  color: #64748b;
  font-size: 12px;
}

/* GDRIVE EMBED IN WEBTOON COLUMN */
.gdrive-full-embed {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.embed-top-bar {
  display: flex;
  justify-content: space-between;
  padding: 6px 14px;
  background: rgba(0, 0, 0, 0.3);
  font-size: 11px;
  color: #94a3b8;
}

.gdrive-iframe-view {
  flex: 1;
  width: 100%;
  border: none;
}

/* DROP ZONE */
.webtoon-drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  margin: auto;
  padding: 30px;
  max-width: 480px;
  background: rgba(255, 255, 255, 0.02);
  border: 2px dashed rgba(255, 255, 255, 0.12);
  border-radius: 12px;
  gap: 12px;
  color: #94a3b8;
}

.webtoon-drop-zone i {
  font-size: 2.5rem;
  color: #38bdf8;
}

.webtoon-drop-zone h3 {
  font-size: 16px;
  color: #fff;
  margin: 0;
}

.webtoon-drop-zone p {
  font-size: 12px;
  line-height: 1.5;
  margin: 0;
}

.quick-url-input {
  display: flex;
  gap: 6px;
  width: 100%;
}

/* SINGLE WEBTOON LAYOUT */
.qc-webtoon-single-layout {
  height: 100%;
  overflow-y: auto;
  display: flex;
  justify-content: center;
  background: #080c14;
}

/* FOOTER / ANNOTATION & DECISION */
.qc-footer {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  padding: 12px 18px;
  background: rgba(15, 23, 42, 0.98);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  flex-shrink: 0;
}

.qc-annotation-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.annotation-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.page-tag {
  font-size: 12px;
  font-weight: 700;
  color: #38bdf8;
  display: flex;
  align-items: center;
  gap: 4px;
}

.preset-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.preset-tags button {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #94a3b8;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}

.preset-tags button:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}

.annotation-input-row {
  display: flex;
  gap: 6px;
}

.annotation-input-row input {
  flex: 1;
}

.active-annotations-pills {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  max-height: 50px;
  overflow-y: auto;
}

.annotation-pill {
  background: rgba(239, 68, 68, 0.15);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.3);
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.annotation-pill button {
  background: transparent;
  border: none;
  color: inherit;
  font-weight: bold;
  cursor: pointer;
}

.qc-decision-box {
  display: flex;
  gap: 12px;
  align-items: center;
}

.qc-general-textarea {
  flex: 1;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #fff;
  border-radius: 6px;
  padding: 8px;
  font-size: 12px;
  resize: none;
  font-family: inherit;
}

.qc-decision-buttons {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 150px;
}

@media (max-width: 900px) {
  .qc-webtoon-dual-layout {
    grid-template-columns: 1fr;
  }
  .qc-footer {
    grid-template-columns: 1fr;
  }
  .qc-header {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
