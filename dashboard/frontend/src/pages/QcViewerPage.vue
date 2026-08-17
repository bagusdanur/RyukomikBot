<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
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

// Inspection Modes: "side-by-side" | "slider" | "webtoon"
const viewMode = ref<"side-by-side" | "slider" | "webtoon">("side-by-side");

// Page Navigation
const currentPage = ref(1);
const zoomLevel = ref(100);
const sliderPosition = ref(50); // 0 to 100%

// Custom/Local Submission Image Overrides (for private GDrive/files)
const localSubmissionPages = ref<Record<number, string>>({});
const customImageInput = ref("");

// Revision & Annotations
const generalNotes = ref("");
const pageAnnotations = ref<QcPageAnnotation[]>([]);
const newAnnotationComment = ref("");

const totalPages = computed(() => {
  if (!data.value) return 1;
  const rawCount = data.value.raw_pages.length;
  const subCount = Object.keys(localSubmissionPages.value).length;
  return Math.max(rawCount, subCount, 1);
});

const currentRawImage = computed(() => {
  if (!data.value || !data.value.raw_pages.length) return null;
  const idx = currentPage.value - 1;
  return data.value.raw_pages[idx] || null;
});

const currentSubmissionImage = computed(() => {
  // Check local override first
  if (localSubmissionPages.value[currentPage.value]) {
    return localSubmissionPages.value[currentPage.value];
  }
  // Check backend submission pages
  if (data.value && data.value.submission_pages.length) {
    return data.value.submission_pages[currentPage.value - 1] || null;
  }
  return null;
});

async function loadQc() {
  loading.value = true;
  error.value = "";
  try {
    data.value = await api.qcDetail(props.assignmentId);
    currentPage.value = 1;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal memuat data QC.";
  } finally {
    loading.value = false;
  }
}

function prevPage() {
  if (currentPage.value > 1) currentPage.value--;
}

function nextPage() {
  if (currentPage.value < totalPages.value) currentPage.value++;
}

function zoomIn() {
  if (zoomLevel.value < 250) zoomLevel.value += 15;
}

function zoomOut() {
  if (zoomLevel.value > 50) zoomLevel.value -= 15;
}

function resetZoom() {
  zoomLevel.value = 100;
}

function fitWidth() {
  zoomLevel.value = 100;
}

function handleKeydown(e: KeyboardEvent) {
  // Ignore when typing in inputs/textareas
  if (["INPUT", "TEXTAREA"].includes((e.target as HTMLElement)?.tagName)) return;
  if (e.key === "ArrowLeft") {
    e.preventDefault();
    prevPage();
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    nextPage();
  } else if (e.key === "+" || e.key === "=") {
    zoomIn();
  } else if (e.key === "-") {
    zoomOut();
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
    (a) => a.page === currentPage.value,
  );
  if (existingIndex >= 0) {
    pageAnnotations.value[existingIndex].comment = newAnnotationComment.value.trim();
  } else {
    pageAnnotations.value.push({
      page: currentPage.value,
      comment: newAnnotationComment.value.trim(),
    });
  }
  newAnnotationComment.value = "";
}

function removeAnnotation(page: number) {
  pageAnnotations.value = pageAnnotations.value.filter((a) => a.page !== page);
}

function handlePasteOrDrop(e: ClipboardEvent | DragEvent) {
  // Check for image files pasted or dropped
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
          localSubmissionPages.value[currentPage.value] = String(event.target.result);
          success.value = `Gambar hasil editan Halaman ${currentPage.value} berhasil ditempel.`;
        }
      };
      reader.readAsDataURL(file);
    }
  }
}

function setCustomImageUrl() {
  if (!customImageInput.value.trim()) return;
  localSubmissionPages.value[currentPage.value] = customImageInput.value.trim();
  customImageInput.value = "";
  success.value = `URL gambar Halaman ${currentPage.value} diterapkan.`;
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
  window.addEventListener("keydown", handleKeydown);
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeydown);
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

        <!-- VIEW MODE SELECTOR -->
        <div class="qc-mode-switch">
          <button
            :class="{ active: viewMode === 'side-by-side' }"
            title="Berdampingan (RAW kiri, Hasil kanan)"
            @click="viewMode = 'side-by-side'"
          >
            <i class="pi pi-columns"></i>
            <span>Berdampingan</span>
          </button>
          <button
            :class="{ active: viewMode === 'slider' }"
            title="Curtain Slider (Sebelum & Sesudah)"
            @click="viewMode = 'slider'"
          >
            <i class="pi pi-sliders-h"></i>
            <span>Slider Geser</span>
          </button>
          <button
            :class="{ active: viewMode === 'webtoon' }"
            title="Webtoon (Scroll Vertikal)"
            @click="viewMode = 'webtoon'"
          >
            <i class="pi pi-bars"></i>
            <span>Webtoon</span>
          </button>
        </div>

        <!-- ZOOM & NAVIGATION CONTROLS -->
        <div class="qc-header-right">
          <div class="qc-page-nav" v-if="viewMode !== 'webtoon'">
            <Button
              icon="pi pi-chevron-left"
              size="small"
              text
              :disabled="currentPage <= 1"
              @click="prevPage"
            />
            <span class="page-indicator">
              <b>{{ currentPage }}</b> / {{ totalPages }}
            </span>
            <Button
              icon="pi pi-chevron-right"
              size="small"
              text
              :disabled="currentPage >= totalPages"
              @click="nextPage"
            />
          </div>

          <div class="qc-zoom-controls">
            <Button icon="pi pi-minus" size="small" text @click="zoomOut" title="Zoom Out (-)" />
            <span class="zoom-level">{{ zoomLevel }}%</span>
            <Button icon="pi pi-plus" size="small" text @click="zoomIn" title="Zoom In (+)" />
            <Button icon="pi pi-refresh" size="small" text @click="resetZoom" title="Reset Zoom" />
          </div>
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

      <!-- MAIN CANVAS AREA -->
      <main class="qc-main-canvas" :class="viewMode">
        <div v-if="loading" class="qc-loading-state">
          <i class="pi pi-spin pi-spinner" style="font-size: 2rem"></i>
          <p>Mengambil halaman RAW dan data tugas...</p>
        </div>

        <template v-else-if="data">
          <!-- 1. SIDE-BY-SIDE MODE -->
          <div v-if="viewMode === 'side-by-side'" class="qc-side-by-side-container">
            <!-- Left Pane: RAW Image -->
            <div class="qc-pane raw-pane">
              <div class="pane-label">
                <span class="badge raw">RAW Asli • Hal. {{ currentPage }}</span>
                <small v-if="data.raw_source">{{ data.raw_source.toUpperCase() }}</small>
              </div>
              <div class="pane-viewport">
                <img
                  v-if="currentRawImage"
                  :src="currentRawImage"
                  alt="RAW Page"
                  :style="{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top center' }"
                  class="qc-image"
                  loading="lazy"
                />
                <div v-else class="image-placeholder">
                  <i class="pi pi-image"></i>
                  <p>Halaman RAW {{ currentPage }} tidak ditemukan.</p>
                </div>
              </div>
            </div>

            <!-- Right Pane: Submission Result -->
            <div class="qc-pane submission-pane">
              <div class="pane-label">
                <span class="badge edit">Hasil Staff • Hal. {{ currentPage }}</span>
                <div class="pane-actions">
                  <a
                    v-if="data.gdrive_link"
                    :href="data.gdrive_link"
                    target="_blank"
                    rel="noopener"
                    class="gdrive-quick-btn"
                  >
                    <i class="pi pi-external-link"></i> Buka GDrive
                  </a>
                </div>
              </div>
              <div class="pane-viewport">
                <img
                  v-if="currentSubmissionImage"
                  :src="currentSubmissionImage"
                  alt="Hasil Staff"
                  :style="{ transform: `scale(${zoomLevel / 100})`, transformOrigin: 'top center' }"
                  class="qc-image"
                />
                <!-- Embed or Paste Placeholder when direct image isn't available -->
                <div v-else-if="data.gdrive_embed_url" class="gdrive-embed-box">
                  <iframe
                    :src="data.gdrive_embed_url"
                    title="Google Drive Submission Folder"
                    class="gdrive-iframe"
                    allowfullscreen
                  ></iframe>
                </div>
                <div v-else class="image-drop-placeholder" @drop.prevent="handlePasteOrDrop" @dragover.prevent>
                  <i class="pi pi-cloud-upload"></i>
                  <p><b>Tempel (Ctrl+V) / Drag & Drop Gambar Hasil TS di sini</b></p>
                  <small>Atau masukkan URL gambar langsung untuk Halaman {{ currentPage }}:</small>
                  <div class="url-input-row">
                    <InputText v-model="customImageInput" placeholder="https://..." size="small" @keyup.enter="setCustomImageUrl" />
                    <Button label="Terapkan" size="small" @click="setCustomImageUrl" />
                  </div>
                  <a v-if="data.gdrive_link" :href="data.gdrive_link" target="_blank" rel="noopener" class="p-button p-button-sm p-button-secondary">
                    Buka Link Folder GDrive Staff
                  </a>
                </div>
              </div>
            </div>
          </div>

          <!-- 2. SLIDER / CURTAIN MODE -->
          <div v-else-if="viewMode === 'slider'" class="qc-slider-container">
            <div class="slider-viewport" :style="{ width: `${zoomLevel}%` }">
              <!-- Background Image: RAW -->
              <img
                v-if="currentRawImage"
                :src="currentRawImage"
                alt="RAW Background"
                class="slider-bg-img"
              />

              <!-- Foreground Clip: Submission -->
              <div
                class="slider-fg-clip"
                :style="{ clipPath: `inset(0 ${100 - sliderPosition}% 0 0)` }"
              >
                <img
                  v-if="currentSubmissionImage"
                  :src="currentSubmissionImage"
                  alt="Submission Foreground"
                  class="slider-fg-img"
                />
                <div v-else-if="currentRawImage" class="slider-notice-overlay">
                  <p>Tempel gambar hasil staff (Ctrl+V) untuk melihat overlay slider.</p>
                </div>
              </div>

              <!-- Draggable Divider Handle -->
              <div class="slider-divider" :style="{ left: `${sliderPosition}%` }">
                <div class="slider-handle">
                  <i class="pi pi-arrows-h"></i>
                </div>
              </div>

              <!-- Hidden Range Input for full interactive control -->
              <input
                v-model="sliderPosition"
                type="range"
                min="0"
                max="100"
                class="slider-range-input"
              />
            </div>
          </div>

          <!-- 3. WEBTOON CONTINUOUS SCROLL MODE -->
          <div v-else-if="viewMode === 'webtoon'" class="qc-webtoon-container">
            <div
              v-for="(rawUrl, idx) in data.raw_pages"
              :key="idx"
              class="webtoon-page-row"
            >
              <div class="webtoon-page-meta">Halaman {{ idx + 1 }}</div>
              <div class="webtoon-page-images">
                <img :src="rawUrl" :alt="`RAW Hal ${idx + 1}`" class="webtoon-img" loading="lazy" />
                <img
                  v-if="localSubmissionPages[idx + 1]"
                  :src="localSubmissionPages[idx + 1]"
                  :alt="`Edit Hal ${idx + 1}`"
                  class="webtoon-img"
                />
              </div>
            </div>
          </div>
        </template>
      </main>

      <!-- BOTTOM REVIEW & DECISION PANEL -->
      <footer class="qc-footer">
        <!-- Annotation Box for current page -->
        <div class="qc-annotation-box">
          <div class="annotation-head">
            <span class="page-tag">📝 Catatan Hal. {{ currentPage }}:</span>
            <div class="preset-tags">
              <button type="button" @click="addPresetComment('Typo terjemahan')">Typo</button>
              <button type="button" @click="addPresetComment('Font tidak sesuai SOP')">Font Salah</button>
              <button type="button" @click="addPresetComment('Balon narasi terlewat')">Balon Terlewat</button>
              <button type="button" @click="addPresetComment('Redraw kurang rapi')">Redraw Kotor</button>
              <button type="button" @click="addPresetComment('Ukuran font kekecilan')">Font Kekecilan</button>
            </div>
          </div>
          <div class="annotation-input-row">
            <InputText
              v-model="newAnnotationComment"
              placeholder="Contoh: Balon tengah ada typo 'meraka' -> 'mereka'"
              size="small"
              @keyup.enter="addAnnotation"
            />
            <Button
              label="Simpan di Hal Ini"
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
              @click="currentPage = note.page"
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
            placeholder="Catatan umum untuk staff (opsional jika sudah ada catatan per halaman)..."
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
  background: rgba(4, 7, 18, 0.94);
  backdrop-filter: blur(12px);
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
  padding: 6px 12px;
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

/* HEADER RIGHT */
.qc-header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.qc-page-nav {
  display: flex;
  align-items: center;
  gap: 4px;
  background: rgba(0, 0, 0, 0.3);
  padding: 2px 6px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.page-indicator {
  font-size: 13px;
  color: #94a3b8;
  min-width: 60px;
  text-align: center;
}

.page-indicator b {
  color: #fff;
}

.qc-zoom-controls {
  display: flex;
  align-items: center;
  gap: 2px;
  background: rgba(0, 0, 0, 0.3);
  padding: 2px 6px;
  border-radius: 6px;
}

.zoom-level {
  font-size: 12px;
  color: #94a3b8;
  min-width: 45px;
  text-align: center;
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
  background: #090d16;
}

.qc-loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: #94a3b8;
}

/* SIDE-BY-SIDE */
.qc-side-by-side-container {
  display: grid;
  grid-template-columns: 1fr 1fr;
  height: 100%;
  gap: 2px;
  background: rgba(255, 255, 255, 0.05);
}

.qc-pane {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #090d16;
  overflow: hidden;
}

.pane-label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 14px;
  background: rgba(15, 23, 42, 0.6);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 12px;
}

.pane-label .badge.raw {
  color: #38bdf8;
  font-weight: 700;
}

.pane-label .badge.edit {
  color: #a78bfa;
  font-weight: 700;
}

.gdrive-quick-btn {
  color: #38bdf8;
  text-decoration: none;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.pane-viewport {
  flex: 1;
  overflow: auto;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 16px;
}

.qc-image {
  max-width: 100%;
  height: auto;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.8);
  border-radius: 4px;
  transition: transform 0.1s ease-out;
}

.image-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #64748b;
  gap: 8px;
}

.gdrive-embed-box {
  width: 100%;
  height: 100%;
}

.gdrive-iframe {
  width: 100%;
  height: 100%;
  border: none;
  border-radius: 6px;
}

.image-drop-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 24px;
  background: rgba(255, 255, 255, 0.02);
  border: 2px dashed rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  gap: 10px;
  color: #94a3b8;
  max-width: 440px;
  margin: auto;
}

.url-input-row {
  display: flex;
  gap: 6px;
  width: 100%;
}

/* SLIDER / CURTAIN */
.qc-slider-container {
  height: 100%;
  overflow: auto;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 16px;
}

.slider-viewport {
  position: relative;
  max-width: 900px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.9);
  user-select: none;
}

.slider-bg-img,
.slider-fg-img {
  width: 100%;
  display: block;
}

.slider-fg-clip {
  position: absolute;
  inset: 0;
  overflow: hidden;
}

.slider-notice-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  text-align: center;
  padding: 20px;
}

.slider-divider {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #38bdf8;
  pointer-events: none;
  box-shadow: 0 0 10px rgba(56, 189, 248, 0.8);
}

.slider-handle {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 32px;
  height: 32px;
  background: #38bdf8;
  color: #040712;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}

.slider-range-input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  cursor: ew-resize;
  z-index: 10;
  margin: 0;
}

/* WEBTOON CONTINUOUS */
.qc-webtoon-container {
  height: 100%;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24px;
}

.webtoon-page-row {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  max-width: 1200px;
  width: 100%;
}

.webtoon-page-meta {
  font-size: 12px;
  color: #94a3b8;
  font-weight: 600;
}

.webtoon-page-images {
  display: flex;
  gap: 12px;
  justify-content: center;
  width: 100%;
}

.webtoon-img {
  max-width: 580px;
  width: 100%;
  border-radius: 4px;
}

/* FOOTER / REVIEW PANEL */
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
  .qc-side-by-side-container {
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
