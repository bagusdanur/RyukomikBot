<script setup lang="ts">
import { ref, computed } from "vue";
import Button from "primevue/button";
import { getCsrfToken } from "../api";

interface OcrResult {
  name: string;
  ok: boolean;
  page_num?: number;
  text?: string;
  bubble_count?: number;
  segments?: number;
  error?: string;
}

const selectedFiles = ref<File[]>([]);
const processing = ref(false);
const downloadingTxt = ref(false);
const progress = ref(0);
const progressStep = ref("");
const error = ref("");
const success = ref("");
const results = ref<OcrResult[]>([]);
const dropActive = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const copied = ref<number | null>(null);

const totalSize = computed(() =>
  selectedFiles.value.reduce((n, f) => n + f.size, 0)
);
const okCount = computed(() => results.value.filter((r) => r.ok).length);

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
  const valid = Array.from(fileList).filter((f) => /\.(png|jpe?g|webp)$/i.test(f.name));
  selectedFiles.value = [...selectedFiles.value, ...valid];
  error.value = "";
}
function removeFile(idx: number) {
  selectedFiles.value = selectedFiles.value.filter((_, i) => i !== idx);
}
function clearAll() {
  selectedFiles.value = [];
  results.value = [];
  error.value = "";
  success.value = "";
  progress.value = 0;
  progressStep.value = "";
}
function fmt(bytes: number) {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}
async function copyText(idx: number, text: string) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = idx;
    setTimeout(() => { if (copied.value === idx) copied.value = null; }, 1500);
  } catch {
    error.value = "Gagal menyalin ke clipboard.";
  }
}
function copyAll() {
  const combined = results.value
    .filter((r) => r.ok && r.text)
    .map((r) => `# ${r.name}\n${r.text}`)
    .join("\n\n");
  if (combined) copyText(-1, combined);
}

async function downloadTxt() {
  if (!selectedFiles.value.length || downloadingTxt.value) return;
  // Kalau belum ada hasil OCR, extract dulu
  if (!results.value.length || !results.value.some((r) => r.ok)) {
    await extract();
  }
  // Generate TXT langsung dari hasil yang sudah ada (instant, gak perlu re-OCR)
  const okResults = results.value.filter((r) => r.ok);
  if (!okResults.length) {
    error.value = "Tidak ada hasil OCR untuk di-download.";
    return;
  }
  downloadingTxt.value = true;
  error.value = "";
  success.value = "";
  try {
    const lines: string[] = [];
    okResults.forEach((r, i) => {
      lines.push(`=== HALAMAN ${i + 1} ===`);
      lines.push(r.text || "(tidak ada teks)");
      lines.push("");
    });
    const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "ocr_extract.txt";
    a.click();
    URL.revokeObjectURL(url);
    success.value = "ocr_extract.txt berhasil diunduh";
  } catch (e) {
    error.value = "Gagal generate file TXT.";
  } finally {
    downloadingTxt.value = false;
  }
}

async function extract() {
  if (!selectedFiles.value.length) return;
  processing.value = true;
  error.value = "";
  success.value = "";
  results.value = [];
  progress.value = 10;
  progressStep.value = "Mengupload & memproses (bisa beberapa detik/halaman)...";
  const formData = new FormData();
  selectedFiles.value.forEach((f) => formData.append("files", f));
  try {
    const res = await new Promise<{ status: number; text: string }>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/tools/ocr-extract");
      const csrf = getCsrfToken();
      if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) progress.value = Math.round((e.loaded / e.total) * 40);
      };
      xhr.upload.onload = () => { progress.value = 50; progressStep.value = "OCR berjalan di MiMo v2.5..."; };
      xhr.onload = () => { progress.value = 100; resolve({ status: xhr.status, text: xhr.responseText }); };
      xhr.onerror = () => reject(new Error("Network error"));
      xhr.send(formData);
    });
    const json = JSON.parse(res.text);
    if (res.status !== 200) throw new Error(json.detail || `Error ${res.status}`);
    results.value = json.results || [];
    progressStep.value = "Selesai!";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "OCR gagal.";
    progress.value = 0;
  } finally {
    processing.value = false;
  }
}
</script>

<template>
  <div class="toolbar">
    <div>
      <p class="eyebrow">TOOLS</p>
      <h3>OCR Extractor</h3>
      <small>Ekstrak teks dialog English dari RAW webtoon buat translator. Ditenagai MiMo v2.5 vision, otomatis skip SFX Jepang.</small>
    </div>
  </div>

  <div class="stats-grid">
    <article>
      <span class="stat-icon blue"><i class="pi pi-language"></i></span>
      <div><small>Bahasa</small><strong>English</strong></div>
    </article>
    <article>
      <span class="stat-icon violet"><i class="pi pi-sparkles"></i></span>
      <div><small>Engine</small><strong>MiMo v2.5</strong></div>
    </article>
    <article>
      <span class="stat-icon amber"><i class="pi pi-bolt"></i></span>
      <div><small>Kecepatan</small><strong>~6 dtk/hal</strong></div>
    </article>
    <article>
      <span class="stat-icon green"><i class="pi pi-shield"></i></span>
      <div><small>Penyimpanan</small><strong>0 B Disk</strong></div>
    </article>
  </div>

  <!-- Drop Zone -->
  <section class="panel drop-zone" :class="{ active: dropActive, compact: selectedFiles.length > 0 }"
    @drop="onDrop" @dragover="onDragOver" @dragleave="dropActive = false" @click="fileInput?.click()">
    <i class="pi pi-cloud-upload"></i>
    <p>Drag & drop RAW atau tap untuk pilih</p>
    <div class="format-tags"><span>PNG</span><span>JPG</span><span>WEBP</span></div>
    <input ref="fileInput" type="file" multiple accept=".png,.jpg,.jpeg,.webp" style="display:none" @change="onFileSelect" />
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
  <section v-if="processing || downloadingTxt || progress === 100" class="panel converter-section">
    <div class="section-title">
      <span>
        <i :class="progress === 100 ? 'pi pi-check-circle' : 'pi pi-spinner pi-spin'"></i>
        {{ downloadingTxt ? 'Download file .txt...' : progressStep }}
      </span>
      <span v-if="!downloadingTxt" class="pct">{{ progress }}%</span>
    </div>
    <div v-if="!downloadingTxt" class="progress-track"><div class="progress-fill" :style="{ width: progress + '%' }"></div></div>
  </section>

  <div v-if="error" class="msg msg-error"><i class="pi pi-exclamation-triangle"></i> {{ error }}</div>
  <div v-if="success" class="msg msg-ok"><i class="pi pi-check-circle"></i> {{ success }}</div>

  <!-- Results -->
  <section v-if="results.length" class="converter-section">
    <div class="section-title">
      <span><i class="pi pi-file-edit"></i> Hasil OCR &middot; {{ okCount }}/{{ results.length }} berhasil</span>
      <div class="result-actions">
        <Button label="Salin semua" icon="pi pi-copy" size="small" text @click="copyAll" />
        <Button label="Download .txt" icon="pi pi-download" size="small" text @click="downloadTxt" :loading="downloadingTxt" :disabled="downloadingTxt" />
      </div>
    </div>
    <div v-for="(r, i) in results" :key="i" class="result-card" :class="{ failed: !r.ok }">
      <div class="result-head">
        <span class="result-name"><i :class="r.ok ? 'pi pi-check-circle ok' : 'pi pi-times-circle bad'"></i> {{ r.name }}</span>
        <span v-if="r.ok" class="result-meta">{{ r.bubble_count }} baris</span>
        <button v-if="r.ok && r.text" class="copy-btn" @click="copyText(i, r.text!)">
          <i :class="copied === i ? 'pi pi-check' : 'pi pi-copy'"></i>
          {{ copied === i ? 'Tersalin' : 'Salin' }}
        </button>
      </div>
      <pre v-if="r.ok" class="result-text">{{ r.text }}</pre>
      <p v-else class="result-err">{{ r.error }}</p>
    </div>
  </section>

  <!-- Actions -->
  <div class="action-row">
    <Button v-if="selectedFiles.length" :label="`Ekstrak teks dari ${selectedFiles.length} file`"
      icon="pi pi-sparkles" class="convert-btn" :loading="processing" :disabled="processing" @click="extract" />
    <Button v-if="okCount > 1" label="Download hasil .txt" icon="pi pi-download" class="convert-btn txt-btn" severity="secondary"
      :loading="downloadingTxt" :disabled="downloadingTxt" @click="downloadTxt" />
  </div>
</template>

<style scoped>
.stats-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 16px; }
.stats-grid article {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px; padding: 14px; display: flex; align-items: center; gap: 12px;
}
.stats-grid article .stat-icon {
  width: 36px; height: 36px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.stat-icon.blue { background: rgba(59,130,246,0.12); color: #3b82f6; }
.stat-icon.violet { background: rgba(139,92,246,0.12); color: #8b5cf6; }
.stat-icon.amber { background: rgba(245,158,11,0.12); color: #f59e0b; }
.stat-icon.green { background: rgba(34,197,94,0.12); color: #22c55e; }
.stats-grid article small { color: #666; font-size: 0.75rem; }
.stats-grid article strong { color: #ccc; font-size: 0.9rem; display: block; margin-top: 1px; }

.converter-section { margin-top: 14px; }
.section-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.section-title span { font-weight: 600; font-size: 0.85rem; display: flex; align-items: center; gap: 8px; }
.section-title i { color: var(--primary-color, #4f9cf7); }
.result-actions { display: flex; gap: 6px; }

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

.progress-track { height: 6px; background: #111; border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--primary-color, #4f9cf7); border-radius: 3px; transition: width 0.4s ease; }
.pct { color: #555; font-weight: 700; font-size: 0.8rem; }

/* Result cards */
.result-card {
  background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px; padding: 12px 14px; margin-bottom: 10px;
}
.result-card.failed { border-color: rgba(239,68,68,0.25); }
.result-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.result-name { flex: 1; font-size: 0.82rem; color: #bbb; font-weight: 600;
  display: flex; align-items: center; gap: 7px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-name .ok { color: #22c55e; }
.result-name .bad { color: #ef4444; }
.result-meta { font-size: 0.72rem; color: #555; white-space: nowrap; }
.copy-btn {
  border: 1px solid #2a2a2a; background: #131313; color: #888;
  border-radius: 7px; padding: 4px 10px; font-size: 0.72rem; font-weight: 600;
  cursor: pointer; display: flex; align-items: center; gap: 5px; white-space: nowrap;
}
.copy-btn:hover { border-color: var(--primary-color, #4f9cf7); color: var(--primary-color, #4f9cf7); }
.result-text {
  margin: 0; padding: 10px 12px; background: #0c0c0c; border-radius: 8px;
  color: #ccc; font-size: 0.82rem; line-height: 1.6; white-space: pre-wrap;
  word-break: break-word; font-family: ui-monospace, "SF Mono", Menlo, monospace;
  max-height: 340px; overflow-y: auto;
}
.result-err { margin: 0; color: #ef4444; font-size: 0.8rem; }

.msg { margin-top: 12px; padding: 11px 14px; border-radius: 10px; font-size: 0.82rem; display: flex; align-items: center; gap: 8px; }
.msg-error { background: rgba(239,68,68,0.08); color: #ef4444; }
.msg-ok { background: rgba(34,197,94,0.08); color: #22c55e; }

.action-row { display: flex; flex-direction: column; gap: 8px; margin-top: 18px; }
.convert-btn { width: 100%; padding: 13px !important; font-size: 0.9rem !important; border-radius: 10px !important; }
.txt-btn { background: rgba(34,197,94,0.08) !important; border-color: rgba(34,197,94,0.2) !important; }
.txt-btn:hover { border-color: #22c55e !important; }
</style>
