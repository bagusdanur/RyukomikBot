<script setup lang="ts">
import Button from "primevue/button";
import Tag from "primevue/tag";
import type { ActionItem } from "../api";

defineProps<{ items: ActionItem[]; loading: boolean }>();
const emit = defineEmits<{
  reload: [];
  handle: [item: ActionItem];
}>();
const label: Record<string, string> = {
  review: "Review hasil", overdue: "Terlambat", deadline: "Deadline dekat",
  transfer: "Transfer gaji", payment_method: "Menunggu rekening",
  invoice_delivery: "Kirim ulang invoice",
};
</script>

<template>
  <div class="toolbar">
    <div><p class="eyebrow">ANTREAN ADMINISTRATOR</p><h3>Perlu Tindakan</h3>
      <small>Diurutkan berdasarkan urgensi agar pekerjaan penting tidak terlewat.</small></div>
    <Button label="Muat ulang" icon="pi pi-refresh" severity="secondary" @click="emit('reload')" />
  </div>
  <div v-if="loading" class="operations-skeleton"><span v-for="n in 4" :key="n"></span></div>
  <div v-else-if="!items.length" class="empty-state">
    <i class="pi pi-check-circle"></i><h3>Semua pekerjaan sudah tertangani</h3>
    <p>Tidak ada review, deadline, pembayaran, atau invoice gagal yang menunggu.</p>
  </div>
  <div v-else class="action-list">
    <article v-for="item in items" :key="`${item.item_type}-${item.id}`" class="panel">
      <div><Tag :severity="item.priority === 1 ? 'danger' : item.priority === 2 ? 'warn' : 'secondary'"
        :value="label[item.action_type] || item.action_type" />
        <h3>{{ item.title }}</h3><p>{{ item.staff_name }}<span v-if="item.due_at"> • {{ item.due_at }}</span></p></div>
      <Button label="Tangani" icon="pi pi-arrow-right" @click="emit('handle', item)" />
    </article>
  </div>
</template>
