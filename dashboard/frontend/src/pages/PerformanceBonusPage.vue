<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, type PerformanceBonus, type PerformanceBonusSettings, type ManualBonus, type Staff } from "../api";

const period = ref(new Date(new Date().getFullYear(), new Date().getMonth() - 1, 1).toISOString().slice(0, 7));
const status = ref("");
const loading = ref(false), saving = ref(false), error = ref(""), success = ref("");
const items = ref<PerformanceBonus[]>([]);
const detail = ref<PerformanceBonus | null>(null);
const rejectTarget = ref<PerformanceBonus | null>(null), rejectionReason = ref("");
const settingsOpen = ref(false);
const settings = ref<PerformanceBonusSettings>({
  quality_weight: 50, speed_weight: 30, consistency_weight: 20, min_chapters: 3,
  tier_1_score: 70, tier_1_percent: 4, tier_2_score: 80, tier_2_percent: 6,
  tier_3_score: 90, tier_3_percent: 10, max_amount: 25000,
});

// Manual Bonus state
const manualBonuses = ref<ManualBonus[]>([]);
const manualBonusOpen = ref(false);
const staffList = ref<Staff[]>([]);
const newManual = ref({
  staff_id: "",
  amount: 15000,
  reason: "",
  period: period.value,
});

const money = (value: number) => new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(value || 0);
const pending = computed(() => items.value.filter((item) => item.status === "pending").length);
const proposed = computed(() => items.value.filter((item) => item.status === "pending").reduce((sum, item) => sum + item.proposed_amount, 0));
const filtered = computed(() => status.value ? items.value.filter((item) => item.status === status.value) : items.value);
const label: Record<string, string> = { pending: "Perlu review", approved: "Disetujui", rejected: "Ditolak", ineligible: "Belum memenuhi", invoiced: "Masuk invoice", paid: "Dibayar" };

async function load() {
  loading.value = true; error.value = "";
  try {
    const [bonuses, setts, manualList, staffData] = await Promise.all([
      api.performanceBonuses(period.value),
      api.performanceBonusSettings(),
      api.manualBonuses("", period.value),
      api.staff(),
    ]);
    items.value = bonuses;
    settings.value = setts;
    manualBonuses.value = manualList;
    staffList.value = staffData;
  }
  catch (e) { error.value = e instanceof Error ? e.message : "Gagal memuat bonus."; }
  finally { loading.value = false; }
}

async function run() {
  saving.value = true; error.value = "";
  try { const result = await api.runPerformanceBonuses(period.value); success.value = `${result.count} hasil evaluasi diperbarui.`; await load(); }
  catch (e) { error.value = e instanceof Error ? e.message : "Evaluasi gagal."; }
  finally { saving.value = false; }
}

async function approve(item: PerformanceBonus) {
  saving.value = true;
  try { await api.approvePerformanceBonus(item.id); success.value = `Bonus ${item.staff_name || "staff Discord"} disetujui dan akan masuk invoice berikutnya.`; detail.value = null; await load(); }
  catch (e) { error.value = e instanceof Error ? e.message : "Persetujuan gagal."; }
  finally { saving.value = false; }
}

async function reject() {
  if (!rejectTarget.value || rejectionReason.value.trim().length < 3) { error.value = "Alasan penolakan minimal 3 karakter."; return; }
  saving.value = true;
  try { await api.rejectPerformanceBonus(rejectTarget.value.id, rejectionReason.value); rejectTarget.value = null; rejectionReason.value = ""; success.value = "Bonus ditolak dan tidak masuk saldo."; await load(); }
  catch (e) { error.value = e instanceof Error ? e.message : "Penolakan gagal."; }
  finally { saving.value = false; }
}

async function saveSettings() {
  saving.value = true;
  try { settings.value = await api.updatePerformanceBonusSettings(settings.value); settingsOpen.value = false; success.value = "Aturan bonus berhasil disimpan."; }
  catch (e) { error.value = e instanceof Error ? e.message : "Pengaturan tidak dapat disimpan."; }
  finally { saving.value = false; }
}

async function createManual() {
  if (!newManual.value.staff_id) { error.value = "Pilih staff penerima bonus."; return; }
  if (!newManual.value.reason.trim()) { error.value = "Alasan bonus wajib diisi."; return; }
  if (newManual.value.amount <= 0) { error.value = "Jumlah bonus harus lebih dari 0."; return; }
  saving.value = true; error.value = "";
  try {
    await api.createManualBonus({
      staff_id: newManual.value.staff_id,
      amount: newManual.value.amount,
      reason: newManual.value.reason.trim(),
      period: newManual.value.period || period.value,
    });
    success.value = "Bonus manual berhasil diberikan!";
    manualBonusOpen.value = false;
    newManual.value = { staff_id: "", amount: 15000, reason: "", period: period.value };
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal memberikan bonus manual.";
  } finally {
    saving.value = false;
  }
}

async function cancelManual(id: number) {
  if (!confirm("Yakin ingin membatalkan bonus manual ini?")) return;
  saving.value = true; error.value = "";
  try {
    await api.cancelManualBonus(id);
    success.value = "Bonus manual dibatalkan.";
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal membatalkan bonus.";
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="bonus-page">
    <div v-if="error" class="bonus-alert error">{{ error }}<button @click="error=''">×</button></div>
    <div v-if="success" class="bonus-alert success">{{ success }}<button @click="success=''">×</button></div>
    <section class="bonus-hero">
      <div>
        <span class="kicker">MONTHLY REWARD</span>
        <h3>Bonus Performa Staff</h3>
        <p>Evaluasi privat berbasis kualitas, deadline, dan konsistensi. Anda juga dapat memberikan bonus manual bebas jumlah.</p>
      </div>
      <div style="display:flex;gap:10px">
        <button class="primary" @click="manualBonusOpen=true; newManual.period = period"><i class="pi pi-plus"></i> + Bonus Manual</button>
        <button class="secondary" @click="settingsOpen=true"><i class="pi pi-cog"></i> Atur skema</button>
      </div>
    </section>
    <section class="bonus-toolbar">
      <label>Periode<input v-model="period" type="month" @change="load" /></label>
      <label>Status<select v-model="status"><option value="">Semua status</option><option v-for="value in ['pending','approved','invoiced','paid','rejected','ineligible']" :key="value" :value="value">{{ label[value] }}</option></select></label>
      <button class="primary" :disabled="saving" @click="run"><i class="pi pi-sparkles"></i> Hitung ulang</button>
    </section>
    <section class="bonus-summary">
      <article><span>Perlu keputusan</span><strong>{{ pending }}</strong><small>kandidat</small></article>
      <article><span>Usulan bonus</span><strong>{{ money(proposed) }}</strong><small>menunggu persetujuan</small></article>
      <article><span>Batas per staff</span><strong>{{ money(settings.max_amount) }}</strong><small>per bulan (otomatis)</small></article>
    </section>

    <!-- Manual Bonuses Section -->
    <section class="bonus-list" v-if="manualBonuses.length">
      <div class="section-title">
        <div>
          <h4>🎁 Bonus Manual ({{ period }})</h4>
          <p>Bonus yang diberikan admin secara langsung tanpa batas tier.</p>
        </div>
        <span>{{ manualBonuses.length }} bonus</span>
      </div>
      <div v-for="mb in manualBonuses" :key="mb.id" class="manual-card">
        <div class="staff">
          <img v-if="mb.staff_avatar" class="avatar image" :src="mb.staff_avatar" alt="" />
          <div v-else class="avatar">{{ (mb.staff_name || '?').slice(0,1).toUpperCase() }}</div>
          <div>
            <strong>{{ mb.staff_name || "Staff Discord" }}</strong>
            <span>{{ mb.reason }}</span>
          </div>
        </div>
        <div>
          <b>{{ money(mb.amount) }}</b>
        </div>
        <span :class="['state', mb.status]">{{ mb.status === 'approved' ? 'Disetujui' : mb.status === 'invoiced' ? 'Masuk invoice' : mb.status === 'paid' ? 'Dibayar' : 'Dibatalkan' }}</span>
        <button v-if="mb.status === 'approved'" class="danger-btn" @click="cancelManual(mb.id)">Batal</button>
      </div>
    </section>

    <!-- Automatic Performance Bonuses Section -->
    <section class="bonus-list">
      <div class="section-title"><div><h4>Evaluasi Otomatis {{ period }}</h4><p>Klik card untuk memeriksa bukti perhitungan.</p></div><span>{{ filtered.length }} staff</span></div>
      <div v-if="loading" class="empty"><i class="pi pi-spin pi-spinner"></i> Memuat evaluasi...</div>
      <div v-else-if="!filtered.length" class="empty"><i class="pi pi-chart-line"></i><b>Belum ada hasil</b><span>Jalankan evaluasi untuk periode ini.</span></div>
      <button v-for="item in filtered" :key="item.id" class="bonus-card" @click="detail=item">
        <div class="staff"><img v-if="item.staff_avatar" class="avatar image" :src="item.staff_avatar" alt="" /><div v-else class="avatar">{{ (item.staff_name || '?').slice(0,1).toUpperCase() }}</div><div><strong>{{ item.staff_name || "Nama Discord belum tersinkron" }}</strong><span>{{ item.approved_chapters }} chapter · {{ money(item.eligible_earnings) }}</span></div></div>
        <div class="score"><strong>{{ item.total_score.toFixed(1) }}</strong><span>/100</span></div>
        <div><span class="tier">{{ item.tier || "Belum eligible" }}</span><b>{{ money(item.proposed_amount) }}</b></div>
        <span :class="['state', item.status]">{{ label[item.status] }}</span><i class="pi pi-chevron-right"></i>
      </button>
    </section>

    <!-- Modal Detail Performance Bonus -->
    <div v-if="detail" class="bonus-modal" @click.self="detail=null"><section class="bonus-sheet">
      <header><div><span class="kicker">BUKTI PERHITUNGAN</span><h3>{{ detail.staff_name || "Nama Discord belum tersinkron" }}</h3><p>Periode {{ detail.period }}</p></div><button @click="detail=null">×</button></header>
      <div class="score-ring"><strong>{{ detail.total_score.toFixed(1) }}</strong><span>Skor total</span></div>
      <div class="metric-grid"><article><span>Kualitas</span><b>{{ detail.quality_score.toFixed(1) }}</b><small>{{ detail.revision_chapters }} chapter terdampak revisi</small></article><article><span>Kecepatan</span><b>{{ detail.speed_score === null ? 'Dialihkan' : detail.speed_score.toFixed(1) }}</b><small>{{ detail.on_time_chapters }}/{{ detail.deadline_chapters }} tepat waktu</small></article><article><span>Konsistensi</span><b>{{ detail.consistency_score.toFixed(1) }}</b><small>{{ detail.overdue_chapters }} chapter terlambat</small></article></div>
      <div class="bonus-total"><span>Usulan {{ detail.percentage }}%</span><strong>{{ money(detail.proposed_amount) }}</strong><small>Dari {{ money(detail.eligible_earnings) }}, dibatasi {{ money(settings.max_amount) }}</small></div>
      <div class="evidence"><h4>Riwayat tugas</h4><article v-for="task in detail.metrics.assignments || []" :key="String(task.assignment_id)"><div><b>{{ task.manga }}</b><span>Ch {{ task.chapter }} · {{ task.role }}</span></div><span>{{ Number(task.revision_count) ? `${task.revision_count} revisi` : 'Tanpa revisi' }}</span></article></div>
      <footer v-if="detail.status==='pending'"><button class="danger" @click="rejectTarget=detail;detail=null">Tolak</button><button class="primary" :disabled="saving" @click="approve(detail)"><i class="pi pi-check"></i> Setujui Bonus</button></footer>
    </section></div>

    <!-- Modal Reject -->
    <div v-if="rejectTarget" class="bonus-modal" @click.self="rejectTarget=null"><section class="small-sheet"><h3>Tolak bonus</h3><p>Alasan tercatat di audit dan tidak ditampilkan publik.</p><textarea v-model="rejectionReason" rows="4" placeholder="Contoh: data deadline perlu diperiksa ulang"></textarea><div><button class="secondary" @click="rejectTarget=null">Batal</button><button class="danger" :disabled="saving" @click="reject">Konfirmasi Tolak</button></div></section></div>

    <!-- Modal Settings -->
    <div v-if="settingsOpen" class="bonus-modal" @click.self="settingsOpen=false"><section class="bonus-sheet settings-sheet"><header><div><span class="kicker">BONUS RULES</span><h3>Atur skema bonus</h3><p>Perubahan hanya memengaruhi evaluasi yang dihitung ulang.</p></div><button @click="settingsOpen=false">×</button></header><h4>Bobot skor (total 100%)</h4><div class="form-grid"><label>Kualitas (%)<input v-model.number="settings.quality_weight" type="number" /></label><label>Kecepatan (%)<input v-model.number="settings.speed_weight" type="number" /></label><label>Konsistensi (%)<input v-model.number="settings.consistency_weight" type="number" /></label><label>Minimal chapter<input v-model.number="settings.min_chapters" type="number" /></label></div><h4>Tier dan persentase</h4><div class="tier-settings"><label>Baik<input v-model.number="settings.tier_1_score" type="number" /><input v-model.number="settings.tier_1_percent" type="number" /><span>%</span></label><label>Sangat Baik<input v-model.number="settings.tier_2_score" type="number" /><input v-model.number="settings.tier_2_percent" type="number" /><span>%</span></label><label>Istimewa<input v-model.number="settings.tier_3_score" type="number" /><input v-model.number="settings.tier_3_percent" type="number" /><span>%</span></label></div><label class="cap">Batas bonus per staff<input v-model.number="settings.max_amount" type="number" /></label><footer><button class="secondary" @click="settingsOpen=false">Batal</button><button class="primary" :disabled="saving" @click="saveSettings">Simpan aturan</button></footer></section></div>

    <!-- Modal Create Manual Bonus -->
    <div v-if="manualBonusOpen" class="bonus-modal" @click.self="manualBonusOpen=false">
      <section class="small-sheet">
        <header style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
          <h3>🎁 Bonus Manual Staff</h3>
          <button style="border:0;background:none;color:#9dabc0;font-size:24px;cursor:pointer" @click="manualBonusOpen=false">×</button>
        </header>
        <p style="margin-bottom:14px;color:#94a2b8;font-size:13px">Beri bonus manual jumlah berapa pun ke staff untuk mengapresiasi kontribusi ekstra.</p>
        <div style="display:grid;gap:12px">
          <label>Pilih Staff
            <select v-model="newManual.staff_id">
              <option value="" disabled>-- Pilih Staff --</option>
              <option v-for="s in staffList" :key="s.staff_id" :value="s.staff_id">
                {{ s.username }} (ID: {{ s.staff_id }})
              </option>
            </select>
          </label>
          <label>Jumlah Bonus (Rp)
            <input v-model.number="newManual.amount" type="number" step="1000" placeholder="15000" />
          </label>
          <label>Alasan Bonus
            <input v-model="newManual.reason" type="text" placeholder="Contoh: Lembur deadline ketat / QC extra" />
          </label>
          <label>Periode
            <input v-model="newManual.period" type="month" />
          </label>
        </div>
        <div style="display:flex;justify-content:flex-end;gap:9px;margin-top:18px">
          <button class="secondary" @click="manualBonusOpen=false">Batal</button>
          <button class="primary" :disabled="saving" @click="createManual">Simpan Bonus</button>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.staff img.avatar{object-fit:cover;background:#20283a}
.bonus-page{display:grid;gap:18px;color:#eef2ff}.bonus-hero,.bonus-toolbar,.bonus-list,.bonus-summary article{border:1px solid #263044;background:#101722;border-radius:18px}.bonus-hero{padding:24px;display:flex;align-items:center;justify-content:space-between;gap:20px}.kicker{color:#8e9dff;font-size:11px;font-weight:800;letter-spacing:.18em}.bonus-hero h3,.bonus-sheet h3{font-size:26px;margin:7px 0}.bonus-hero p,.bonus-sheet p,.section-title p{color:#91a0b9;margin:0}.bonus-toolbar{padding:14px;display:flex;align-items:end;gap:12px}.bonus-toolbar label,.form-grid label,.cap{display:grid;gap:7px;color:#9eabc1;font-size:12px}.bonus-toolbar input,.bonus-toolbar select,input,textarea{min-height:43px;border:1px solid #303b51;border-radius:11px;background:#0b111b;color:#fff;padding:0 12px}.primary,.secondary,.danger{border:0;border-radius:11px;padding:12px 16px;font-weight:700;cursor:pointer}.primary{background:#31d3a0;color:#06150f}.secondary{background:#202838;color:#dce4f5}.danger{background:#ef5262;color:#fff}.bonus-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.bonus-summary article{padding:18px;display:grid;gap:5px}.bonus-summary span,.bonus-summary small{color:#91a0b9}.bonus-summary strong{font-size:23px}.bonus-list{padding:20px}.section-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.section-title h4,.evidence h4,.settings-sheet h4{margin:0 0 5px}.bonus-card{width:100%;display:grid;grid-template-columns:minmax(180px,1.6fr) 80px 130px 120px 20px;align-items:center;gap:16px;text-align:left;color:#eaf0ff;background:#0c131e;border:1px solid #222e42;border-radius:14px;padding:14px;margin-top:9px;cursor:pointer}.manual-card{width:100%;display:grid;grid-template-columns:minmax(180px,1.6fr) 130px 120px 80px;align-items:center;gap:16px;text-align:left;color:#eaf0ff;background:#0c131e;border:1px solid #222e42;border-radius:14px;padding:14px;margin-top:9px}.danger-btn{border:0;border-radius:8px;padding:6px 12px;font-size:12px;font-weight:700;background:#ef5262;color:#fff;cursor:pointer}.staff{display:flex;align-items:center;gap:11px}.staff .avatar{width:39px;height:39px;border-radius:12px;background:#6978ed;display:grid;place-items:center;font-weight:800}.staff div:last-child{display:grid;gap:4px}.staff span,.score span{color:#8c9ab1;font-size:12px}.score strong{font-size:22px}.bonus-card>div:nth-child(3){display:grid;gap:4px}.tier{font-size:11px;color:#8fa1ff}.state{border-radius:99px;padding:6px 9px;text-align:center;font-size:11px;font-weight:700;background:#273044}.state.pending{color:#ffc96b;background:#332817}.state.approved,.state.invoiced,.state.paid{color:#63e1ae;background:#15382e}.state.rejected,.state.cancelled{color:#ff8994;background:#3d1d25}.empty{min-height:190px;border:1px dashed #2b374c;border-radius:14px;display:grid;place-content:center;text-align:center;gap:8px;color:#8796ae}.bonus-modal{position:fixed;inset:0;background:#050810d9;z-index:1000;display:grid;place-items:center;padding:18px}.bonus-sheet,.small-sheet{width:min(720px,100%);max-height:min(90vh,850px);overflow:auto;background:#111925;border:1px solid #303c53;border-radius:20px;padding:24px}.small-sheet{width:min(440px,100%)}.bonus-sheet header{display:flex;justify-content:space-between}.bonus-sheet header>button{border:0;background:transparent;color:#9dabc0;font-size:28px}.score-ring{width:120px;height:120px;border-radius:50%;margin:20px auto;display:grid;place-content:center;text-align:center;background:radial-gradient(circle,#111925 59%,transparent 61%),conic-gradient(#48d7ad 0 82%,#293246 82%)}.score-ring strong{font-size:29px}.score-ring span{font-size:11px;color:#97a5bb}.metric-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.metric-grid article,.bonus-total{padding:15px;border-radius:13px;border:1px solid #29364a;background:#0b121d;display:grid;gap:5px}.metric-grid span,.metric-grid small,.bonus-total span,.bonus-total small{color:#91a0b8;font-size:12px}.metric-grid b{font-size:21px}.bonus-total{margin-top:10px}.bonus-total strong{font-size:25px;color:#4bdcaf}.evidence{margin-top:20px}.evidence article{display:flex;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid #253047}.evidence article div{display:grid;gap:3px}.evidence span{color:#91a0b8;font-size:12px}.bonus-sheet footer,.small-sheet>div{display:flex;justify-content:flex-end;gap:9px;margin-top:20px}.form-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.tier-settings{display:grid;gap:8px}.tier-settings label{display:grid;grid-template-columns:1fr 90px 90px 20px;align-items:center;gap:8px}.cap{margin-top:15px}.bonus-alert{padding:12px 14px;border-radius:11px;display:flex;justify-content:space-between}.bonus-alert.error{background:#3a1e28;color:#ff9ba6}.bonus-alert.success{background:#17392f;color:#79e4bc}.bonus-alert button{border:0;background:none;color:inherit}.small-sheet textarea{width:100%;box-sizing:border-box;padding:12px}.small-sheet p{color:#94a2b8}
@media(max-width:700px){.bonus-page{gap:12px}.bonus-hero{padding:18px;align-items:flex-start;flex-direction:column}.bonus-hero h3{font-size:22px}.bonus-hero p{font-size:13px}.bonus-toolbar{display:grid;grid-template-columns:1fr 1fr}.bonus-toolbar .primary{grid-column:1/-1}.bonus-summary{grid-template-columns:1fr 1fr}.bonus-summary article:last-child{grid-column:1/-1}.bonus-list{padding:14px}.bonus-card,.manual-card{grid-template-columns:1fr auto;padding:14px}.bonus-card>.staff,.manual-card>.staff{grid-column:1/-1}.bonus-card>.score{grid-column:1}.bonus-card>div:nth-child(3){grid-column:2;text-align:right}.bonus-card>.state{grid-column:1}.bonus-card>i{grid-column:2;grid-row:3}.bonus-sheet{padding:18px;border-radius:18px 18px 0 0;max-height:92vh}.bonus-modal{align-items:end;padding:0}.metric-grid{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr 1fr}.tier-settings label{grid-template-columns:1fr 60px 60px 15px}.section-title{align-items:flex-start}}
</style>
