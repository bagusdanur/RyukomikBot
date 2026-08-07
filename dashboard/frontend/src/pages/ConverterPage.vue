<script setup lang="ts">
import { ref, computed } from "vue";
import Button from "primevue/button";
import { getCsrfToken } from "../api";

const quality = ref(95);
const selectedFiles = ref<File[]>([]);
const converting = ref(false);
const progress = ref(0);
const progressStep = ref("");
const error = ref("");
const success = ref("");
const dropActive = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

const totalSize = computed(() =>
  selectedFiles.value.reduce((n, f) => n + f.size, 0)
);
const estWebpSize = computed(() => totalSize.value * (quality.value / 100) * 0.35);

function onDrop(e: DragEvent) {
  e.preventDefault();
  dropActive.value = false;
  if (e.dataTransfer?.files) addFiles(e.dataTransfer.files);
}
function onDragOver(e: DragEvent) {
  e.preventDefault();
  dropActive.value = true;
}
function onFileSelect(e: Event) {
  const input = e.target as HTMLInputElement;
  if (input.files) addFiles(input.files);
  input.value = "";
}
function addFiles(fileList: FileList) {
  const valid = Array.from(fileList).filter((f) => /\.(png|jpe?g)$/i.test(f.name));
  selectedFiles.value = [...selectedFiles.value, ...valid];
  success.value = "";
  error.value = "";
}
function removeFile(idx: number) {
  selectedFiles.value = selectedFiles.value.filter((_, i) => i !== idx);
}
function clearAll() {
  selectedFiles.value = [];
  success.value = "";
  error.value = "";
  progress.value = 0;
  progressStep.value = "";
}
function setProgress(pct: number, step: string) {
  progress.value = pct;
  progressStep.value = step;
}
function fmt(bytes: number) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}
async function convert() {
  if (!selectedFiles.value.length) return;
  converting.value = true;
  error.value = "";
  success.value = "";
  setProgress(0, "Mengupload...");
  const formData = new FormData();
  formData.append("quality", String(quality.value));
  selectedFiles.value.forEach((f) => formData.append("files", f));
  try {
    const res = await new Promise<{ status: number; blob: Blob; filename: string }>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/tools/webp-convert");
      const csrf = getCsrfToken();
      if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) setProgress(Math.round((e.loaded / e.total) * 60), `Mengupload... ${fmt(e.loaded)} / ${fmt(e.total)}`);
      };
      xhr.upload.onload = () => setProgress(70, "Mengkonversi gambar...");
      xhr.onload = () => {
        if (xhr.status >= 400) setProgress(0, "");
        else setProgress(100, "Selesai!");
        const cd = xhr.getResponseHeader("content-disposition");
        let fname = "webp_converted.zip";
        if (cd) { const m = cd.match(/filename="?([^"]+)"?/); if (m) fname = m[1]; }
        resolve({ status: xhr.status, blob: xhr.response as Blob, filename: fname });
      };
      xhr.onerror = () => reject(new Error("Network error"));
      xhr.responseType = "blob";
      xhr.send(formData);
    });
    if (res.status !== 200) {
      let msg = `Error ${res.status}`;
      try { const j = JSON.parse(await res.blob.text()); msg = j.detail || msg; } catch {}
      throw new Error(msg);
    }
    const url = URL.createObjectURL(res.blob);
    const a = document.createElement("a"); a.href = url; a.download = res.filename; a.click();
    URL.revokeObjectURL(url);
    success.value = `${res.filename} (${fmt(res.blob.size)}) berhasil diunduh`;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Konversi gagal.";
    setProgress(0, "");
  } finally {
    converting.value = false;
  }
}
</script>

<template>
  <!-- Header: match OperationsPage style -->
  <div class="toolbar">
    <div>
      <p class="eyebrow">TOOLS</p>
      <h3>WebP Converter</h3>
      <small>Convert PNG/JPG ke WebP. Gambar >16.000px di-split otomatis tanpa kehilangan kualitas.</small>
    </div>
  </div>

  <!-- Stat cards: same style as OperationsPage stats-grid -->
  <div class="stats-grid">
    <article>
      <span class="stat-icon blue"><i class="pi pi-image"></i></span>
      <div><small>Format Output</small><strong>WebP</strong></div>
    </article>
    <article>
      <span class="stat-icon violet"><i class="pi pi-bolt"></i></span>
      <div><small>Mode Proses</small><strong>In-Memory</strong></div>
    </article>
    <article>
      <span class="stat-icon amber"><i class="pi pi-database"></i></span>
      <div><small>Penyimpanan</small><strong>0 B Disk</strong></div>
    </article>
    <article>
      <span class="stat-icon green"><i class="pi pi-shield"></i></span>
      <div><small>Keamanan</small><strong>Auto-Clean</strong></div>
    </article>
  </div>

  <!-- Quality Settings -->
  <section class="panel converter-section">
    <div class="section-title">
      <span><i class="pi pi-sliders-h"></i> Pengaturan Kualitas</span>
      <div class="quality-est" v-if="selectedFiles.length">
        {{ fmt(totalSize) }} → ~{{ fmt(estWebpSize) }}
      </div>
    </div>
    <div class="quality-row">
      <div class="quality-display">
        <span class="quality-num">{{ quality }}</span>
        <span class="quality-pct">%</span>
      </div>
      <input type="range" v-model.number="quality" min="50" max="100" step="1" class="slider" />
      <div class="presets">
        <button v-for="q in [80, 85, 90, 95, 100]" :key="q" :class="{ active: quality === q }" @click="quality = q">{{ q }}</button>
      </div>
    </div>
  </section>

  <!-- Drop Zone -->
  <section class="panel drop-zone" :class="{ active: dropActive, compact: selectedFiles.length > 0 }"
    @drop="onDrop" @dragover="onDragOver" @dragleave="dropActive = false" @click="fileInput?.click()">
    <i class="pi pi-cloud-upload"></i>
    <p>Drag & drop gambar atau tap untuk pilih</p>
    <div class="format-tags"><span>PNG</span><span>JPG</span><span>JPEG</span></div>
    <input ref="fileInput" type="file" multiple accept=".png,.jpg,.jpeg" style="display:none" @change="onFileSelect" />
  </section>

  <!-- File List -->
  <section v-if="selectedFiles.length" class="panel converter-section">
    <div class="section-title">
      <span>{{ selectedFiles.length }} file &middot; {{ fmt(totalSize) }}</span>
      <Button label="Hapus semua" severity="danger" size="small" text @click="clearAll" />
    </div>
    <div class="file-list">
      <div v-for="(f, i) in selectedFiles" :key="i" class="file-row">
        <span class="file-icon"><i class="pi pi-image"></i></span>
        <span class="file-name">{{ f.name }}</span>
        <span class="file-size">{{ fmt(f.size) }}</span>
        <button class="file-del" @click="removeFile(i)"><i class="pi pi-times"></i></button>
      </div>
    </div>
  </section>

  <!-- Progress -->
  <section v-if="converting || progress === 100" class="panel converter-section">
    <div class="section-title">
      <span><i :class="progress === 100 ? 'pi pi-check-circle' : 'pi pi-spinner pi-spin'"></i> {{ progressStep }}</span>
      <span class="pct">{{ progress }}%</span>
    </div>
    <div class="progress-track"><div class="progress-fill" :style="{ width: progress + '%' }"></div></div>
  </section>

  <!-- Status -->
  <div v-if="error" class="msg msg-error"><i class="pi pi-exclamation-triangle"></i> {{ error }}</div>
  <div v-if="success" class="msg msg-ok"><i class="pi pi-check-circle"></i> {{ success }}</div>

  <!-- Action -->
  <Button v-if="selectedFiles.length" :label="`Convert ${selectedFiles.length} file ke WebP`"
    icon="pi pi-bolt" class="convert-btn" :loading="converting" :disabled="converting" @click="convert" />
</template>

<style scoped>
/* Stats grid — same as dashboard */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  margin-top: 16px;
}
.stats-grid article {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px;
  padding: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.stats-grid article .stat-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-icon.blue { background: rgba(59,130,246,0.12); color: #3b82f6; }
.stat-icon.violet { background: rgba(139,92,246,0.12); color: #8b5cf6; }
.stat-icon.amber { background: rgba(245,158,11,0.12); color: #f59e0b; }
.stat-icon.green { background: rgba(34,197,94,0.12); color: #22c55e; }
.stats-grid article small { color: #666; font-size: 0.75rem; }
.stats-grid article strong { color: #ccc; font-size: 0.9rem; display: block; margin-top: 1px; }

/* Section */
.converter-section { margin-top: 14px; }
.section-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}
.section-title span { font-weight: 600; font-size: 0.85rem; display: flex; align-items: center; gap: 8px; }
.section-title i { color: var(--primary-color, #4f9cf7); }
.quality-est {
  font-size: 0.75rem;
  color: #4f9cf7;
  background: rgba(79,156,247,0.1);
  padding: 3px 10px;
  border-radius: 6px;
  font-weight: 600;
}

/* Quality */
.quality-row { display: flex; flex-direction: column; gap: 12px; }
.quality-display { display: flex; align-items: baseline; }
.quality-num { font-size: 2.6rem; font-weight: 800; color: var(--primary-color, #4f9cf7); line-height: 1; }
.quality-pct { font-size: 1rem; color: #555; margin-left: 2px; font-weight: 600; }
.slider {
  width: 100%; height: 6px; -webkit-appearance: none; appearance: none;
  background: #1e293b; border-radius: 3px; outline: none;
}
.slider::-webkit-slider-thumb {
  -webkit-appearance: none; width: 22px; height: 22px; border-radius: 50%;
  background: var(--primary-color, #4f9cf7); cursor: pointer;
  box-shadow: 0 0 10px rgba(79,156,247,0.35); border: 3px solid #0c1020;
}
.presets { display: flex; gap: 6px; }
.presets button {
  flex: 1; padding: 7px 0; border: 1px solid #222; border-radius: 8px;
  background: #111; color: #666; font-size: 0.82rem; font-weight: 600;
  cursor: pointer; transition: all 0.15s;
}
.presets button.active {
  background: var(--primary-color, #4f9cf7); color: #fff;
  border-color: var(--primary-color, #4f9cf7);
}
.presets button:not(.active):hover { border-color: #444; color: #aaa; }

/* Drop Zone */
.drop-zone {
  margin-top: 14px; border: 2px dashed #222; border-radius: 14px;
  padding: 36px 20px; text-align: center; cursor: pointer; transition: all 0.2s;
}
.drop-zone:hover, .drop-zone.active { border-color: #334155; background: rgba(255,255,255,0.015); }
.drop-zone.compact { padding: 20px; }
.drop-zone i { font-size: 2rem; color: #333; display: block; margin-bottom: 8px; }
.drop-zone p { color: #555; font-size: 0.85rem; margin: 0 0 10px; }
.format-tags { display: flex; gap: 6px; justify-content: center; }
.format-tags span {
  padding: 2px 10px; border-radius: 6px; background: #111; color: #444;
  font-size: 0.7rem; font-weight: 700; letter-spacing: 0.5px;
}

/* File List */
.file-list { display: flex; flex-direction: column; gap: 4px; max-height: 280px; overflow-y: auto; }
.file-row {
  display: flex; align-items: center; gap: 10px; padding: 9px 12px;
  background: rgba(255,255,255,0.02); border-radius: 8px; font-size: 0.82rem;
}
.file-icon { color: #3b82f6; font-size: 0.85rem; }
.file-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #aaa; }
.file-size { color: #555; white-space: nowrap; font-size: 0.75rem; }
.file-del {
  width: 24px; height: 24px; border: none; border-radius: 6px;
  background: transparent; color: #555; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.file-del:hover { background: rgba(239,68,68,0.1); color: #ef4444; }

/* Progress */
.progress-track { height: 6px; background: #111; border-radius: 3px; overflow: hidden; }
.progress-fill {
  height: 100%; background: var(--primary-color, #4f9cf7); border-radius: 3px;
  transition: width 0.4s ease;
}
.pct { color: #555; font-weight: 700; font-size: 0.8rem; }

/* Messages */
.msg {
  margin-top: 12px; padding: 11px 14px; border-radius: 10px;
  font-size: 0.82rem; display: flex; align-items: center; gap: 8px;
}
.msg-error { background: rgba(239,68,68,0.08); color: #ef4444; }
.msg-ok { background: rgba(34,197,94,0.08); color: #22c55e; }

/* Button */
.convert-btn {
  margin-top: 18px; width: 100%; padding: 13px !important;
  font-size: 0.9rem !important; border-radius: 10px !important;
}
</style>
