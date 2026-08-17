<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import Button from "primevue/button";
import Tag from "primevue/tag";
import Select from "primevue/select";
import InputText from "primevue/inputtext";
import QcViewerPage from "./QcViewerPage.vue";
import {
  api,
  type Assignment,
  type ProjectTrackerItem,
} from "../api";

const props = defineProps<{
  initialAssignmentId?: number | null;
}>();

const emit = defineEmits<{
  (e: "task-approved", id: number): void;
  (e: "task-revised", id: number): void;
}>();

const loading = ref(true);
const assignments = ref<Assignment[]>([]);
const projects = ref<ProjectTrackerItem[]>([]);
const selectedTaskId = ref<number | null>(props.initialAssignmentId || null);

// Quick mode: Review from existing task OR Inspect from Project
const mode = ref<"task" | "project">("task");
const selectedProjectSlug = ref<string>("");
const customChapter = ref<string>("1");

const submittedTasks = computed(() =>
  assignments.value.filter((a) => a.status === "submitted"),
);

const activeReviewTasks = computed(() =>
  assignments.value.filter((a) =>
    ["submitted", "revision", "claimed", "approved"].includes(a.status),
  ),
);

async function loadData() {
  loading.value = true;
  try {
    const [taskRes, projRes] = await Promise.all([
      api.assignments(),
      api.projects("", "all", "all", 1, 100),
    ]);
    assignments.value = taskRes;
    projects.value = projRes.items || [];

    // Auto-select first submitted task if none selected
    if (!selectedTaskId.value && submittedTasks.value.length > 0) {
      selectedTaskId.value = submittedTasks.value[0].id;
    } else if (!selectedTaskId.value && activeReviewTasks.value.length > 0) {
      selectedTaskId.value = activeReviewTasks.value[0].id;
    }
  } catch (e) {
    console.error("Gagal memuat daftar tugas untuk QC:", e);
  } finally {
    loading.value = false;
  }
}

function handleApproved(taskId: number) {
  emit("task-approved", taskId);
  loadData();
}

function handleRevised(taskId: number) {
  emit("task-revised", taskId);
  loadData();
}

watch(
  () => props.initialAssignmentId,
  (newId) => {
    if (newId) {
      selectedTaskId.value = newId;
    }
  },
);

onMounted(loadData);
</script>

<template>
  <div class="qc-studio-page">
    <!-- Top Header / Task Selector Toolbar -->
    <section class="qc-top-bar panel">
      <div class="top-bar-left">
        <div class="studio-badge">
          <i class="pi pi-search"></i>
          <span>STUDIO QUALITY CONTROL (QC)</span>
        </div>
        <h3>Studio Inspeksi & Review Webtoon</h3>
        <p class="subtitle">
          Bandingkan RAW Webtoon langsung dengan hasil Google Drive staff dalam tampilan scroll bersandingan.
        </p>
      </div>

      <div class="top-bar-right">
        <!-- Task Selector Dropdown -->
        <div class="task-selector-box">
          <label><i class="pi pi-list"></i> Pilih Tugas untuk Di-Review:</label>
          <select v-model="selectedTaskId" class="task-select">
            <option :value="null" disabled>-- Pilih Pekerjaan / Tugas --</option>
            <optgroup v-if="submittedTasks.length" label="⭐ Menunggu Review (Prioritas)">
              <option v-for="t in submittedTasks" :key="t.id" :value="t.id">
                🔴 {{ t.manga }} • Ch. {{ t.chapter }} ({{ t.role }}) — {{ t.staff_name || 'Staff' }}
              </option>
            </optgroup>
            <optgroup label="Semua Tugas Aktif">
              <option v-for="t in activeReviewTasks" :key="t.id" :value="t.id">
                {{ t.manga }} • Ch. {{ t.chapter }} ({{ t.role }} - {{ t.status }}) — {{ t.staff_name || 'Staff' }}
              </option>
            </optgroup>
          </select>
        </div>

        <Button
          icon="pi pi-refresh"
          severity="secondary"
          size="small"
          title="Muat ulang daftar tugas"
          @click="loadData"
        />
      </div>
    </section>

    <!-- Quick Queue Pills if multiple tasks are waiting review -->
    <div v-if="submittedTasks.length > 0" class="quick-queue-bar">
      <span class="queue-label"><i class="pi pi-bell"></i> Antrean Menunggu Review ({{ submittedTasks.length }}):</span>
      <div class="queue-chips">
        <button
          v-for="t in submittedTasks"
          :key="t.id"
          class="queue-chip"
          :class="{ active: selectedTaskId === t.id }"
          @click="selectedTaskId = t.id"
        >
          <b>{{ t.manga }}</b> Ch. {{ t.chapter }}
          <span class="chip-staff">({{ t.staff_name }})</span>
        </button>
      </div>
    </div>

    <!-- MAIN VIEWER AREA -->
    <main class="qc-viewer-viewport">
      <div v-if="loading" class="qc-loading-card">
        <i class="pi pi-spin pi-spinner" style="font-size: 2.5rem; color: #38bdf8;"></i>
        <p>Memuat antrean tugas QC...</p>
      </div>

      <div v-else-if="!selectedTaskId" class="qc-empty-state">
        <i class="pi pi-check-circle" style="font-size: 3rem; color: #10b981;"></i>
        <h3>Tidak Ada Tugas yang Dipilih</h3>
        <p>Pilih salah satu tugas dari dropdown di atas untuk memulai inspeksi side-by-side.</p>
      </div>

      <!-- Embedded Full-Featured QC Viewer -->
      <div v-else class="qc-embedded-wrapper">
        <QcViewerPage
          :assignment-id="selectedTaskId"
          @close="selectedTaskId = null"
          @approved="handleApproved"
          @revised="handleRevised"
        />
      </div>
    </main>
  </div>
</template>

<style scoped>
.qc-studio-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 100px);
  min-height: 700px;
}

.qc-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  background: rgba(15, 23, 42, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  gap: 20px;
}

.studio-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(56, 189, 248, 0.15);
  color: #38bdf8;
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
  margin-bottom: 4px;
}

.qc-top-bar h3 {
  font-size: 18px;
  font-weight: 700;
  margin: 0;
  color: #fff;
}

.subtitle {
  font-size: 12px;
  color: #94a3b8;
  margin: 2px 0 0 0;
}

.top-bar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.task-selector-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.task-selector-box label {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 600;
}

.task-select {
  background: rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(56, 189, 248, 0.3);
  color: #fff;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  min-width: 320px;
  outline: none;
  cursor: pointer;
}

.task-select:focus {
  border-color: #38bdf8;
  box-shadow: 0 0 10px rgba(56, 189, 248, 0.3);
}

/* QUICK QUEUE CHIPS */
.quick-queue-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 8px;
  overflow-x: auto;
}

.queue-label {
  font-size: 12px;
  font-weight: 700;
  color: #fca5a5;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 6px;
}

.queue-chips {
  display: flex;
  gap: 8px;
  overflow-x: auto;
}

.queue-chip {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: #f1f5f9;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}

.queue-chip:hover {
  border-color: #38bdf8;
  color: #38bdf8;
}

.queue-chip.active {
  background: #38bdf8;
  color: #040712;
  font-weight: 700;
  border-color: #38bdf8;
}

.chip-staff {
  opacity: 0.75;
  font-size: 11px;
}

/* MAIN VIEWPORT */
.qc-viewer-viewport {
  flex: 1;
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.qc-loading-card,
.qc-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  background: rgba(15, 23, 42, 0.6);
  color: #94a3b8;
  text-align: center;
}

.qc-embedded-wrapper {
  width: 100%;
  height: 100%;
  position: relative;
}

@media (max-width: 900px) {
  .qc-top-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .task-select {
    min-width: 100%;
  }
}
</style>
