<script setup lang="ts">
import { onMounted, ref } from "vue";
import Button from "primevue/button";
import Tag from "primevue/tag";
import { api, type ScoutTitle } from "../api";

const rows = ref<ScoutTitle[]>([]);
const selected = ref<ScoutTitle | null>(null);
const title = ref("");
const rawSource = ref("all");
const status = ref("");
const search = ref("");
const page = ref(1);
const pages = ref(1);
const total = ref(0);
const loading = ref(false);
const scanning = ref(false);
const error = ref("");
const success = ref("");

const labels: Record<string, string> = {
  untranslated: "Belum ditemukan",
  lagging: "Tertinggal",
  available: "Sudah tersedia",
  ambiguous: "Perlu dicek",
  ryukomik_project: "Project Ryukomik",
  candidate: "Kandidat",
  adopted: "Diambil",
  ignored: "Diabaikan",
};
const severity = (value: string) =>
  value === "untranslated" ? "success" : value === "lagging" ? "warn" :
  value === "ambiguous" ? "info" : value === "ignored" ? "danger" : "secondary";
const chapter = (value: number | null) => value == null ? "—" : Number.isInteger(value) ? String(value) : String(value);

async function load() {
  loading.value = true; error.value = "";
  try {
    const result = await api.scoutTitles(status.value, search.value, page.value, 20);
    rows.value = result.items; pages.value = result.total_pages; total.value = result.total;
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Project Scout gagal dimuat.";
  } finally { loading.value = false; }
}

async function scan(force = false) {
  if (title.value.trim().length < 2) return;
  scanning.value = true; error.value = ""; success.value = "";
  try {
    const result = await api.scoutSearch(title.value.trim(), rawSource.value, force);
    selected.value = result;
    success.value = result.cached
      ? "Hasil cache ditampilkan. Gunakan pindai ulang untuk data terbaru."
      : "Perbandingan seluruh sumber selesai dan kandidat disimpan.";
    page.value = 1; await load();
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : "Pemindaian gagal.";
  } finally { scanning.value = false; }
}

async function openDetail(id: number) {
  loading.value = true; error.value = "";
  try { selected.value = await api.scoutDetail(id); }
  catch (reason) { error.value = reason instanceof Error ? reason.message : "Detail gagal dimuat."; }
  finally { loading.value = false; }
}

async function decide(action: string) {
  if (!selected.value) return;
  let notes = "";
  if (action === "ignore") {
    notes = window.prompt("Alasan mengabaikan kandidat:", "Tidak sesuai target Ryukomik")?.trim() || "";
    if (!notes) return;
  }
  loading.value = true; error.value = "";
  try {
    selected.value = await api.scoutDecision(selected.value.id, action, notes);
    success.value = "Keputusan Project Scout disimpan."; await load();
  } catch (reason) { error.value = reason instanceof Error ? reason.message : "Keputusan gagal disimpan."; }
  finally { loading.value = false; }
}

async function changePage(direction: number) {
  page.value = Math.min(pages.value, Math.max(1, page.value + direction)); await load();
}

onMounted(load);
</script>

<template>
  <section class="scout-hero">
    <div>
      <p class="eyebrow">PROJECT DISCOVERY</p>
      <h3>Temukan project yang belum tersedia di Indonesia</h3>
      <p>Bandingkan Asura, Omega, Doujiva, EvaScan, dan Thunder dengan enam katalog Indonesia serta project Ryukomik.</p>
    </div>
    <div class="scout-count"><b>{{ total }}</b><span>hasil tersimpan</span></div>
  </section>

  <div v-if="error" class="notice error">{{ error }}</div>
  <div v-if="success" class="notice success">{{ success }}</div>

  <section class="panel scout-search-panel">
    <div class="section-title"><div><span>Cek satu judul</span><small>Pencarian manual diprioritaskan dan disimpan selama 24 jam.</small></div></div>
    <div class="scout-search-form">
      <label><span>Judul RAW</span><input v-model="title" maxlength="180" placeholder="Contoh: Affair Agency" @keyup.enter="scan(false)" /></label>
      <label><span>Sumber RAW</span><select v-model="rawSource"><option value="all">Semua sumber</option><option value="asura">Asura</option><option value="omega">Omega</option><option value="doujiva">Doujiva</option><option value="evascan">EvaScan</option><option value="thunder">Thunder</option></select></label>
      <Button label="Bandingkan" icon="pi pi-search" :loading="scanning" :disabled="title.trim().length < 2" @click="scan(false)" />
    </div>
    <p class="scout-safety"><i class="pi pi-shield"></i> Pustaka Komiku, Kiryuu, Ikiru, Sekte, Doujindesu, KomikID, dan project internal diperiksa paralel dengan batas request.</p>
  </section>

  <section class="scout-toolbar">
    <input v-model="search" placeholder="Cari kandidat tersimpan..." @keyup.enter="page=1;load()" />
    <select v-model="status" @change="page=1;load()">
      <option value="">Semua status</option><option value="untranslated">Belum ditemukan</option>
      <option value="lagging">Tertinggal</option><option value="ambiguous">Perlu dicek</option>
      <option value="available">Sudah tersedia</option><option value="ryukomik_project">Project Ryukomik</option>
      <option value="candidate">Kandidat</option><option value="adopted">Diambil</option><option value="ignored">Diabaikan</option>
    </select>
    <Button label="Tampilkan" icon="pi pi-filter" severity="secondary" @click="page=1;load()" />
  </section>

  <section class="scout-grid" :class="{ muted: loading }">
    <article v-for="item in rows" :key="item.id" class="scout-card" @click="openDetail(item.id)">
      <img v-if="item.cover_url" :src="item.cover_url" :alt="item.canonical_title" loading="lazy" referrerpolicy="no-referrer" />
      <div v-else class="scout-cover"><i class="pi pi-book"></i></div>
      <div class="scout-card-body">
        <div class="scout-card-head"><Tag :value="labels[item.scout_status] || item.scout_status" :severity="severity(item.scout_status)" /><small>{{ item.confidence }}% match</small></div>
        <h4>{{ item.canonical_title }}</h4>
        <div class="scout-chapters"><span><small>RAW</small><b>Ch. {{ chapter(item.raw_latest_chapter) }}</b></span><span><small>Indonesia</small><b>Ch. {{ chapter(item.indonesia_latest_chapter) }}</b></span><span><small>Selisih</small><b>{{ item.chapter_gap ?? "—" }}</b></span></div>
        <Button label="Lihat perbandingan" icon="pi pi-arrow-right" text />
      </div>
    </article>
    <div v-if="!loading && !rows.length" class="empty">Belum ada kandidat. Masukkan satu judul RAW untuk memulai.</div>
  </section>

  <div v-if="pages > 1" class="server-pager"><Button icon="pi pi-chevron-left" severity="secondary" :disabled="page<=1" @click="changePage(-1)"/><span>Halaman {{ page }} / {{ pages }}</span><Button icon="pi pi-chevron-right" severity="secondary" :disabled="page>=pages" @click="changePage(1)"/></div>

  <div v-if="selected" class="modal-backdrop" @click.self="selected=null">
    <section class="modal-card scout-detail">
      <div class="modal-head"><div><p class="eyebrow">PROJECT SCOUT</p><h3>{{ selected.canonical_title }}</h3></div><button type="button" @click="selected=null">×</button></div>
      <div class="scout-detail-summary">
        <img v-if="selected.cover_url" :src="selected.cover_url" :alt="selected.canonical_title" referrerpolicy="no-referrer" />
        <div><Tag :value="labels[selected.scout_status] || selected.scout_status" :severity="severity(selected.scout_status)"/><p>{{ selected.synopsis || "Sinopsis belum tersedia dari sumber." }}</p><div class="scout-chip-row"><span>RAW Ch. {{ chapter(selected.raw_latest_chapter) }}</span><span>Indonesia Ch. {{ chapter(selected.indonesia_latest_chapter) }}</span><span>Confidence {{ selected.confidence }}%</span></div></div>
      </div>
      <div class="scout-source-list">
        <article v-for="source in selected.sources" :key="`${source.source_group}-${source.source}-${source.source_id}`">
          <div><small>{{ source.source_group }}</small><b>{{ source.source }}</b></div>
          <div class="scout-source-title"><b>{{ source.title }}</b><small>Chapter {{ chapter(source.latest_chapter) }} • Match {{ source.match_score }}%</small></div>
          <a v-if="source.detail_url" :href="source.detail_url" target="_blank" rel="noopener">Buka <i class="pi pi-external-link"></i></a>
        </article>
      </div>
      <div class="modal-actions scout-actions"><Button label="Simpan Kandidat" icon="pi pi-bookmark" severity="secondary" @click="decide('candidate')"/><Button label="Sudah Tersedia" icon="pi pi-check" severity="secondary" @click="decide('available')"/><Button label="Abaikan" icon="pi pi-times" severity="danger" @click="decide('ignore')"/><Button label="Ambil Project" icon="pi pi-plus" @click="decide('adopt')"/></div>
    </section>
  </div>
</template>

<style scoped>
.scout-hero{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:27px;border:1px solid #7180ff35;border-radius:20px;background:linear-gradient(130deg,#161e38,#111722 62%,#13251f)}.scout-hero h3{margin:5px 0 8px;font:800 25px Manrope}.scout-hero p{margin-bottom:0;color:var(--muted);line-height:1.55}.scout-count{min-width:125px;text-align:center}.scout-count b,.scout-count span{display:block}.scout-count b{font:800 32px Manrope;color:#73e4bc}.scout-count span{font-size:11px;color:var(--muted)}.scout-search-panel{margin:17px 0}.scout-search-form{display:grid;grid-template-columns:minmax(0,2fr) minmax(180px,.7fr) auto;gap:10px;align-items:end}.scout-search-form label{display:grid;gap:6px}.scout-search-form label span{font-size:11px;color:var(--muted)}.scout-search-form input,.scout-search-form select,.scout-toolbar input,.scout-toolbar select{width:100%;min-width:0;padding:12px;border:1px solid var(--line);border-radius:11px;background:#0b1018;color:var(--text)}.scout-safety{margin:13px 0 0;color:#8290ab;font-size:12px}.scout-safety i{margin-right:6px;color:#55d9a8}.scout-toolbar{display:grid;grid-template-columns:minmax(0,1fr) 220px auto;gap:9px;margin-bottom:14px}.scout-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px;transition:opacity .2s}.scout-grid.muted{opacity:.55}.scout-grid>.empty{grid-column:1/-1}.scout-card{min-width:0;display:grid;grid-template-columns:112px minmax(0,1fr);overflow:hidden;border:1px solid var(--line);border-radius:17px;background:linear-gradient(145deg,#141a25,#10141d);cursor:pointer}.scout-card>img,.scout-cover{width:112px;height:100%;min-height:190px;object-fit:cover;background:#0b1018}.scout-cover{display:grid;place-items:center;color:#57627a;font-size:28px}.scout-card-body{min-width:0;padding:15px}.scout-card-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.scout-card-head small{color:var(--muted);white-space:nowrap}.scout-card h4{margin:13px 0;font:700 17px/1.35 Manrope;overflow-wrap:anywhere}.scout-chapters{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}.scout-chapters span{min-width:0;padding:8px;border:1px solid var(--line);border-radius:9px;background:#0c111a}.scout-chapters small,.scout-chapters b{display:block}.scout-chapters small{color:var(--muted);font-size:9px}.scout-chapters b{margin-top:3px;font-size:11px}.scout-card .p-button{margin-top:8px;padding-left:0}.scout-detail{width:min(880px,100%)}.scout-detail-summary{display:grid;grid-template-columns:130px 1fr;gap:18px}.scout-detail-summary>img{width:130px;height:180px;border-radius:13px;object-fit:cover}.scout-detail-summary p{color:var(--muted);line-height:1.6}.scout-chip-row{display:flex;flex-wrap:wrap;gap:7px}.scout-chip-row span{padding:7px 9px;border:1px solid var(--line);border-radius:9px;font-size:11px}.scout-source-list{display:grid;gap:8px;margin:18px 0}.scout-source-list article{display:grid;grid-template-columns:105px minmax(0,1fr) auto;align-items:center;gap:12px;padding:12px;border:1px solid var(--line);border-radius:11px;background:#0c111a}.scout-source-list small,.scout-source-list b{display:block}.scout-source-list small{color:var(--muted);font-size:10px}.scout-source-list>article>div:first-child b{text-transform:capitalize}.scout-source-title{min-width:0}.scout-source-title b{overflow-wrap:anywhere}.scout-source-list a{color:#8fa0ff;text-decoration:none;font-size:12px}.scout-actions{display:grid;grid-template-columns:repeat(4,1fr)}
@media(max-width:760px){.scout-hero{align-items:flex-start;padding:20px}.scout-count{min-width:80px}.scout-search-form,.scout-toolbar{grid-template-columns:1fr}.scout-search-form .p-button,.scout-toolbar .p-button{width:100%}.scout-grid{grid-template-columns:1fr}.scout-actions{grid-template-columns:1fr 1fr}}
@media(max-width:430px){.scout-hero{flex-direction:column;padding:17px}.scout-hero h3{font-size:21px}.scout-count{display:flex;align-items:baseline;gap:7px;text-align:left}.scout-count b{font-size:25px}.scout-search-panel{padding:15px}.scout-card{grid-template-columns:88px minmax(0,1fr)}.scout-card>img,.scout-cover{width:88px;min-height:180px}.scout-card-body{padding:12px}.scout-chapters{grid-template-columns:1fr 1fr}.scout-chapters span:last-child{grid-column:1/-1}.scout-detail-summary{grid-template-columns:82px minmax(0,1fr);gap:12px}.scout-detail-summary>img{width:82px;height:115px}.scout-detail-summary p{font-size:12px}.scout-source-list article{grid-template-columns:70px minmax(0,1fr)}.scout-source-list a{grid-column:1/-1}.scout-actions{grid-template-columns:1fr}}
</style>
