<script setup lang="ts">
import { ref, onMounted } from "vue";
import Button from "primevue/button";
import { api } from "../api";

const loading = ref(true);
const error = ref("");
const data = ref<{
  workload: Array<Record<string, unknown>>;
  upcoming_deadlines: Array<Record<string, unknown>>;
  overdue: Array<Record<string, unknown>>;
  summary: Record<string, number>;
} | null>(null);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    data.value = await api.staffWorkload();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal memuat data.";
  } finally {
    loading.value = false;
  }
}

const avatar = (id: string, hash: string | null | undefined) =>
  hash ? `https://cdn.discordapp.com/avatars/${id}/${hash}.png?size=64` : "";
const initials = (name: string) => (name || "?").slice(0, 2).toUpperCase();

const loadColors: Record<string, string> = {
  overload: "#ef4444",
  busy: "#f59e0b",
  normal: "#22c55e",
  idle: "#555",
};
const loadLabels: Record<string, string> = {
  overload: "Overload",
  busy: "Sibuk",
  normal: "Normal",
  idle: "Kosong",
};

onMounted(load);
</script>

<template>
  <div class="toolbar">
    <div>
      <p class="eyebrow">OVERVIEW</p>
      <h3>Staff Workload</h3>
      <small>Siapa yang sibuk, siapa yang kosong, deadline mendekat.</small>
    </div>
    <Button label="Muat ulang" icon="pi pi-refresh" severity="secondary" @click="load" :loading="loading" />
  </div>

  <div v-if="loading && !data" class="skel-grid"><div v-for="n in 4" :key="n" class="skel-card"></div></div>
  <div v-else-if="error" class="msg msg-error"><i class="pi pi-exclamation-triangle"></i> {{ error }}</div>

  <template v-else-if="data">
    <!-- Summary cards -->
    <div class="stats-grid">
      <article>
        <span class="stat-icon blue"><i class="pi pi-users"></i></span>
        <div><small>Staff Aktif</small><strong>{{ data.summary.total_staff }}</strong></div>
      </article>
      <article>
        <span class="stat-icon red"><i class="pi pi-exclamation-circle"></i></span>
        <div><small>Overload</small><strong>{{ data.summary.overload }}</strong></div>
      </article>
      <article>
        <span class="stat-icon amber"><i class="pi pi-clock"></i></span>
        <div><small>Deadline Lewat</small><strong>{{ data.summary.overdue_count }}</strong></div>
      </article>
      <article>
        <span class="stat-icon green"><i class="pi pi-check-circle"></i></span>
        <div><small>Idle</small><strong>{{ data.summary.idle }}</strong></div>
      </article>
    </div>

    <!-- Workload grid -->
    <section class="panel workload-section">
      <div class="section-title"><span><i class="pi pi-users"></i> Beban Kerja</span></div>
      <div class="staff-grid">
        <div v-for="w in data.workload" :key="String(w.staff_id)" class="staff-card">
          <div class="staff-head">
            <div class="staff-avatar">
              <img v-if="avatar(String(w.staff_id), String(w.avatar || ''))" :src="avatar(String(w.staff_id), String(w.avatar || ''))" />
              <span v-else>{{ initials(String(w.username || '')) }}</span>
            </div>
            <div class="staff-info">
              <strong>{{ w.username }}</strong>
              <span class="load-badge" :style="{ color: loadColors[String(w.load_level)] }">
                {{ loadLabels[String(w.load_level)] }} • {{ w.total_active }} tugas
              </span>
            </div>
          </div>
          <div class="status-bar">
            <div v-for="(cnt, status) in (w.by_status as Record<string, number>)" :key="String(status)" class="status-chip">
              <span class="chip-label">{{ status }}</span>
              <span class="chip-count">{{ cnt }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-if="!data.workload.length" class="empty">Belum ada staff dengan tugas aktif.</div>
    </section>

    <!-- Overdue -->
    <section v-if="data.overdue.length" class="panel workload-section">
      <div class="section-title">
        <span><i class="pi pi-exclamation-triangle"></i> Deadline Terlewat</span>
        <span class="badge-red">{{ data.overdue.length }}</span>
      </div>
      <div class="deadline-list">
        <div v-for="d in data.overdue" :key="`${d.staff_id}-${d.manga}-${d.chapter}`" class="deadline-row overdue">
          <div class="dl-info">
            <strong>{{ d.manga }}</strong>
            <small>Ch {{ d.chapter }} • {{ d.staff_name }}</small>
          </div>
          <span class="dl-date">{{ d.deadline_at }}</span>
        </div>
      </div>
    </section>

    <!-- Upcoming -->
    <section v-if="data.upcoming_deadlines.length" class="panel workload-section">
      <div class="section-title">
        <span><i class="pi pi-clock"></i> Deadline 7 Hari</span>
        <span class="badge-amber">{{ data.upcoming_deadlines.length }}</span>
      </div>
      <div class="deadline-list">
        <div v-for="d in data.upcoming_deadlines" :key="`${d.staff_id}-${d.manga}-${d.chapter}`" class="deadline-row">
          <div class="dl-info">
            <strong>{{ d.manga }}</strong>
            <small>Ch {{ d.chapter }} • {{ d.staff_name }}</small>
          </div>
          <span class="dl-date">{{ d.deadline_at }}</span>
        </div>
      </div>
    </section>
  </template>
</template>

<style scoped>
.stats-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 16px; }
@media (min-width: 480px) { .stats-grid { grid-template-columns: repeat(4, 1fr); } }
.stats-grid article {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px; padding: 14px; display: flex; align-items: center; gap: 12px;
}
.stat-icon { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.stat-icon.blue { background: rgba(59,130,246,0.12); color: #3b82f6; }
.stat-icon.red { background: rgba(239,68,68,0.12); color: #ef4444; }
.stat-icon.amber { background: rgba(245,158,11,0.12); color: #f59e0b; }
.stat-icon.green { background: rgba(34,197,94,0.12); color: #22c55e; }
.stats-grid article small { color: #666; font-size: 0.75rem; }
.stats-grid article strong { color: #ccc; font-size: 0.9rem; display: block; margin-top: 1px; }

.workload-section { margin-top: 14px; }
.section-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
.section-title span { font-weight: 600; font-size: 0.85rem; display: flex; align-items: center; gap: 8px; }
.section-title i { color: var(--primary-color, #4f9cf7); }
.badge-red { background: rgba(239,68,68,0.15); color: #ef4444; padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; }
.badge-amber { background: rgba(245,158,11,0.15); color: #f59e0b; padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 700; }

/* Staff grid */
.staff-grid { display: grid; grid-template-columns: 1fr; gap: 8px; }
@media (min-width: 480px) { .staff-grid { grid-template-columns: repeat(2, 1fr); } }
.staff-card { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04); border-radius: 10px; padding: 12px; }
.staff-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.staff-avatar { width: 32px; height: 32px; border-radius: 50%; background: #222; display: flex; align-items: center; justify-content: center; font-size: 0.7rem; color: #888; overflow: hidden; flex-shrink: 0; }
.staff-avatar img { width: 100%; height: 100%; object-fit: cover; }
.staff-info { flex: 1; min-width: 0; }
.staff-info strong { font-size: 0.82rem; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.load-badge { font-size: 0.7rem; font-weight: 600; }
.status-bar { display: flex; gap: 4px; flex-wrap: wrap; }
.status-chip { display: flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 6px; background: rgba(255,255,255,0.04); font-size: 0.7rem; }
.chip-label { color: #666; text-transform: capitalize; }
.chip-count { color: #aaa; font-weight: 700; }

/* Deadlines */
.deadline-list { display: flex; flex-direction: column; gap: 6px; }
.deadline-row { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: rgba(255,255,255,0.02); border-radius: 8px; }
.deadline-row.overdue { border-left: 3px solid #ef4444; }
.dl-info { flex: 1; min-width: 0; }
.dl-info strong { font-size: 0.82rem; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.dl-info small { color: #666; font-size: 0.72rem; }
.dl-date { color: #888; font-size: 0.75rem; white-space: nowrap; }

.empty { color: #555; font-size: 0.85rem; text-align: center; padding: 20px; }
.skel-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 16px; }
.skel-card { height: 80px; background: #111; border-radius: 12px; animation: pulse 1.5s infinite; }
@keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 0.6; } }
.msg { margin-top: 14px; padding: 11px 14px; border-radius: 10px; font-size: 0.82rem; display: flex; align-items: center; gap: 8px; }
.msg-error { background: rgba(239,68,68,0.08); color: #ef4444; }
</style>
