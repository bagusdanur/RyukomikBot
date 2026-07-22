<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import Button from 'primevue/button'
import Column from 'primevue/column'
import DataTable from 'primevue/datatable'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import Tag from 'primevue/tag'
import { api, type Assignment, type User } from './api'

type Page = 'overview' | 'tasks' | 'staff' | 'payrates' | 'deadlines' | 'recap' | 'audit'
const user = ref<User | null>(null)
const authChecked = ref(false)
const loading = ref(false)
const error = ref('')
const page = ref<Page>('overview')
const overview = ref({ counts: {} as Record<string, number>, total_value: 0, urgent_deadlines: 0 })
const assignments = ref<Assignment[]>([])
const staff = ref<Array<Record<string, number>>>([])
const payrates = ref<Array<{ role: string; base_rate: number; updated_at: string }>>([])
const deadlines = ref<Assignment[]>([])
const recap = ref<Array<Record<string, number>>>([])
const audit = ref<Array<Record<string, string | number | null>>>([])
const search = ref('')
const status = ref('')
const period = ref(new Date().toISOString().slice(0, 7))

const navItems = computed(() => [
  { id: 'overview', label: 'Ringkasan', icon: 'pi pi-home' },
  { id: 'tasks', label: 'Tugas', icon: 'pi pi-list-check' },
  ...(user.value?.role === 'admin' ? [
    { id: 'staff', label: 'Staff', icon: 'pi pi-users' },
    { id: 'payrates', label: 'Payrate', icon: 'pi pi-wallet' },
    { id: 'recap', label: 'Rekap Gaji', icon: 'pi pi-receipt' },
    { id: 'audit', label: 'Audit Log', icon: 'pi pi-shield' },
  ] : []),
  { id: 'deadlines', label: 'Deadline', icon: 'pi pi-clock' },
])

const money = (value: number) => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(value || 0)
const statusLabel: Record<string, string> = { open: 'Tersedia', claimed: 'Dikerjakan', submitted: 'Menunggu Review', revision: 'Perlu Revisi', approved: 'Disetujui', paid: 'Dibayar' }
const severity = (value: string) => ({ open: 'info', claimed: 'warn', submitted: 'secondary', revision: 'danger', approved: 'success', paid: 'contrast' }[value] || 'secondary') as any

async function run<T>(operation: () => Promise<T>, target: { value: T }) {
  loading.value = true; error.value = ''
  try { target.value = await operation() } catch (e) { error.value = e instanceof Error ? e.message : 'Terjadi kesalahan.' } finally { loading.value = false }
}

async function loadPage() {
  if (!user.value) return
  if (page.value === 'overview') await run(api.overview, overview)
  if (page.value === 'tasks') await run(() => api.assignments(status.value, search.value), assignments)
  if (page.value === 'staff') await run(api.staff, staff)
  if (page.value === 'payrates') await run(api.payrates, payrates)
  if (page.value === 'deadlines') await run(api.deadlines, deadlines)
  if (page.value === 'recap') await run(() => api.recap(period.value), recap)
  if (page.value === 'audit') await run(api.audit, audit)
}

async function saveRate(item: { role: string; base_rate: number }) {
  loading.value = true; error.value = ''
  try { await api.updatePayrate(item.role, item.base_rate); await loadPage() } catch (e) { error.value = e instanceof Error ? e.message : 'Gagal menyimpan payrate.' } finally { loading.value = false }
}

async function logout() { await api.logout(); user.value = null }
watch(page, loadPage)
watch(status, () => page.value === 'tasks' && loadPage())
onMounted(async () => {
  try { user.value = await api.me(); await loadPage() } catch { user.value = null } finally { authChecked.value = true }
})
</script>

<template>
  <div v-if="!authChecked" class="center-screen"><i class="pi pi-spin pi-spinner"></i></div>
  <main v-else-if="!user" class="login-page">
    <section class="login-card">
      <div class="brand-mark">R</div>
      <p class="eyebrow">RYUKOMIK OPERATIONS</p>
      <h1>Kerja staff lebih rapi,<br><span>tanpa command rumit.</span></h1>
      <p class="login-copy">Kelola tugas, deadline, review, dan pembayaran melalui satu ruang kerja yang terhubung dengan Discord.</p>
      <a class="discord-login" href="/auth/login"><i class="pi pi-discord"></i> Masuk dengan Discord</a>
      <p class="security-note"><i class="pi pi-lock"></i> Hanya Administrator dan Staff Ryukomik</p>
    </section>
  </main>

  <div v-else class="app-shell app-dark">
    <aside class="sidebar">
      <div class="brand"><div class="brand-mark small">R</div><div><strong>Ryukomik</strong><span>Staff Operations</span></div></div>
      <nav>
        <button v-for="item in navItems" :key="item.id" :class="{ active: page === item.id }" @click="page = item.id as Page">
          <i :class="item.icon"></i><span>{{ item.label }}</span>
        </button>
      </nav>
      <div class="profile"><div class="avatar">{{ user.username.slice(0, 1).toUpperCase() }}</div><div><strong>{{ user.username }}</strong><span>{{ user.role === 'admin' ? 'Administrator' : 'Staff' }}</span></div><button title="Keluar" @click="logout"><i class="pi pi-sign-out"></i></button></div>
    </aside>

    <section class="content">
      <header><div><p class="eyebrow">STAFF MANAGEMENT</p><h2>{{ navItems.find(i => i.id === page)?.label }}</h2></div><div class="live"><span></span> Sistem aktif</div></header>
      <div v-if="error" class="error-banner"><i class="pi pi-exclamation-circle"></i>{{ error }}<button @click="error=''">×</button></div>

      <template v-if="page === 'overview'">
        <div class="hero-card"><div><p>Selamat datang kembali,</p><h3>{{ user.username }}</h3><span>{{ user.role === 'admin' ? 'Pantau operasi tim dan selesaikan pekerjaan yang membutuhkan perhatian.' : 'Lihat tindakan berikutnya dan progres pekerjaanmu.' }}</span></div><i class="pi pi-sparkles"></i></div>
        <div class="stats-grid">
          <article><span class="stat-icon blue"><i class="pi pi-inbox"></i></span><div><small>Tugas tersedia</small><strong>{{ overview.counts.open || 0 }}</strong></div></article>
          <article><span class="stat-icon amber"><i class="pi pi-hourglass"></i></span><div><small>Sedang dikerjakan</small><strong>{{ overview.counts.claimed || 0 }}</strong></div></article>
          <article><span class="stat-icon violet"><i class="pi pi-eye"></i></span><div><small>Menunggu review</small><strong>{{ overview.counts.submitted || 0 }}</strong></div></article>
          <article><span class="stat-icon red"><i class="pi pi-clock"></i></span><div><small>Deadline mendesak</small><strong>{{ overview.urgent_deadlines }}</strong></div></article>
        </div>
        <div class="summary-grid"><article class="panel"><p class="eyebrow">NILAI PEKERJAAN</p><h3>{{ money(overview.total_value) }}</h3><p>Total nilai seluruh tugas yang dapat kamu akses.</p></article><article class="panel next"><p class="eyebrow">TINDAKAN BERIKUTNYA</p><h3>{{ overview.counts.revision ? 'Ada revisi yang perlu diselesaikan' : overview.counts.submitted ? 'Hasil sedang menunggu review' : 'Alur kerja dalam kondisi baik' }}</h3><Button label="Buka daftar tugas" icon="pi pi-arrow-right" icon-pos="right" @click="page='tasks'" /></article></div>
      </template>

      <template v-if="page === 'tasks'">
        <div class="toolbar"><span class="search"><i class="pi pi-search"></i><InputText v-model="search" placeholder="Cari manga atau chapter" @keyup.enter="loadPage" /></span><Select v-model="status" :options="['','open','claimed','submitted','revision','approved','paid']" placeholder="Semua status" /><Button label="Cari" icon="pi pi-search" @click="loadPage" /></div>
        <div class="table-card"><DataTable :value="assignments" :loading="loading" paginator :rows="12" stripedRows responsiveLayout="scroll"><Column field="id" header="#" sortable /><Column field="manga" header="Manga" sortable /><Column field="chapter" header="Chapter" /><Column field="role" header="Role" /><Column header="Status"><template #body="{data}"><Tag :value="statusLabel[data.status] || data.status" :severity="severity(data.status)" /></template></Column><Column header="Bayaran"><template #body="{data}">{{ money(data.final_rate) }}</template></Column><Column field="deadline_at" header="Deadline"><template #body="{data}">{{ data.deadline_at || '—' }}</template></Column></DataTable></div>
      </template>

      <template v-if="page === 'staff'"><div class="table-card"><DataTable :value="staff" :loading="loading" paginator :rows="12"><Column field="staff_id" header="Discord Staff ID" /><Column field="task_count" header="Total Tugas" sortable /><Column field="active_count" header="Aktif" sortable /><Column header="Approved"><template #body="{data}">{{ money(data.approved_amount) }}</template></Column><Column header="Dibayar"><template #body="{data}">{{ money(data.paid_amount) }}</template></Column></DataTable></div></template>

      <template v-if="page === 'payrates'"><div class="payrate-grid"><article v-for="item in payrates" :key="item.role" class="panel rate-card"><span>{{ item.role }}</span><h3>{{ item.role === 'TL' ? 'Translator' : item.role === 'TS' ? 'Typesetter' : 'Translator + Typesetter' }}</h3><InputNumber v-model="item.base_rate" mode="currency" currency="IDR" locale="id-ID" :min="0" /><Button label="Simpan rate" icon="pi pi-check" :loading="loading" @click="saveRate(item)" /><small>Hanya berlaku untuk tugas baru.</small></article></div></template>

      <template v-if="page === 'deadlines'"><div class="table-card"><DataTable :value="deadlines" :loading="loading"><Column field="deadline_at" header="Deadline" sortable /><Column field="manga" header="Manga" /><Column field="chapter" header="Chapter" /><Column field="staff_id" header="Staff ID" /><Column header="Status"><template #body="{data}"><Tag :value="statusLabel[data.status]" :severity="severity(data.status)" /></template></Column></DataTable></div></template>

      <template v-if="page === 'recap'"><div class="toolbar"><label>Periode <input v-model="period" type="month" /></label><Button label="Tampilkan" icon="pi pi-filter" @click="loadPage" /></div><div class="table-card"><DataTable :value="recap" :loading="loading"><Column field="staff_id" header="Staff ID" /><Column field="chapter_count" header="Chapter" /><Column header="Total"><template #body="{data}"><strong>{{ money(data.total_amount) }}</strong></template></Column></DataTable></div></template>

      <template v-if="page === 'audit'"><div class="table-card"><DataTable :value="audit" :loading="loading" paginator :rows="15"><Column field="created_at" header="Waktu" /><Column field="actor_id" header="Pelaku" /><Column field="action" header="Aksi" /><Column field="target_type" header="Target" /><Column field="target_id" header="ID" /></DataTable></div></template>
    </section>
  </div>
</template>
