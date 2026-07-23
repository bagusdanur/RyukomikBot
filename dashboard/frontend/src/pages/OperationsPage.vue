<script setup lang="ts">
import { onMounted, ref } from "vue";
import Button from "primevue/button";
import Tag from "primevue/tag";
import { api, type OperationSnapshot } from "../api";

const loading = ref(true);
const error = ref("");
const data = ref<OperationSnapshot | null>(null);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    data.value = await api.operations();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Status operasional gagal dimuat.";
  } finally {
    loading.value = false;
  }
}
async function resolveEvent(id: number) {
  await api.resolveOperation(id);
  await load();
}
async function retryNotification(id: number) {
  await api.retryNotification(id);
  await load();
}
async function syncStaff() {
  await api.syncStaff();
  await load();
}
const localTime = (value: unknown) =>
  value ? new Intl.DateTimeFormat("id-ID", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Jakarta",
  }).format(new Date(String(value).replace(" ", "T") + "Z")) : "Belum pernah";

onMounted(load);
</script>

<template>
  <div class="toolbar operations-head">
    <div>
      <p class="eyebrow">SYSTEM HEALTH</p>
      <h3>Operasional</h3>
      <small>Error aktif, retry notifikasi, scheduler, backup, dan cache Discord.</small>
    </div>
    <Button label="Muat ulang" icon="pi pi-refresh" severity="secondary" @click="load" />
  </div>
  <div v-if="loading" class="operations-skeleton">
    <span v-for="n in 4" :key="n"></span>
  </div>
  <div v-else-if="error" class="empty-state">
    <i class="pi pi-exclamation-triangle"></i><h3>Gagal memuat operasional</h3>
    <p>{{ error }}</p><Button label="Coba lagi" @click="load" />
  </div>
  <template v-else-if="data">
    <div class="stats-grid">
      <article><span class="stat-icon red"><i class="pi pi-exclamation-circle"></i></span>
        <div><small>Error aktif</small><strong>{{ data.events.length }}</strong></div></article>
      <article><span class="stat-icon amber"><i class="pi pi-send"></i></span>
        <div><small>Antrean notifikasi</small><strong>{{ data.outbox.length }}</strong></div></article>
      <article><span class="stat-icon blue"><i class="pi pi-database"></i></span>
        <div><small>Backup tersimpan</small><strong>{{ data.backups.length }}</strong></div></article>
      <article><span class="stat-icon violet"><i class="pi pi-users"></i></span>
        <div><small>Cache staff</small><strong>{{ data.staff_cache.count }}</strong></div></article>
    </div>
    <section class="panel operation-section">
      <div class="section-title"><div><span>Error Aktif</span><small>Masalah serupa digabung otomatis.</small></div></div>
      <div v-if="!data.events.length" class="empty">Tidak ada error aktif.</div>
      <article v-for="event in data.events" :key="event.id" class="operation-row">
        <div><Tag :severity="event.severity === 'critical' || event.severity === 'error' ? 'danger' : 'warn'"
          :value="`${event.component} • ${event.severity}`" />
          <h4>{{ event.message }}</h4><small>{{ localTime(event.last_seen_at) }} • {{ event.occurrence_count }} kali</small></div>
        <Button label="Tandai selesai" severity="secondary" size="small" @click="resolveEvent(Number(event.id))" />
      </article>
    </section>
    <section class="panel operation-section">
      <div class="section-title"><div><span>Notifikasi Bermasalah</span><small>Pending, retry, atau gagal permanen.</small></div></div>
      <div v-if="!data.outbox.length" class="empty">Antrean notifikasi bersih.</div>
      <article v-for="item in data.outbox" :key="item.id" class="operation-row">
        <div><Tag :severity="item.status === 'failed' ? 'danger' : 'warn'" :value="item.status" />
          <h4>{{ item.notification_type }}</h4><small>Percobaan {{ item.attempt_count }} • {{ item.last_error || 'Menunggu worker' }}</small></div>
        <Button v-if="item.status === 'failed'" label="Coba lagi" size="small" @click="retryNotification(Number(item.id))" />
      </article>
    </section>
    <div class="summary-grid">
      <section class="panel operation-section"><div class="section-title"><span>Scheduler</span></div>
        <article v-for="job in data.schedulers" :key="job.job_name" class="operation-row compact">
          <div><h4>{{ job.job_name }}</h4><small>Berhasil: {{ localTime(job.last_succeeded_at) }}</small></div></article>
      </section>
      <section class="panel operation-section"><div class="section-title"><span>Backup Database</span></div>
        <article v-for="backup in data.backups.slice(0,5)" :key="backup.id" class="operation-row compact">
          <div><h4>{{ backup.filename }}</h4><small>{{ backup.integrity_status }} • {{ localTime(backup.created_at) }}</small></div></article>
        <div class="button-row"><Button label="Sinkronkan Discord" icon="pi pi-sync" severity="secondary" @click="syncStaff" /></div>
      </section>
    </div>
  </template>
</template>
