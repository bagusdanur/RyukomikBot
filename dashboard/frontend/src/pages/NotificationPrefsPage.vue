<script setup lang="ts">
import { ref, onMounted } from "vue";
import Button from "primevue/button";
import { api } from "../api";

const loading = ref(true);
const saving = ref(false);
const error = ref("");
const success = ref("");
const types: string[] = ["assignment", "deadline", "payout", "review", "revoke"];
const channels: string[] = ["dm", "ticket", "dashboard"];

interface NotifPref {
  notif_type: string;
  channel: string;
  enabled: boolean;
  reminder_hours: number;
}
const prefs = ref<NotifPref[]>([]);

const typeConfig: Record<string, { icon: string; label: string; color: string }> = {
  assignment: { icon: "pi pi-list-check", label: "Tugas Baru", color: "#3b82f6" },
  deadline: { icon: "pi pi-clock", label: "Deadline", color: "#f59e0b" },
  payout: { icon: "pi pi-money-bill", label: "Pembayaran", color: "#22c55e" },
  review: { icon: "pi pi-file-edit", label: "Review & Revisi", color: "#8b5cf6" },
  revoke: { icon: "pi pi-ban", label: "Penarikan Tugas", color: "#ef4444" },
};

const channelConfig: Record<string, { icon: string; label: string }> = {
  dm: { icon: "pi pi-send", label: "DM" },
  ticket: { icon: "pi pi-ticket", label: "Tiket" },
  dashboard: { icon: "pi pi-desktop", label: "Dashboard" },
};

function getPref(type: string, channel: string): NotifPref {
  let p = prefs.value.find((x) => x.notif_type === type && x.channel === channel);
  if (!p) {
    p = { notif_type: type, channel, enabled: channel === "ticket", reminder_hours: 24 };
    prefs.value.push(p);
  }
  return p;
}

function toggle(type: string, channel: string) {
  const p = getPref(type, channel);
  p.enabled = !p.enabled;
}

function setReminder(type: string, hours: number) {
  prefs.value.filter((p) => p.notif_type === type).forEach((p) => (p.reminder_hours = hours));
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const data = await api.notifPreferences();
    prefs.value = (data.preferences || []) as unknown as NotifPref[];
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal memuat preferensi.";
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  error.value = "";
  success.value = "";
  try {
    await api.updateNotifPreferences(prefs.value);
    success.value = "Preferensi tersimpan!";
    setTimeout(() => (success.value = ""), 3000);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal menyimpan.";
  } finally {
    saving.value = false;
  }
}

function allEnabled(type: string): boolean {
  return channels.every((ch) => getPref(type, ch).enabled);
}

function toggleAll(type: string) {
  const enable = !allEnabled(type);
  channels.forEach((ch) => (getPref(type, ch).enabled = enable));
}

onMounted(load);
</script>

<template>
  <div class="toolbar">
    <div>
      <p class="eyebrow">PENGATURAN</p>
      <h3>Notifikasi</h3>
      <small>Atur kapan dan ke mana notifikasi dikirim.</small>
    </div>
    <Button label="Simpan" icon="pi pi-save" @click="save" :loading="saving" />
  </div>

  <!-- Loading -->
  <div v-if="loading && !prefs.length" class="skel-grid">
    <div v-for="n in 5" :key="n" class="skel-card"></div>
  </div>

  <!-- Error -->
  <div v-else-if="error" class="msg msg-error">
    <i class="pi pi-exclamation-triangle"></i><span>{{ error }}</span>
  </div>

  <template v-else>
    <!-- Success -->
    <transition name="fade">
      <div v-if="success" class="msg msg-ok">
        <i class="pi pi-check-circle"></i><span>{{ success }}</span>
      </div>
    </transition>

    <!-- Cards -->
    <div class="notif-grid">
      <section v-for="type in types" :key="type" class="panel notif-card">
        <!-- Header -->
        <div class="card-head">
          <span class="card-icon" :style="{ color: typeConfig[type]?.color }">
            <i :class="typeConfig[type]?.icon"></i>
          </span>
          <div class="card-title">
            <strong>{{ typeConfig[type]?.label || type }}</strong>
          </div>
          <button class="toggle-all" :class="{ on: allEnabled(type) }" @click="toggleAll(type)">
            <i :class="allEnabled(type) ? 'pi pi-check' : 'pi pi-times'"></i>
          </button>
        </div>

        <!-- Channel toggles -->
        <div class="channel-row">
          <button
            v-for="ch in channels"
            :key="ch"
            :class="['ch-btn', { active: getPref(type, ch).enabled }]"
            @click="toggle(type, ch)"
          >
            <i :class="channelConfig[ch]?.icon"></i>
            <span>{{ channelConfig[ch]?.label }}</span>
          </button>
        </div>

        <!-- Reminder (deadline only) -->
        <div v-if="type === 'deadline'" class="reminder-bar">
          <i class="pi pi-bell"></i>
          <select
            :value="getPref(type, 'ticket').reminder_hours"
            @change="setReminder(type, +($event.target as HTMLSelectElement).value)"
          >
            <option :value="6">6 jam sebelum</option>
            <option :value="12">12 jam sebelum</option>
            <option :value="24">24 jam sebelum</option>
            <option :value="48">2 hari sebelum</option>
            <option :value="72">3 hari sebelum</option>
          </select>
        </div>
      </section>
    </div>
  </template>
</template>

<style scoped>
/* Grid layout — 1 col mobile, 2 col tablet+ */
.notif-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  margin-top: 16px;
}
@media (min-width: 480px) {
  .notif-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (min-width: 768px) {
  .notif-grid { grid-template-columns: repeat(3, 1fr); }
}

/* Card */
.notif-card {
  padding: 14px;
  border-radius: 12px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.card-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.04);
  font-size: 0.9rem;
  flex-shrink: 0;
}
.card-title {
  flex: 1;
  min-width: 0;
}
.card-title strong {
  font-size: 0.85rem;
  display: block;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Toggle all button */
.toggle-all {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: 1px solid #333;
  background: #111;
  color: #555;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  flex-shrink: 0;
  transition: all 0.15s;
}
.toggle-all.on {
  border-color: rgba(34, 197, 94, 0.4);
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}

/* Channel buttons */
.channel-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}
.ch-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 10px 4px;
  border-radius: 8px;
  border: 1px solid #222;
  background: #0d0d0d;
  color: #444;
  cursor: pointer;
  transition: all 0.15s;
  font-size: 0.7rem;
}
.ch-btn i { font-size: 0.9rem; }
.ch-btn:hover { border-color: #444; }
.ch-btn.active {
  border-color: rgba(34, 197, 94, 0.35);
  background: rgba(34, 197, 94, 0.06);
  color: #22c55e;
}
.ch-btn.active i { color: #22c55e; }

/* Reminder bar */
.reminder-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}
.reminder-bar i { color: #f59e0b; font-size: 0.8rem; }
.reminder-bar select {
  flex: 1;
  background: #111;
  color: #aaa;
  border: 1px solid #2a2a2a;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 0.75rem;
  outline: none;
}

/* Skeleton */
.skel-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  margin-top: 16px;
}
@media (min-width: 480px) {
  .skel-grid { grid-template-columns: repeat(2, 1fr); }
}
.skel-card {
  height: 120px;
  background: #111;
  border-radius: 12px;
  animation: pulse 1.5s infinite;
}
@keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 0.6; } }

/* Messages */
.msg {
  margin-top: 14px;
  padding: 11px 14px;
  border-radius: 10px;
  font-size: 0.82rem;
  display: flex;
  align-items: center;
  gap: 8px;
}
.msg-error { background: rgba(239, 68, 68, 0.08); color: #ef4444; }
.msg-ok { background: rgba(34, 197, 94, 0.08); color: #22c55e; }

.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
