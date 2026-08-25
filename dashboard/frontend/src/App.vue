<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref, watch } from "vue";
import Button from "primevue/button";
import Column from "primevue/column";
import DataTable from "primevue/datatable";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
import Tag from "primevue/tag";
import {
  api,
  type ActionItem,
  type Assignment,
  type Invoice,
  type Payout,
  type PayoutDetail,
  type PairProject,
  type ProjectProgress,
  type RecruitmentSettings,
  type RecruitmentSubmission,
  type Recap,
  type RecapSummary,
  type RawRateAnalysis,
  type RawSearchResult,
  type Staff,
  type StaffQuestion,
  type Submission,
  type User,
} from "./api";

type Page =
  "overview" | "actions" | "projects" | "tasks" | "qc" | "staff" | "payrates" | "recruitment" | "scout" | "deadlines" | "recap" | "payouts" | "bonuses" | "operations" | "audit" | "converter" | "ocr" | "notifications" | "workload";
const ProjectsPage = defineAsyncComponent(() => import("./pages/ProjectsPage.vue"));
const OperationsPage = defineAsyncComponent(() => import("./pages/OperationsPage.vue"));
const ActionCenterPage = defineAsyncComponent(() => import("./pages/ActionCenterPage.vue"));
const ScoutPage = defineAsyncComponent(() => import("./pages/ScoutPage.vue"));
const PerformanceBonusPage = defineAsyncComponent(() => import("./pages/PerformanceBonusPage.vue"));
const ConverterPage = defineAsyncComponent(() => import("./pages/ConverterPage.vue"));
const OcrPage = defineAsyncComponent(() => import("./pages/OcrPage.vue"));
const NotificationPrefsPage = defineAsyncComponent(() => import("./pages/NotificationPrefsPage.vue"));
const WorkloadPage = defineAsyncComponent(() => import("./pages/WorkloadPage.vue"));
const QcViewerPage = defineAsyncComponent(() => import("./pages/QcViewerPage.vue"));
const QcStudioPage = defineAsyncComponent(() => import("./pages/QcStudioPage.vue"));
const user = ref<User | null>(null),
  authChecked = ref(false),
  loading = ref(false),
  error = ref(""),
  success = ref(""),
  activeQcTaskId = ref<number | null>(null),
  page = ref<Page>("overview");
const overview = ref({
    counts: {} as Record<string, number>,
    total_value: 0,
    urgent_deadlines: 0,
    project_progress: [] as ProjectProgress[],
  }),
  assignments = ref<Assignment[]>([]),
  pairProjects = ref<PairProject[]>([]),
  staff = ref<Staff[]>([]);
const payrates = ref<
    Array<{ role: string; base_rate: number; min_rate: number; max_rate: number; updated_at: string }>
  >([]),
  deadlines = ref<Assignment[]>([]),
  recap = ref<Recap[]>([]),
  recapSummary = ref<RecapSummary>({ total_earned: 0, unpaid_amount: 0, paid_amount: 0, chapter_count: 0 }),
  invoices = ref<Invoice[]>([]),
  payouts = ref<Payout[]>([]),
  payoutDetail = ref<PayoutDetail | null>(null),
  paymentConfirmation = ref<PayoutDetail | null>(null),
  payoutStatus = ref(""),
  audit = ref<Array<Record<string, string | number | null>>>([]);
const actionItems = ref<ActionItem[]>([]);
const mobileMenuOpen = ref(false);
const installPrompt = ref<any>(null);
const recruitment = ref<RecruitmentSettings>({ open: true, positions: [] });
const recruitmentSubmissions = ref<RecruitmentSubmission[]>([]);
const staffQuestions = ref<StaffQuestion[]>([]);
const staffQuestionForm = ref({ title:"", message:"", requires_answer:true });
const taskPage = ref(1), taskPages = ref(1), taskTotal = ref(0),
  payoutPage = ref(1), payoutPages = ref(1), payoutTotal = ref(0),
  auditPage = ref(1), auditPages = ref(1), auditTotal = ref(0);
const search = ref(""),
  status = ref(""),
  staffFilter = ref(""),
  groupBy = ref("none"),
  period = ref(new Date().toISOString().slice(0, 7)),
  showTask = ref(false),
  editingTask = ref<Assignment | null>(null);
const closeRegistrationTarget = ref<RecruitmentSubmission | null>(null);
const closeRegistrationReason = ref("Batal mendaftar");
const recruitmentAnnouncement = ref("");
const task = ref({
  manga: "",
  chapter: "",
  staff_id: "",
  role: "TL",
  final_rate: 4000,
  ts_staff_id: "",
  ts_rate: 5000,
  deadline_at: "",
  raw_mode: "editor_safe",
  raw_source: "",
  raw_id: "",
  raw_pack_mode: "normal",
});
const mangaSearchSource = ref("all");
const mangaSearchResults = ref<RawSearchResult[]>([]);
const mangaSearching = ref(false);
const mangaDropdownOpen = ref(false);
let mangaSearchTimer: ReturnType<typeof setTimeout> | null = null;

function onMangaSearchInput() {
  mangaDropdownOpen.value = true;
  if (mangaSearchTimer) clearTimeout(mangaSearchTimer);
  const q = task.value.manga.trim();
  if (q.length < 2) {
    mangaSearchResults.value = [];
    mangaSearching.value = false;
    return;
  }
  mangaSearching.value = true;
  mangaSearchTimer = setTimeout(async () => {
    try {
      mangaSearchResults.value = await api.rawSearch(q, mangaSearchSource.value);
    } catch {
      mangaSearchResults.value = [];
    } finally {
      mangaSearching.value = false;
    }
  }, 300);
}

function selectMangaResult(item: RawSearchResult) {
  task.value.manga = item.title;
  task.value.raw_source = item.source;
  task.value.raw_id = item.id;
  mangaDropdownOpen.value = false;
  if (task.value.chapter.trim()) {
    analyzeRawRate();
  }
}

function clearSelectedSource() {
  task.value.raw_source = "";
  task.value.raw_id = "";
}

const rawRateAnalysis = ref<RawRateAnalysis | null>(null);
const rawRateAnalyzing = ref(false);
const submissions = ref<Submission[]>([]);
// Compatibility state for an old cached modal. No new dashboard uploads are accepted.
const uploadTask = ref<Assignment | null>(null),
  selectedImages = ref<File[]>([]),
  uploadProgress = ref(0),
  uploadStage = ref("");

const navItems = computed(() => [
  { id: "overview", label: "Ringkasan", icon: "pi pi-home" },
  { id: "projects", label: "Daftar Project", icon: "pi pi-book" },
  ...(user.value?.role === "admin"
    ? [{ id: "actions", label: "Perlu Tindakan", icon: "pi pi-bell" }]
    : []),
  { id: "tasks", label: "Tugas", icon: "pi pi-list-check" },
  ...(user.value?.role === "admin"
    ? [{ id: "qc", label: "Studio QC", icon: "pi pi-search" }]
    : []),
  ...(user.value?.role === "admin"
    ? [
        { id: "staff", label: "Tim Staff", icon: "pi pi-users" },
        { id: "payrates", label: "Payrate", icon: "pi pi-wallet" },
        { id: "recruitment", label: "Rekrutmen", icon: "pi pi-user-plus" },
        { id: "scout", label: "Project Scout", icon: "pi pi-compass" },
        { id: "recap", label: "Gaji & Invoice", icon: "pi pi-receipt" },
        { id: "payouts", label: "Permintaan Gaji", icon: "pi pi-money-bill" },
        { id: "bonuses", label: "Bonus Performa", icon: "pi pi-star" },
        { id: "operations", label: "Operasional", icon: "pi pi-heart-fill" },
        { id: "workload", label: "Workload", icon: "pi pi-chart-bar" },
        { id: "converter", label: "Converter", icon: "pi pi-image" },
        { id: "ocr", label: "OCR Extractor", icon: "pi pi-language" },
        { id: "audit", label: "Audit Log", icon: "pi pi-shield" },
      ]
    : []),
  { id: "deadlines", label: "Deadline", icon: "pi pi-clock" },
  { id: "notifications", label: "Notifikasi", icon: "pi pi-bell" },
]);
const mobilePrimaryIds = computed(() =>
  user.value?.role === "admin"
    ? ["overview", "projects", "tasks", "recap"]
    : ["overview", "projects", "tasks", "deadlines"],
);
const mobilePrimaryItems = computed(() =>
  navItems.value.filter((item) => mobilePrimaryIds.value.includes(item.id)),
);
const mobileMoreItems = computed(() =>
  navItems.value.filter((item) => !mobilePrimaryIds.value.includes(item.id)),
);
function navigateMobile(target: string) {
  page.value = target as Page;
  mobileMenuOpen.value = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}
async function installDashboard() {
  if (!installPrompt.value) return;
  await installPrompt.value.prompt();
  await installPrompt.value.userChoice;
  installPrompt.value = null;
}
const money = (v: number) =>
  new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "IDR",
    maximumFractionDigits: 0,
  }).format(v || 0);
const statusLabel: Record<string, string> = {
  open: "Tersedia",
  claimed: "Dikerjakan",
  submitted: "Menunggu Review",
  revision: "Perlu Revisi",
  approved: "Disetujui",
  paid: "Dibayar",
  cancelled: "Dibatalkan",
};
const severity = (v: string) =>
  (({
    open: "info",
    claimed: "warn",
    submitted: "secondary",
    revision: "danger",
    approved: "success",
    paid: "contrast",
    cancelled: "danger",
  })[v] || "secondary") as any;
const avatar = (id: string, hash: string | null | undefined) =>
  hash ? `https://cdn.discordapp.com/avatars/${id}/${hash}.png?size=128` : "";
const initials = (name: string) => (name || "?").slice(0, 2).toUpperCase();
const filteredAssignments = computed(() =>
  assignments.value.filter(
    (a) => !staffFilter.value || String(a.staff_id) === staffFilter.value,
  ),
);
const groupedAssignments = computed(() => {
  if (groupBy.value === "none")
    return [{ label: "Semua tugas", items: filteredAssignments.value }];
  const groups = new Map<string, Assignment[]>();
  for (const item of filteredAssignments.value) {
    const key =
      groupBy.value === "staff"
        ? item.staff_name || "Belum ditentukan"
        : statusLabel[item.status] || item.status;
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  return [...groups].map(([label, items]) => ({ label, items }));
});
const recapTotal = computed(() =>
    recap.value.reduce((n, x) => n + x.total_amount, 0),
  ),
  pendingTotal = computed(() =>
    recap.value.reduce((n, x) => n + x.pending_amount, 0),
  );
const submissionByTask = computed(
  () => new Map(submissions.value.map((item) => [item.assignment_id, item])),
);
function chapterCount(value: string) {
  const raw = value.trim();
  const range = raw.match(/^(\d+)\s*-\s*(\d+)$/);
  if (range) {
    const count = Number(range[2]) - Number(range[1]) + 1;
    return count > 0 && count <= 5 ? count : 0;
  }
  const parts = raw.split(",").map((part) => part.trim()).filter(Boolean);
  return parts.length <= 5 && new Set(parts).size === parts.length ? parts.length : 0;
}
const taskChapterCount = computed(() => chapterCount(task.value.chapter));
const taskTotalRate = computed(() => task.value.final_rate * taskChapterCount.value);

async function run<T>(op: () => Promise<T>, target: { value: T }) {
  loading.value = true;
  error.value = "";
  try {
    target.value = await op();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Terjadi kesalahan.";
  } finally {
    loading.value = false;
  }
}
async function loadPage() {
  if (!user.value) return;
  if (page.value === "overview") {
    await run(api.overview, overview);
    if (user.value.role === "admin") actionItems.value = await api.actionCenter();
  }
  if (page.value === "actions") await run(api.actionCenter, actionItems);
  if (page.value === "tasks") {
    if (user.value.role === "admin" && !staff.value.length)
      staff.value = await api.staff();
    loading.value = true;
    error.value = "";
    try {
      const [result, submissionRows, pairRows] = await Promise.all([
        api.assignmentsPage(status.value, search.value, taskPage.value, 20),
        api.submissions(),
        api.pairProjects(),
      ]);
      assignments.value = result.items;
      taskPages.value = result.total_pages;
      taskTotal.value = result.total;
      submissions.value = submissionRows;
      pairProjects.value = pairRows;
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : "Tugas gagal dimuat.";
    } finally {
      loading.value = false;
    }
  }
  if (page.value === "staff") { await run(api.staff, staff); staffQuestions.value = await api.staffQuestions(); }
  if (page.value === "payrates") await run(api.payrates, payrates);
  if (page.value === "recruitment") { await run(api.recruitmentSettings, recruitment); recruitmentSubmissions.value = await api.recruitmentSubmissions(); }
  if (page.value === "deadlines") await run(api.deadlines, deadlines);
  if (page.value === "recap") {
    if (!staff.value.length) staff.value = await api.staff();
    await Promise.all([
      run(() => api.recap(period.value), recap),
      run(api.recapSummary, recapSummary),
      run(() => api.invoices(period.value), invoices),
    ]);
  }
  if (page.value === "payouts")
    try {
      loading.value = true;
      const result = await api.payoutsPage(payoutStatus.value, payoutPage.value, 20);
      payouts.value = result.items; payoutPages.value = result.total_pages; payoutTotal.value = result.total;
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : "Payout gagal dimuat.";
    } finally { loading.value = false; }
  if (page.value === "audit")
    try {
      loading.value = true;
      const result = await api.auditPage(auditPage.value, 20);
      audit.value = result.items; auditPages.value = result.total_pages; auditTotal.value = result.total;
    } catch (reason) {
      error.value = reason instanceof Error ? reason.message : "Audit gagal dimuat.";
    } finally { loading.value = false; }
}
async function changeServerPage(kind: "tasks" | "payouts" | "audit", direction: number) {
  if (kind === "tasks") taskPage.value = Math.min(taskPages.value, Math.max(1, taskPage.value + direction));
  if (kind === "payouts") payoutPage.value = Math.min(payoutPages.value, Math.max(1, payoutPage.value + direction));
  if (kind === "audit") auditPage.value = Math.min(auditPages.value, Math.max(1, auditPage.value + direction));
  await loadPage();
}
async function openPayout(item: Payout) {
  try {
    loading.value = true;
    payoutDetail.value = await api.payout(item.id);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal membuka permintaan.";
  } finally {
    loading.value = false;
  }
}
async function handleAction(item: ActionItem) {
  if (item.item_type === "payout") {
    page.value = "payouts";
    await loadPage();
    const payout = payouts.value.find((entry) => entry.id === item.id);
    if (payout) await openPayout(payout);
    return;
  }
  if (item.action_type === "review") {
    openQc(item.id);
    return;
  }
  page.value = "tasks";
  status.value = item.action_type === "review" ? "submitted" : "";
  search.value = item.title.split(" • ")[0];
  await loadPage();
}
function openQc(taskId: number) {
  activeQcTaskId.value = taskId;
  page.value = "qc";
  window.scrollTo({ top: 0, behavior: "smooth" });
}
async function handleQcApproved(taskId: number) {
  activeQcTaskId.value = null;
  success.value = `Tugas #${taskId} berhasil disetujui melalui QC Viewer.`;
  await loadPage();
}
async function handleQcRevised(taskId: number) {
  activeQcTaskId.value = null;
  success.value = `Catatan revisi untuk tugas #${taskId} telah dikirim ke tiket staff.`;
  await loadPage();
}
async function openQris(item: PayoutDetail) {
  try {
    const result = await api.payoutQris(item.id);
    window.open(result.download_url, "_blank", "noopener");
  } catch (e) {
    error.value = e instanceof Error ? e.message : "QRIS tidak dapat dibuka.";
  }
}
function openPayoutPdf(item: Payout) {
  window.open(api.payoutPdfUrl(item.id), "_blank", "noopener");
}
async function resendInvoice(item: Payout) {
  try {
    loading.value = true;
    await api.resendPayoutInvoice(item.id);
    success.value = "Invoice PDF berhasil dikirim ulang ke tiket staff.";
    payoutDetail.value = await api.payout(item.id);
    await loadPage();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Invoice gagal dikirim ulang.";
  } finally {
    loading.value = false;
  }
}
async function copyAccount(value: string | null) {
  if (!value) return;
  await window.navigator.clipboard.writeText(value);
  success.value = "Nomor tujuan berhasil disalin.";
}
async function confirmPayout(item: Payout) {
  const detail = payoutDetail.value?.id === item.id
    ? payoutDetail.value
    : await api.payout(item.id);
  paymentConfirmation.value = detail;
}
async function completePayout(item: PayoutDetail) {
  const destination = item.method.account_number || "QRIS";
  const last4 = destination === "QRIS" ? "QRIS" : destination.slice(-4);
  try {
    loading.value = true;
    await api.payPayout(item.id, item.total_amount, last4);
    paymentConfirmation.value = null;
    payoutDetail.value = null;
    success.value = "Transfer dikonfirmasi dan tugas terkait ditandai dibayar.";
    await loadPage();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Konfirmasi pembayaran gagal.";
  } finally {
    loading.value = false;
  }
}
async function rejectPayout(item: Payout) {
  const reason = prompt("Alasan penolakan pengajuan gaji:")?.trim();
  if (!reason) return;
  try {
    loading.value = true;
    await api.rejectPayout(item.id, reason);
    payoutDetail.value = null;
    success.value = "Pengajuan ditolak dan tugas kembali tersedia.";
    await loadPage();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Penolakan gagal.";
  } finally {
    loading.value = false;
  }
}
async function saveRate(item: { role: string; min_rate: number; max_rate: number }) {
  if (item.max_rate < item.min_rate) {
    error.value = "Rate maksimum harus sama atau lebih besar dari minimum.";
    return;
  }
  try {
    loading.value = true;
    const result: any = await api.updatePayrate(item.role, item.min_rate, item.max_rate);
    success.value = `Range ${item.role} tersimpan dan dikirim ke ${result.notified || 0} tiket staff.`;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal menyimpan.";
  } finally {
    loading.value = false;
  }
}

function staffDisplayName(staffId: string) {
  return staff.value.find((item) => item.id === staffId)?.username || `Staff ${staffId}`;
}

async function createStaffQuestion() {
  const payload = { ...staffQuestionForm.value, title:staffQuestionForm.value.title.trim(), message:staffQuestionForm.value.message.trim() };
  if (!payload.title || !payload.message) return (error.value = "Judul dan isi pesan wajib diisi.");
  try {
    loading.value = true;
    const result = await api.createStaffQuestion(payload);
    success.value = `Pesan terkirim ke ${result.sent} tiket staff${result.failed ? `, ${result.failed} tiket tidak ditemukan/gagal` : ""}.`;
    staffQuestionForm.value = {title:"",message:"",requires_answer:true};
    staffQuestions.value = await api.staffQuestions();
  } catch (e) { error.value = e instanceof Error ? e.message : "Pesan staff gagal dikirim."; }
  finally { loading.value = false; }
}

async function closeStaffQuestion(id:number) {
  try {
    loading.value = true; await api.closeStaffQuestion(id);
    success.value = "Pertanyaan ditutup."; staffQuestions.value = await api.staffQuestions();
  } catch (e) { error.value = e instanceof Error ? e.message : "Pertanyaan gagal ditutup."; }
  finally { loading.value = false; }
}

async function saveRecruitmentSettings() {
  const byPosition = new Map(
    recruitment.value.positions.map((item) => [item.position, item.enabled]),
  );
  const closingWithApplicants = recruitment.value.positions.some(
    (item) => !item.enabled && item.active_count > 0,
  );
  if (
    closingWithApplicants &&
    !confirm("Ada pelamar aktif pada posisi yang ditutup. Pelamar lama tetap dapat melanjutkan. Simpan perubahan?")
  ) return;
  try {
    loading.value = true;
    const result = await api.updateRecruitmentSettings({
      tl: byPosition.get("TL") ?? false,
      ts: byPosition.get("TS") ?? false,
      tl_ts: byPosition.get("TL+TS") ?? false,
    });
    success.value = result.discord_synced
      ? "Pengaturan rekrutmen tersimpan dan panel Discord diperbarui."
      : "Pengaturan tersimpan, tetapi panel Discord belum ditemukan. Peringatan masuk ke Operasional.";
    recruitment.value = await api.recruitmentSettings();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Pengaturan rekrutmen gagal disimpan.";
  } finally {
    loading.value = false;
  }
}

async function saveRecruitmentMaterials() {
  const material = recruitment.value.test_material;
  if (!material) return;
  try {
    loading.value = true;
    const result = await api.updateRecruitmentMaterials({
      test_url: material.url,
      tl_example_url: material.tl_example_url,
      ts_assets_url: material.ts_assets_url,
    });
    success.value = `Link bahan tersimpan dan ${result.cards_refreshed} tiket aktif diperbarui.`;
    recruitment.value = await api.recruitmentSettings();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Link bahan gagal disimpan.";
  } finally { loading.value = false; }
}

async function sendRecruitmentAnnouncement() {
  const message = recruitmentAnnouncement.value.trim();
  if (!message) return (error.value = "Isi pengumuman belum diisi.");
  if (!confirm("Kirim pengumuman ini ke semua tiket pelamar aktif?")) return;
  try {
    loading.value = true;
    const result = await api.sendRecruitmentAnnouncement(message);
    success.value = `Pengumuman terkirim ke ${result.sent} tiket${result.failed ? `, ${result.failed} gagal` : ""}.`;
    recruitmentAnnouncement.value = "";
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Pengumuman gagal dikirim.";
  } finally { loading.value = false; }
}

async function closeRegistration(item: RecruitmentSubmission) {
  closeRegistrationTarget.value = item; closeRegistrationReason.value = "Batal mendaftar";
}
async function confirmCloseRegistration() {
  const item = closeRegistrationTarget.value;
  if (!item) return;
  try { loading.value = true; await api.closeRecruitmentSubmission(item.id, closeRegistrationReason.value); success.value = "Pendaftaran ditutup dan channel tiket dihapus."; closeRegistrationTarget.value = null; await loadPage(); }
  catch (e) { error.value = e instanceof Error ? e.message : "Gagal menutup pendaftaran."; }
  finally { loading.value = false; }
}
async function createTask() {
  if (!editingTask.value && !task.value.staff_id) return (error.value = "Pilih staf tujuan.");
  if (!editingTask.value && task.value.role === "PAIR" && !task.value.ts_staff_id) return (error.value = "Pilih staff Typesetter.");
  if (!task.value.deadline_at) return (error.value = "Deadline wajib diisi untuk setiap tugas.");
  if (task.value.deadline_at < new Date().toISOString().slice(0, 10)) return (error.value = "Deadline tidak boleh tanggal yang sudah lewat.");
  try {
    loading.value = true;
    if (editingTask.value) {
      const result = await api.updateAssignment(editingTask.value.id, {
        manga: task.value.manga,
        chapter: task.value.chapter,
        role: task.value.role,
        rate_per_chapter: task.value.final_rate,
        deadline_at: task.value.deadline_at || null,
        raw_mode: task.value.raw_mode,
        raw_source: task.value.raw_source || null,
        raw_id: task.value.raw_id || null,
        raw_pack_mode: task.value.raw_pack_mode,
      });
      success.value = `Tugas #${editingTask.value.id} diperbarui${result.notified ? " dan staff sudah diberi notifikasi." : "."}`;
    } else if (task.value.role === "PAIR") {
      const result = await api.createTlTsPair({
        manga: task.value.manga, chapter: task.value.chapter,
        tl_staff_id: task.value.staff_id, ts_staff_id: task.value.ts_staff_id,
        tl_rate_per_chapter: task.value.final_rate, ts_rate_per_chapter: task.value.ts_rate,
        deadline_at: task.value.deadline_at || null,
        raw_mode: task.value.raw_mode,
        raw_source: task.value.raw_source || null,
        raw_id: task.value.raw_id || null,
        raw_pack_mode: task.value.raw_pack_mode,
      });
      success.value = result.notified
        ? `Pair dibuat: tugas TL #${result.tl_assignment_id} dikirim ke tiket staff. Tugas TS akan otomatis aktif setelah TL disetujui.`
        : `Pair #${result.tl_assignment_id} tersimpan, tetapi tiket staff tidak ditemukan. Periksa tiket staff sebelum melanjutkan.`;
    } else {
      const result = await api.createAssignment({ ...task.value, rate_per_chapter: task.value.final_rate, staff_id: task.value.staff_id, deadline_at: task.value.deadline_at || null });
      success.value = `Tugas #${result.id} dibuat${result.notified ? " dan staf sudah diberi notifikasi." : ", tetapi notifikasi Discord gagal."}`;
    }
    showTask.value = false;
    editingTask.value = null;
    task.value = {
      manga: "",
      chapter: "",
      staff_id: "",
      role: "TL",
      final_rate: 4000,
      ts_staff_id: "",
      ts_rate: 5000,
      deadline_at: "",
      raw_mode: "editor_safe",
      raw_source: "",
      raw_id: "",
      raw_pack_mode: "normal",
    };
    rawRateAnalysis.value = null;
    await loadPage();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal membuat tugas.";
  } finally {
    loading.value = false;
  }
}

function deadlineUrgency(deadline:string|null) {
  if (!deadline) return {label:"Tanpa deadline",severity:"secondary" as const};
  const today = new Date(); today.setHours(0,0,0,0);
  const due = new Date(`${deadline}T00:00:00`);
  const days = Math.round((due.getTime()-today.getTime())/86400000);
  if (days < 0) return {label:`Terlambat ${Math.abs(days)} hari`,severity:"danger" as const};
  if (days === 0) return {label:"Hari ini",severity:"danger" as const};
  if (days === 1) return {label:"Besok",severity:"warn" as const};
  if (days <= 3) return {label:`H-${days}`,severity:"warn" as const};
  return {label:`${days} hari lagi`,severity:"success" as const};
}
async function analyzeRawRate() {
  if (!task.value.manga.trim() || !task.value.chapter.trim()) {
    error.value = "Isi judul manga dan chapter dahulu agar RAW dapat dianalisis.";
    return;
  }
  try {
    rawRateAnalyzing.value = true;
    error.value = "";
    const sourceParam = task.value.raw_source || undefined;
    const rawIdParam = task.value.raw_id || undefined;
    if (task.value.role === "PAIR") {
      const [tl, ts] = await Promise.all([
        api.analyzeRawRate(task.value.manga, task.value.chapter, "TL", sourceParam, rawIdParam),
        api.analyzeRawRate(task.value.manga, task.value.chapter, "TS", sourceParam, rawIdParam),
      ]);
      rawRateAnalysis.value = tl;
      task.value.final_rate = tl.rate_per_chapter;
      task.value.ts_rate = ts.rate_per_chapter;
      success.value = `RAW (${tl.source.toUpperCase()}) dianalisis: ${tl.workload}. Rekomendasi TL ${money(tl.rate_per_chapter)}/chapter dan TS ${money(ts.rate_per_chapter)}/chapter sudah diterapkan.`;
      return;
    }
    const result = await api.analyzeRawRate(task.value.manga, task.value.chapter, task.value.role, sourceParam, rawIdParam);
    rawRateAnalysis.value = result;
    task.value.final_rate = result.rate_per_chapter;
    success.value = `RAW (${result.source.toUpperCase()}) dianalisis: ${result.workload}. Rekomendasi rate diterapkan dan masih dapat diubah.`;
  } catch (e) {
    rawRateAnalysis.value = null;
    error.value = e instanceof Error ? e.message : "Analisis RAW gagal.";
  } finally {
    rawRateAnalyzing.value = false;
  }
}
async function openTask(staffId?: string, prefill?: { manga?: string; chapter?: string; role?: string }) {
  editingTask.value = null;
  rawRateAnalysis.value = null;
  mangaSearchResults.value = [];
  mangaDropdownOpen.value = false;
  task.value.raw_source = "";
  task.value.raw_id = "";
  task.value.raw_pack_mode = "normal";
  error.value = "";
  if (prefill) {
    if (prefill.manga) task.value.manga = prefill.manga;
    if (prefill.chapter) task.value.chapter = prefill.chapter;
    if (prefill.role) task.value.role = prefill.role;
  }
  if (!staff.value.length) {
    loading.value = true;
    try {
      staff.value = await api.staff();
    } catch (e) {
      error.value =
        e instanceof Error ? e.message : "Gagal mengambil daftar staf.";
    } finally {
      loading.value = false;
    }
  }
  if (staffId) task.value.staff_id = staffId;
  if (!staff.value.length) {
    error.value =
      "Daftar staf kosong. Pastikan anggota memiliki role Staff atau Admin di Discord.";
    return;
  }
  showTask.value = true;
  if (prefill?.manga && prefill?.chapter) {
    analyzeRawRate();
  }
}
function handleCreateTaskFromProject(payload: { manga: string; chapter: string }) {
  openTask(undefined, { manga: payload.manga, chapter: payload.chapter });
}
function editTask(item: Assignment) {
  editingTask.value = item;
  task.value = {
    manga: item.manga,
    chapter: item.chapter,
    staff_id: item.staff_id || "",
    role: item.role,
    final_rate: item.rate_per_chapter || Math.floor(item.final_rate / (item.chapter_count || 1)),
    ts_staff_id: "",
    ts_rate: 5000,
    deadline_at: item.deadline_at || "",
    raw_mode: item.raw_mode || "editor_safe",
    raw_source: item.raw_source || "",
    raw_id: item.raw_manga_id || "",
    raw_pack_mode: item.raw_pack_mode || "normal",
  };
  rawRateAnalysis.value = null;
  showTask.value = true;
}
async function downloadResult(item: Submission) {
  try {
    const result = await api.downloadSubmission(item.id);
    window.open(result.download_url, "_blank", "noopener");
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Download gagal.";
  }
}
function selectImages() {
  selectedImages.value = [];
}
async function submitUpload() {
  error.value =
    "Upload dashboard dinonaktifkan. Submit link Google Drive melalui Discord.";
  uploadTask.value = null;
}
async function approveTask(item: Assignment) {
  if (!confirm(`Setujui ${item.manga} chapter ${item.chapter}?`)) return;
  try {
    loading.value = true;
    await api.approveAssignment(item.id);
    success.value = `Tugas #${item.id} disetujui dan staff diberi tahu di tiket.`;
    await loadPage();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Approve gagal.";
  } finally {
    loading.value = false;
  }
}
async function reviseTask(item: Assignment) {
  const notes = prompt(
    `Catatan revisi untuk ${item.manga} chapter ${item.chapter}:`,
  )?.trim();
  if (!notes) return;
  try {
    loading.value = true;
    await api.reviseAssignment(item.id, notes);
    success.value = `Revisi tugas #${item.id} dikirim ke tiket staff.`;
    await loadPage();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Revisi gagal.";
  } finally {
    loading.value = false;
  }
}
async function revokeTask(item: Assignment) {
  const reason = prompt(
    `Alasan penarikan tugas ${item.manga} chapter ${item.chapter} (opsional):`,
  )?.trim();
  if (reason === undefined) return; // user cancelled prompt
  if (!confirm(`Tarik tugas #${item.id}? Status akan berubah menjadi Dibatalkan.`)) return;
  try {
    loading.value = true;
    await api.revokeAssignment(item.id, reason || "");
    success.value = `Tugas #${item.id} berhasil ditarik.`;
    await loadPage();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal menarik tugas.";
  } finally {
    loading.value = false;
  }
}
const pairStatusLabel: Record<string, string> = {
  waiting_tl: "Menunggu TL", ready_for_ts: "Siap TS", tl_revision: "Perbaikan TL",
  ts_revision: "Perbaikan TS", both_revision: "Perbaikan TL + TS",
  final_review: "Review Final", completed: "Selesai",
};
async function approvePairChapter(project: PairProject, chapter: PairProject["chapters"][number]) {
  if (!confirm(`Setujui final ${project.manga} chapter ${chapter.chapter} dan lepaskan gaji TL + TS?`)) return;
  try {
    loading.value = true;
    await api.approvePairChapter(chapter.id);
    success.value = `Chapter ${chapter.chapter} disetujui; kedua gaji masuk saldo.`;
    await loadPage();
  } catch (e) { error.value = e instanceof Error ? e.message : "Approve pair gagal."; }
  finally { loading.value = false; }
}
async function revisePairChapter(project: PairProject, chapter: PairProject["chapters"][number], target: "tl" | "ts" | "both") {
  const label = target === "both" ? "TL dan TS" : target.toUpperCase();
  const notes = prompt(`Catatan revisi ${label} untuk ${project.manga} chapter ${chapter.chapter}:`)?.trim();
  if (!notes) return;
  try {
    loading.value = true;
    await api.revisePairChapter(chapter.id, target, notes);
    success.value = `Revisi ${label} dikirim ke staff terkait.`;
    await loadPage();
  } catch (e) { error.value = e instanceof Error ? e.message : "Revisi pair gagal."; }
  finally { loading.value = false; }
}
async function createInvoice(item: Recap) {
  try {
    loading.value = true;
    await api.createInvoice(item.staff_id, period.value);
    // An invoice is only a billing document. Take the administrator straight
    // to its actionable payout queue so the transfer destination is never
    // missed after issuing it.
    page.value = "payouts";
    payoutStatus.value = "";
    payoutPage.value = 1;
    success.value = `Invoice ${item.staff_name} diterbitkan dan masuk Permintaan Gaji. Buka Detail untuk melihat tujuan transfer.`;
    await loadPage();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal membuat invoice.";
  } finally {
    loading.value = false;
  }
}
async function payInvoice(item: Invoice) {
  page.value = "payouts";
  success.value = `Buka permintaan ${item.invoice_number}, periksa tujuan transfer, lalu gunakan konfirmasi aman.`;
  await loadPage();
}
async function deleteInvoice(item: Invoice) {
  if (
    !confirm(
      `Hapus invoice ${item.invoice_number}? Tugas tetap approved dan dapat dibuatkan invoice baru.`,
    )
  )
    return;
  try {
    loading.value = true;
    await api.deleteInvoice(item.id);
    success.value = `Invoice ${item.invoice_number} berhasil dihapus.`;
    await loadPage();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal menghapus invoice.";
  } finally {
    loading.value = false;
  }
}
async function refreshInvoice(item: Invoice) {
  if (
    !confirm(
      `Hitung ulang invoice ${item.invoice_number} dari tugas approved terbaru?`,
    )
  )
    return;
  try {
    loading.value = true;
    await api.refreshInvoice(item.id);
    success.value = "Invoice diperbarui tanpa mengganti nomor.";
    await loadPage();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Gagal memperbarui invoice.";
  } finally {
    loading.value = false;
  }
}
async function correctionInvoice(item: Invoice) {
  if (
    !confirm(
      `Buat invoice koreksi untuk tugas terlambat setelah ${item.invoice_number}?`,
    )
  )
    return;
  try {
    loading.value = true;
    await api.correctionInvoice(item.id);
    success.value = "Invoice koreksi berhasil dibuat.";
    await loadPage();
  } catch (e) {
    error.value =
      e instanceof Error ? e.message : "Gagal membuat invoice koreksi.";
  } finally {
    loading.value = false;
  }
}
const safeHtml = (value: unknown) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      })[char]!,
  );
const storedUtcDate = (value: string) => {
  let normalized = value.trim().replace(" ", "T");
  if (!normalized.includes("T")) normalized += "T00:00:00";
  if (!/(Z|[+-]\d{2}:\d{2})$/i.test(normalized)) normalized += "Z";
  return new Date(normalized);
};
const invoiceDate = (value: string | null) =>
  value
    ? storedUtcDate(value).toLocaleDateString("id-ID", {
        day: "2-digit",
        month: "long",
        year: "numeric",
        timeZone: "Asia/Jakarta",
      })
    : "—";
const invoiceDateTime = (value: string | null) =>
  value
    ? `${storedUtcDate(value).toLocaleString("id-ID", {
        day: "2-digit",
        month: "long",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
        timeZone: "Asia/Jakarta",
      })} WIB`
    : "—";
async function printInvoice(item: Invoice) {
  const w = window.open("", "_blank", "width=900,height=900");
  if (!w) return;
  w.document.write(
    '<p style="font:15px Arial;padding:32px">Menyiapkan invoice…</p>',
  );
  try {
    const detail = await api.invoice(item.id);
    const rows = detail.items
      .map(
        (task, index) =>
          `<tr><td>${index + 1}</td><td><b>${safeHtml(task.manga)}</b><small>Task #${task.assignment_id}</small></td><td>${safeHtml(task.chapter)}</td><td>${safeHtml(task.role)}</td><td>${invoiceDate(task.approved_at)}</td><td class="money">${money(task.amount)}</td></tr>`,
      )
      .join("");
    w.document.open();
    w.document.write(
      `<html><head><title>${safeHtml(detail.invoice_number)}</title><style>@page{size:A4;margin:16mm}*{box-sizing:border-box}body{font:13px Arial,sans-serif;margin:0;color:#162033}.sheet{max-width:900px;margin:auto;padding:34px}.top{display:flex;justify-content:space-between;gap:24px;border-bottom:3px solid #6574f7;padding-bottom:22px}.brand h1{margin:0;font-size:29px;letter-spacing:1px}.brand small,.muted{color:#68748a}.number{text-align:right}.number strong{display:block;font-size:15px;margin-bottom:7px}.status{display:inline-block;padding:6px 10px;border-radius:20px;background:${detail.status === "paid" ? "#daf7e9" : "#fff1cf"};color:${detail.status === "paid" ? "#087443" : "#8a5b00"};font-weight:700}.info{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:28px 0}.card{padding:17px;border:1px solid #dde2eb;border-radius:10px}.card p{margin:7px 0}.card h3{margin:0 0 10px;font-size:12px;text-transform:uppercase;color:#68748a}table{width:100%;border-collapse:collapse;margin-top:12px}th{background:#f1f3f8;text-align:left;padding:11px 9px;font-size:11px;text-transform:uppercase;color:#5d687d}td{padding:12px 9px;border-bottom:1px solid #e4e8ef;vertical-align:top}td small{display:block;color:#8892a4;margin-top:4px}.money{text-align:right;white-space:nowrap}.summary{margin:24px 0 0 auto;width:310px}.summary div{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #e3e7ee}.summary .total{font-size:19px;font-weight:800;border-bottom:3px double #6574f7}.footer{margin-top:45px;padding-top:18px;border-top:1px solid #dde2eb;display:flex;justify-content:space-between;color:#778196;font-size:11px}@media print{.sheet{padding:0}}</style></head><body><main class="sheet"><header class="top"><div class="brand"><h1>RYUKOMIK</h1><small>Staff Payment Invoice · Scanlation Operations</small></div><div class="number"><strong>${safeHtml(detail.invoice_number)}</strong><span class="status">${detail.status === "paid" ? "LUNAS" : "MENUNGGU PEMBAYARAN"}</span></div></header><section class="info"><div class="card"><h3>Penerima</h3><p><b>${safeHtml(detail.staff_name)}</b></p><p class="muted">Discord ID ${detail.staff_id}</p></div><div class="card"><h3>Informasi Periode</h3><p>Periode: <b>${safeHtml(detail.period)}</b></p><p>Rentang kerja: <b>${invoiceDate(detail.work_started_at)} – ${invoiceDate(detail.work_ended_at)}</b></p><p>Diterbitkan: ${invoiceDate(detail.issued_at)}</p><p>Dibayar: ${invoiceDateTime(detail.paid_at)}</p></div></section><h3>Rincian Pekerjaan</h3><table><thead><tr><th>No.</th><th>Judul / Task</th><th>Chapter</th><th>Role</th><th>Disetujui</th><th class="money">Bayaran</th></tr></thead><tbody>${rows || '<tr><td colspan="6">Rincian tugas tidak tersedia.</td></tr>'}</tbody></table><section class="summary"><div><span>Jumlah pekerjaan</span><b>${detail.chapter_count} chapter</b></div><div class="total"><span>Total gaji</span><span>${money(detail.total_amount)}</span></div></section><footer class="footer"><span>Dokumen dibuat otomatis oleh Ryukomik Staff Management.</span><span>${safeHtml(detail.invoice_number)}</span></footer></main><script>window.onload=()=>window.print()<\/script></body></html>`,
    );
    w.document.close();
  } catch (e) {
    w.document.body.innerHTML = `<p style="font:15px Arial;padding:32px;color:#b42318">${safeHtml(e instanceof Error ? e.message : "Gagal membuat invoice.")}</p>`;
  }
}
async function logout() {
  await api.logout();
  user.value = null;
}
async function syncStaff() {
  try {
    loading.value = true;
    error.value = "";
    const result = await api.syncStaff();
    success.value = `Sinkronisasi selesai: ${result.count} staff aktif ditemukan.`;
    await loadPage();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Sinkronisasi gagal.";
  } finally {
    loading.value = false;
  }
}
watch(page, async () => {
  const params = new URLSearchParams(location.search);
  params.set("page", page.value);
  history.replaceState(null, "", `${location.pathname}?${params}`);
  await loadPage();
});
watch(status, () => {
  const params = new URLSearchParams(location.search);
  status.value ? params.set("status", status.value) : params.delete("status");
  history.replaceState(null, "", `${location.pathname}?${params}`);
  if (page.value === "tasks") loadPage();
});
watch(
  () => task.value.role,
  (role) => {
    if (editingTask.value) return;
    const selected = payrates.value.find((item) => item.role === role);
    const fallback = role === "TS" ? 5000 : role === "TL+TS" ? 9000 : 4000;
    task.value.final_rate = selected?.min_rate ?? fallback;
  },
);
onMounted(async () => {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt.value = event;
  });
  window.addEventListener("appinstalled", () => {
    installPrompt.value = null;
  });
  try {
    user.value = await api.me();
    const params = new URLSearchParams(location.search);
    const requested = params.get("page") as Page | null;
    if (requested && navItems.value.some((item) => item.id === requested)) page.value = requested;
    status.value = params.get("status") || "";
    await loadPage();
  } catch {
    user.value = null;
  } finally {
    authChecked.value = true;
  }
});
</script>

<template>
  <div v-if="!authChecked" class="center-screen">
    <i class="pi pi-spin pi-spinner"></i>
  </div>
  <main v-else-if="!user" class="login-page">
    <section class="login-card">
      <img class="brand-mark" src="/icons/ryukomik-staff-20260804.png?v=staff-2" alt="Logo Ryukomik Staff" />
      <p class="eyebrow">RYUKOMIK STAFF</p>
      <h1>Satu ruang kerja untuk<br /><span>administrator Ryukomik.</span></h1>
      <p class="login-copy">
        Kelola tugas, review hasil, gaji, dan invoice yang terhubung langsung
        dengan Discord.
      </p>
      <a class="discord-login" href="/auth/login"
        ><i class="pi pi-discord"></i> Masuk dengan Discord</a
      >
      <p class="security-note">
        <i class="pi pi-lock"></i> Khusus Administrator Ryukomik
      </p>
    </section>
  </main>
  <div v-else class="app-shell app-dark">
    <aside class="sidebar">
      <div class="brand">
        <img class="brand-mark small" src="/icons/ryukomik-staff-20260804.png?v=staff-2" alt="Logo Ryukomik Staff" />
        <div><strong>Ryukomik</strong><span>Ryukomik Staff</span></div>
      </div>
      <nav>
        <button
          v-for="item in navItems"
          :key="item.id"
          :class="{ active: page === item.id }"
          @click="page = item.id as Page"
        >
          <i :class="item.icon"></i><span>{{ item.label }}</span>
          <b v-if="item.id === 'actions' && actionItems.length" class="nav-badge">{{ actionItems.length }}</b>
        </button>
      </nav>
      <div class="profile">
        <img
          v-if="avatar(user.id, user.avatar)"
          :src="avatar(user.id, user.avatar)"
        />
        <div v-else class="avatar">{{ initials(user.username) }}</div>
        <div>
          <strong>{{ user.username }}</strong
          ><span>{{ user.role === "admin" ? "Administrator" : "Staff" }}</span>
        </div>
        <button title="Keluar" @click="logout">
          <i class="pi pi-sign-out"></i>
        </button>
      </div>
    </aside>
    <nav class="mobile-bottom-nav" aria-label="Navigasi utama">
      <button
        v-for="item in mobilePrimaryItems"
        :key="item.id"
        :class="{ active: page === item.id }"
        @click="navigateMobile(item.id)"
      >
        <span class="mobile-nav-icon">
          <i :class="item.icon"></i>
          <b v-if="item.id === 'actions' && actionItems.length" class="mobile-nav-badge">{{ actionItems.length }}</b>
        </span>
        <small>{{ item.label === 'Gaji & Invoice' ? 'Gaji' : item.label }}</small>
      </button>
      <button :class="{ active: mobileMenuOpen || mobileMoreItems.some((item) => item.id === page) }" @click="mobileMenuOpen = true">
        <span class="mobile-nav-icon"><i class="pi pi-th-large"></i></span>
        <small>Lainnya</small>
      </button>
    </nav>
    <div v-if="mobileMenuOpen" class="mobile-menu-backdrop" @click.self="mobileMenuOpen = false">
      <section class="mobile-menu-sheet">
        <div class="mobile-menu-handle"></div>
        <div class="mobile-menu-head">
          <div>
            <strong>Menu Ryukomik</strong>
            <span>{{ user.username }} • {{ user.role === 'admin' ? 'Administrator' : 'Staff' }}</span>
          </div>
          <button aria-label="Tutup menu" @click="mobileMenuOpen = false">×</button>
        </div>
        <div class="mobile-menu-grid">
          <button v-for="item in mobileMoreItems" :key="item.id" :class="{ active: page === item.id }" @click="navigateMobile(item.id)">
            <i :class="item.icon"></i><span>{{ item.label }}</span>
          </button>
        </div>
        <button v-if="installPrompt" class="install-app-button" @click="installDashboard">
          <i class="pi pi-mobile"></i><span><b>Pasang Aplikasi</b><small>Tambahkan dashboard ke layar utama</small></span>
        </button>
        <button class="mobile-logout" @click="logout"><i class="pi pi-sign-out"></i> Keluar dari dashboard</button>
      </section>
    </div>
    <section class="content">
      <header>
        <div>
          <p class="eyebrow">RYUKOMIK WORKSPACE</p>
          <h2>{{ navItems.find((i) => i.id === page)?.label }}</h2>
        </div>
        <div class="header-actions">
          <Button
            v-if="user.role === 'admin'"
            label="Buat tugas"
            icon="pi pi-plus"
            @click="openTask()"
          />
          <div class="live"><span></span>Sistem aktif</div>
        </div>
      </header>
      <div v-if="error" class="notice error">
        <i class="pi pi-exclamation-circle"></i>{{ error
        }}<button @click="error = ''">×</button>
      </div>
      <div v-if="success" class="notice success">
        <i class="pi pi-check-circle"></i>{{ success
        }}<button @click="success = ''">×</button>
      </div>
      <template v-if="page === 'overview'"
        ><section class="mobile-quick-section">
          <div class="mobile-section-label"><span>Akses Cepat</span><small>Tindakan yang paling sering digunakan</small></div>
          <div class="mobile-quick-grid" v-if="user.role === 'admin'">
            <button @click="navigateMobile('projects')"><i class="pi pi-book"></i><span><b>Daftar Project</b><small>Tracker RAW</small></span></button>
            <button @click="openTask()"><i class="pi pi-plus-circle"></i><span><b>Buat Tugas</b><small>Kirim pekerjaan</small></span></button>
            <button @click="navigateMobile('actions')"><i class="pi pi-bell"></i><span><b>Review</b><small>{{ actionItems.length }} tindakan</small></span></button>
            <button @click="navigateMobile('payouts')"><i class="pi pi-money-bill"></i><span><b>Bayar Gaji</b><small>Proses transfer</small></span></button>
          </div>
          <div class="mobile-quick-grid" v-else>
            <button @click="navigateMobile('tasks')"><i class="pi pi-list-check"></i><span><b>Tugas Saya</b><small>Lihat progres kerja</small></span></button>
            <button @click="navigateMobile('deadlines')"><i class="pi pi-clock"></i><span><b>Deadline</b><small>Cek tenggat tugas</small></span></button>
          </div>
        </section>
        <div class="hero-card">
          <div>
            <p>Selamat datang kembali,</p>
            <h3>{{ user.username }}</h3>
            <span>{{
              user.role === "admin"
                ? "Kelola tim, pekerjaan, dan pembayaran dari satu tempat."
                : "Semua pekerjaan dan penghasilanmu ada di sini."
            }}</span>
          </div>
          <i class="pi pi-sparkles"></i>
        </div>
        <div class="stats-grid">
          <article>
            <span class="stat-icon blue"><i class="pi pi-inbox"></i></span>
            <div>
              <small>Tersedia</small
              ><strong>{{ overview.counts.open || 0 }}</strong>
            </div>
          </article>
          <article>
            <span class="stat-icon amber"><i class="pi pi-hourglass"></i></span>
            <div>
              <small>Dikerjakan</small
              ><strong>{{ overview.counts.claimed || 0 }}</strong>
            </div>
          </article>
          <article>
            <span class="stat-icon violet"><i class="pi pi-eye"></i></span>
            <div>
              <small>Menunggu review</small
              ><strong>{{ overview.counts.submitted || 0 }}</strong>
            </div>
          </article>
          <article>
            <span class="stat-icon red"><i class="pi pi-clock"></i></span>
            <div>
              <small>Deadline dekat</small
              ><strong>{{ overview.urgent_deadlines }}</strong>
            </div>
          </article>
        </div>
        <div class="summary-grid">
          <article class="panel">
            <p class="eyebrow">NILAI PEKERJAAN</p>
            <h3>{{ money(overview.total_value) }}</h3>
            <p>Total nilai tugas yang dapat Anda akses.</p>
          </article>
          <article class="panel next">
            <p class="eyebrow">AKSI CEPAT</p>
            <h3>
              {{
                overview.counts.revision
                  ? "Ada revisi yang perlu ditangani"
                  : "Operasional tim dalam kondisi baik"
              }}
            </h3>
            <div class="button-row">
              <Button
                label="Lihat tugas"
                icon="pi pi-arrow-right"
                @click="page = 'tasks'"
              /><Button
                v-if="user.role === 'admin'"
                label="Assign baru"
                severity="secondary"
                icon="pi pi-plus"
                @click="openTask()"
              />
            </div>
          </article></div>
        <section class="project-progress panel">
          <div class="section-title">
            <div>
              <span>Progres Proyek</span>
              <small>Ringkasan chapter berdasarkan status tugas terbaru.</small>
            </div>
            <div style="display: flex; gap: 8px; align-items: center;">
              <Button label="Daftar Project & RAW" icon="pi pi-book" severity="secondary" size="small" @click="page = 'projects'" />
              <Button label="Lihat semua tugas" text icon="pi pi-arrow-right" @click="page = 'tasks'" />
            </div>
          </div>
          <div v-if="overview.project_progress.length" class="project-progress-list">
            <article v-for="project in overview.project_progress" :key="project.manga">
              <div class="project-progress-head">
                <strong>{{ project.manga }}</strong>
                <span>{{ project.completed_chapters }}/{{ project.chapter_count }} chapter selesai</span>
              </div>
              <div class="project-progress-track" aria-label="Progres chapter">
                <span :style="{ width: `${Math.min(100, Math.round((project.completed_chapters / Math.max(project.chapter_count, 1)) * 100))}%` }"></span>
              </div>
              <div class="project-progress-meta">
                <span v-if="project.active_chapters">{{ project.active_chapters }} dikerjakan</span>
                <span v-if="project.review_chapters">{{ project.review_chapters }} menunggu review</span>
                <span v-if="project.revision_chapters">{{ project.revision_chapters }} revisi</span>
                <span v-if="!project.active_chapters && !project.review_chapters && !project.revision_chapters">Tidak ada tindakan aktif</span>
              </div>
            </article>
          </div>
          <div v-else class="empty">Belum ada tugas proyek untuk ditampilkan.</div>
        </section>
      </template>
      <Suspense v-if="page === 'actions'">
        <ActionCenterPage :items="actionItems" :loading="loading" @reload="loadPage" @handle="handleAction" />
        <template #fallback><div class="operations-skeleton"><span v-for="n in 4" :key="n"></span></div></template>
      </Suspense>
      <Suspense v-if="page === 'projects'">
        <ProjectsPage @create-task="handleCreateTaskFromProject" @open-qc="openQc" />
        <template #fallback><div class="operations-skeleton"><span v-for="n in 4" :key="n"></span></div></template>
      </Suspense>
      <Suspense v-if="page === 'qc'">
        <QcStudioPage
          :initial-assignment-id="activeQcTaskId"
          @task-approved="handleQcApproved"
          @task-revised="handleQcRevised"
        />
        <template #fallback><div class="operations-skeleton"><span v-for="n in 4" :key="n"></span></div></template>
      </Suspense>
      <Suspense v-if="page === 'operations'">
        <OperationsPage />
        <template #fallback><div class="operations-skeleton"><span v-for="n in 4" :key="n"></span></div></template>
      </Suspense>
      <Suspense v-if="page === 'bonuses'">
        <PerformanceBonusPage />
        <template #fallback><div class="operations-skeleton"><span v-for="n in 4" :key="n"></span></div></template>
      </Suspense>
      <Suspense v-if="page === 'scout'">
        <ScoutPage />
        <template #fallback><div class="operations-skeleton"><span v-for="n in 4" :key="n"></span></div></template>
      </Suspense>
      <ConverterPage v-if="page === 'converter'" />
      <OcrPage v-if="page === 'ocr'" />
      <NotificationPrefsPage v-if="page === 'notifications'" />
      <WorkloadPage v-if="page === 'workload'" />
      <template v-if="page === 'tasks'"
        ><div class="toolbar">
          <span class="search"
            ><i class="pi pi-search"></i
            ><InputText
              v-model="search"
              placeholder="Cari manga atau chapter"
              @keyup.enter="loadPage" /></span
          ><select v-model="status">
            <option value="">Semua status</option>
            <option v-for="(label, key) in statusLabel" :value="key">
              {{ label }}
            </option></select
          ><select v-if="user.role === 'admin'" v-model="staffFilter">
            <option value="">Semua staf</option>
            <option v-for="s in staff" :value="String(s.id)">
              {{ s.username }}
            </option></select
          ><select v-model="groupBy">
            <option value="none">Tanpa grup</option>
            <option value="staff">Grup per staf</option>
            <option value="status">Grup per status</option></select
          ><Button icon="pi pi-search" label="Cari" @click="loadPage" />
        </div>
        <section v-if="pairProjects.length" class="pair-projects">
          <div class="section-title"><div><span>Kolaborasi TL–TS</span><small>Satu ruang kerja, progres dan pembayaran per chapter.</small></div></div>
          <article v-for="project in pairProjects" :key="project.id" class="pair-project-card">
            <div class="pair-project-head">
              <div><small>PAIR PROJECT #{{ project.id }}</small><h3>{{ project.manga }}</h3><p>{{ project.tl_staff_name }} (TL) → {{ project.ts_staff_name }} (TS)</p></div>
              <a v-if="project.channel_id" :href="`https://discord.com/channels/1524448659951849666/${project.channel_id}`" target="_blank" rel="noopener" class="p-button p-button-sm p-button-secondary">Buka ruang Discord</a>
            </div>
            <div class="pair-rate-row"><span>TL {{ money(project.tl_rate_per_chapter) }}/chapter</span><span>TS {{ money(project.ts_rate_per_chapter) }}/chapter</span><span>Deadline {{ project.deadline_at || 'Tidak ditentukan' }}</span></div>
            <div class="pair-chapter-list">
              <div v-for="chapter in project.chapters" :key="chapter.id" class="pair-chapter-row">
                <div><b>Chapter {{ chapter.chapter }}</b><Tag :value="pairStatusLabel[chapter.status] || chapter.status" :severity="chapter.status === 'completed' ? 'success' : chapter.status.includes('revision') ? 'danger' : chapter.status === 'final_review' ? 'warn' : 'info'" /></div>
                <div class="button-row">
                  <a v-if="chapter.tl_link" :href="chapter.tl_link" target="_blank" rel="noopener" class="p-button p-button-sm p-button-secondary">Hasil TL</a>
                  <a v-if="chapter.final_link" :href="chapter.final_link" target="_blank" rel="noopener" class="p-button p-button-sm p-button-secondary">Hasil Final</a>
                  <template v-if="user.role === 'admin' && chapter.status === 'final_review'">
                    <Button label="Setujui Final" icon="pi pi-check" size="small" @click="approvePairChapter(project, chapter)" />
                    <Button label="Revisi TL" size="small" severity="danger" @click="revisePairChapter(project, chapter, 'tl')" />
                    <Button label="Revisi TS" size="small" severity="danger" @click="revisePairChapter(project, chapter, 'ts')" />
                    <Button label="Revisi Keduanya" size="small" severity="danger" @click="revisePairChapter(project, chapter, 'both')" />
                  </template>
                </div>
              </div>
            </div>
          </article>
        </section>
        <section
          v-for="group in groupedAssignments"
          :key="group.label"
          class="table-section"
        >
          <div class="section-title">
            <div>
              <span>{{ group.label }}</span
              ><small>{{ group.items.length }} tugas</small>
            </div>
          </div>
          <div class="table-card">
            <DataTable
              :value="group.items"
              :loading="loading"
              paginator
              :rows="10"
              responsiveLayout="scroll"
              ><Column field="id" header="#" sortable /><Column header="Proyek"
                ><template #body="{ data }"
                  ><strong>{{ data.manga }}</strong
                  ><small class="subline"
                    >Chapter {{ data.chapter }}</small
                  ></template
                ></Column
              ><Column v-if="user.role === 'admin'" header="Staff"
                ><template #body="{ data }"
                  ><div class="person">
                    <img
                      v-if="data.staff_avatar"
                      :src="data.staff_avatar"
                    /><span v-else class="mini-avatar">{{
                      initials(data.staff_name)
                    }}</span
                    ><span>{{ data.staff_name }}</span>
                  </div></template
                ></Column
              ><Column field="role" header="Role" /><Column header="Status"
                ><template #body="{ data }"
                  ><Tag
                    :value="statusLabel[data.status] || data.status"
                    :severity="severity(data.status)" /></template></Column
              ><Column header="Bayaran"
                ><template #body="{ data }">{{
                  money(data.final_rate)
                }}</template></Column
              ><Column header="Deadline"
                ><template #body="{ data }">{{
                  data.deadline_at || "—"
                }}</template></Column
              ><Column header="Hasil / Review"
                ><template #body="{ data }"
                  ><div class="button-row">
                    <Button
                      v-if="['submitted', 'revision', 'approved'].includes(data.status)"
                      label="QC Viewer"
                      icon="pi pi-search"
                      size="small"
                      severity="info"
                      @click="openQc(data.id)"
                    />
                    <a
                      v-if="data.gdrive_link"
                      :href="data.gdrive_link"
                      target="_blank"
                      rel="noopener"
                      class="p-button p-button-sm p-button-secondary"
                      >Buka Drive</a
                    >
                    <Button
                      v-if="submissionByTask.get(data.id)"
                      label="Arsip R2"
                      icon="pi pi-download"
                      size="small"
                      severity="secondary"
                      @click="downloadResult(submissionByTask.get(data.id)!)"
                    />
                    <Button
                      v-if="data.status === 'submitted'"
                      label="Setujui"
                      icon="pi pi-check"
                      size="small"
                      @click="approveTask(data)"
                    />
                    <Button
                      v-if="data.status === 'submitted'"
                      label="Revisi"
                      icon="pi pi-refresh"
                      size="small"
                      severity="danger"
                      @click="reviseTask(data)"
                    />
                    <Button
                      v-if="
                        user.role === 'admin' &&
                        ['open', 'claimed', 'submitted', 'revision'].includes(data.status)
                      "
                      label="Edit"
                      icon="pi pi-pencil"
                      size="small"
                      severity="secondary"
                      @click="editTask(data)"
                    />
                    <Button
                      v-if="
                        user.role === 'admin' &&
                        ['open', 'claimed'].includes(data.status)
                      "
                      label="Tarik"
                      icon="pi pi-trash"
                      size="small"
                      severity="danger"
                      @click="revokeTask(data)"
                    />
                    <span
                      v-if="
                        !data.gdrive_link &&
                        !submissionByTask.get(data.id) &&
                        data.status !== 'submitted'
                      "
                      class="muted"
                      >Belum ada</span
                    >
                  </div></template
                ></Column
              ></DataTable
            >
          </div>
        </section>
        <div class="server-pager">
          <Button icon="pi pi-chevron-left" severity="secondary" :disabled="taskPage <= 1" @click="changeServerPage('tasks', -1)" />
          <span>Halaman {{ taskPage }} / {{ taskPages }} • {{ taskTotal }} tugas</span>
          <Button icon="pi pi-chevron-right" severity="secondary" :disabled="taskPage >= taskPages" @click="changeServerPage('tasks', 1)" />
        </div></template
      >
      <template v-if="page === 'staff'"
        ><div class="section-header">
          <div>
            <span>Tim Staff</span>
            <small>{{ staff.length }} anggota terdaftar</small>
          </div>
          <Button
            label="Sync Discord"
            icon="pi pi-refresh"
            severity="secondary"
            :loading="loading"
            @click="syncStaff"
          />
        </div>
        <section class="panel staff-message-composer">
          <div class="staff-message-intro">
            <span class="staff-message-icon"><i class="pi pi-megaphone"></i></span>
            <div><p class="eyebrow">PESAN KE TIKET STAFF</p><h3>Kirim pesan ke seluruh tim</h3><p>Pesan dikirim langsung ke tiket privat setiap staff di Discord.</p></div>
          </div>
          <div class="staff-message-modes">
            <label :class="{ active: !staffQuestionForm.requires_answer }">
              <input v-model="staffQuestionForm.requires_answer" type="radio" :value="false" />
              <i class="pi pi-megaphone"></i><span><b>Pengumuman</b><small>Informasi satu arah tanpa jawaban.</small></span>
            </label>
            <label :class="{ active: staffQuestionForm.requires_answer }">
              <input v-model="staffQuestionForm.requires_answer" type="radio" :value="true" />
              <i class="pi pi-comments"></i><span><b>Pertanyaan</b><small>Staff menjawab melalui tombol Discord.</small></span>
            </label>
          </div>
          <div class="staff-message-fields">
            <label><span>Judul pesan</span><InputText v-model="staffQuestionForm.title" placeholder="Contoh: Jadwal kerja minggu ini" /></label>
            <label><span>Isi pesan</span><textarea v-model="staffQuestionForm.message" rows="5" maxlength="1800" placeholder="Tulis pesan untuk seluruh staff..."></textarea><small>{{ staffQuestionForm.message.length }}/1800 karakter</small></label>
          </div>
          <div class="staff-message-footer">
            <div><i class="pi pi-users"></i><span><b>{{ staff.length }} staff</b><small>akan menerima pesan di tiket privat</small></span></div>
            <Button :label="staffQuestionForm.requires_answer ? 'Kirim pertanyaan' : 'Kirim pengumuman'" icon="pi pi-send" :loading="loading" @click="createStaffQuestion" />
          </div>
        </section>
        <section v-if="staffQuestions.length" class="panel recruitment-applicants">
          <div class="section-title"><div><span>Jawaban Staff</span><small>Jawaban terbaru dari tombol di tiket Discord.</small></div></div>
          <div class="recap-list">
            <article v-for="question in staffQuestions" :key="question.id">
              <div><b>{{ question.title }}</b><small>{{ question.message }} • {{ question.status === 'open' ? 'Aktif' : 'Ditutup' }}</small></div>
              <div><small>Sudah menjawab</small><b>{{ question.responses?.length || 0 }} staff</b></div>
              <Button v-if="question.status === 'open' && question.requires_answer" label="Tutup" severity="secondary" icon="pi pi-lock" @click="closeStaffQuestion(question.id)" />
            </article>
            <template v-for="question in staffQuestions" :key="`answers-${question.id}`">
              <article v-for="response in question.responses" :key="`${question.id}-${response.staff_id}`">
                <div><b>{{ staffDisplayName(response.staff_id) }}</b><small>Jawaban untuk: {{ question.title }}</small></div>
                <div style="flex:1"><small>Jawaban</small><b>{{ response.answer }}</b></div>
              </article>
            </template>
          </div>
        </section>
        <div class="people-grid">
          <article v-for="s in staff" :key="s.id" class="person-card">
            <div class="person-head">
              <img v-if="s.avatar" :src="s.avatar" /><span
                v-else
                class="large-avatar"
                >{{ initials(s.username) }}</span
              >
              <div>
                <h3>{{ s.username }}</h3>
                <small>{{ s.active_count }} tugas aktif</small>
              </div>
              <Button
                icon="pi pi-plus"
                rounded
                text
                title="Beri tugas"
                @click="openTask(s.id)"
              />
            </div>
            <div class="person-stats">
              <span
                ><small>Total tugas</small><b>{{ s.task_count }}</b></span
              ><span
                ><small>Belum dibayar</small
                ><b>{{ money(s.approved_amount) }}</b></span
              ><span
                ><small>Sudah dibayar</small
                ><b>{{ money(s.paid_amount) }}</b></span
              >
            </div>
          </article>
        </div></template
      >
      <template v-if="page === 'payrates'"
        ><div class="payrate-grid">
          <article
            v-for="item in payrates"
            :key="item.role"
            class="panel rate-card"
          >
            <span>{{ item.role }}</span>
            <h3>
              {{
                item.role === "TL"
                  ? "Translator"
                  : item.role === "TS"
                    ? "Typesetter"
                    : "TL + TS"
              }}
            </h3>
            <label class="rate-input">
              <small>Minimum per chapter</small>
              <InputNumber
                v-model="item.min_rate"
                mode="currency"
                currency="IDR"
                locale="id-ID"
                :min="0"
              />
            </label>
            <label class="rate-input">
              <small>Maksimum per chapter</small>
              <InputNumber
                v-model="item.max_rate"
                mode="currency"
                currency="IDR"
                locale="id-ID"
                :min="item.min_rate"
              />
            </label>
            <strong class="rate-range">{{ money(item.min_rate) }} – {{ money(item.max_rate) }}</strong>
            <Button
              label="Simpan rate"
              icon="pi pi-check"
              :loading="loading"
              @click="saveRate(item)"
            /><small>Staff aktif akan diberi tahu melalui tiket privat.</small>
          </article>
        </div></template
      >
      <template v-if="page === 'recruitment'">
        <section
          v-if="recruitment.test_material"
          class="panel recruitment-summary"
          :class="{ 'material-warning': recruitment.test_material.status !== 'active' }"
        >
          <div>
            <p class="eyebrow">BAHAN TES AKTIF</p>
            <h3>{{ recruitment.test_material.status === 'expired' ? 'Bahan perlu diperbarui' : recruitment.test_material.status === 'expiring' ? 'Bahan segera kedaluwarsa' : 'Bahan terbaru • 20 halaman' }}</h3>
            <p>
              Satu bahan untuk TL, TS, dan TL+TS.
              <a :href="recruitment.test_material.url" target="_blank">Buka bahan Drive</a>
              • <a :href="recruitment.test_material.tl_example_url" target="_blank">Contoh TL</a>
              • <a :href="recruitment.test_material.ts_assets_url" target="_blank">Asset TS</a>
              <span v-if="recruitment.test_material.hours_remaining !== null">
                • {{ recruitment.test_material.hours_remaining > 0 ? `${Math.ceil(recruitment.test_material.hours_remaining / 24)} hari tersisa` : 'sudah kedaluwarsa' }}
              </span>
            </p>
          </div>
          <Tag
            :value="recruitment.test_material.status === 'active' ? 'Aktif' : recruitment.test_material.status === 'expiring' ? 'Segera habis' : 'Perbarui'"
            :severity="recruitment.test_material.status === 'active' ? 'success' : recruitment.test_material.status === 'expiring' ? 'warn' : 'danger'"
          />
        </section>
        <section v-if="recruitment.test_material" class="panel recruitment-preview">
          <div style="width:100%">
            <p class="eyebrow">SETTING BAHAN GOOGLE DRIVE</p>
            <h3>Link bahan tes</h3>
            <div class="form-grid">
              <label class="wide">Bahan tes utama<InputText v-model="recruitment.test_material.url" placeholder="https://drive.google.com/..." /></label>
              <label>Contoh Translator<InputText v-model="recruitment.test_material.tl_example_url" placeholder="https://drive.google.com/..." /></label>
              <label>Asset Typesetter<InputText v-model="recruitment.test_material.ts_assets_url" placeholder="https://drive.google.com/..." /></label>
            </div>
          </div>
          <Button label="Simpan link bahan" icon="pi pi-link" :loading="loading" @click="saveRecruitmentMaterials" />
        </section>
        <section class="panel recruitment-preview">
          <div style="width:100%">
            <p class="eyebrow">PENGUMUMAN PELAMAR</p>
            <h3>Kirim ke semua tiket rekrutmen aktif</h3>
            <textarea v-model="recruitmentAnnouncement" rows="4" maxlength="1800" placeholder="Tulis informasi untuk para pelamar..."></textarea>
          </div>
          <Button label="Kirim pengumuman" icon="pi pi-send" :loading="loading" @click="sendRecruitmentAnnouncement" />
        </section>
        <section class="panel recruitment-summary">
          <div>
            <p class="eyebrow">RECRUITMENT CONTROL</p>
            <h3>{{ recruitment.positions.some((item) => item.enabled) ? "Rekrutmen dibuka" : "Rekrutmen ditutup" }}</h3>
            <p>
              Pilih posisi yang boleh dilamar. Pelamar yang sudah memilih posisi tetap dapat
              menyelesaikan prosesnya.
            </p>
          </div>
          <Tag
            :value="recruitment.positions.some((item) => item.enabled) ? 'Aktif' : 'Ditutup'"
            :severity="recruitment.positions.some((item) => item.enabled) ? 'success' : 'danger'"
          />
        </section>
        <div class="recruitment-grid">
          <article
            v-for="item in recruitment.positions"
            :key="item.position"
            class="panel recruitment-card"
            :class="{ disabled: !item.enabled }"
          >
            <div class="recruitment-card-head">
              <div>
                <span>{{ item.position }}</span>
                <h3>{{
                  item.position === "TL"
                    ? "Translator"
                    : item.position === "TS"
                      ? "Typesetter / Editor"
                      : "Translator + Typesetter"
                }}</h3>
              </div>
              <label class="switch">
                <input v-model="item.enabled" type="checkbox" />
                <span></span>
              </label>
            </div>
            <p>{{
              item.position === "TL"
                ? "Tes terjemahan Bahasa Inggris ke Indonesia."
                : item.position === "TS"
                  ? "Tes cleaning, redraw, dan typesetting."
                  : "Pelamar mengerjakan paket tes TL dan TS."
            }}</p>
            <div class="recruitment-meta">
              <span><small>Pelamar menunggu review</small><b>{{ item.active_count }}</b></span>
              <span><small>Status</small><b>{{ item.enabled ? "Dibuka" : "Ditutup" }}</b></span>
            </div>
          </article>
        </div>
        <section class="panel recruitment-preview">
          <div>
            <p class="eyebrow">PREVIEW DISCORD</p>
            <h3>Posisi yang terlihat oleh pelamar</h3>
            <p v-if="recruitment.positions.some((item) => item.enabled)">
              {{ recruitment.positions.filter((item) => item.enabled).map((item) => item.position).join(" • ") }}
            </p>
            <p v-else>Rekrutmen sedang ditutup dan tombol pendaftaran akan dinonaktifkan.</p>
          </div>
          <Button
            label="Simpan & perbarui Discord"
            icon="pi pi-check"
            :loading="loading"
            @click="saveRecruitmentSettings"
          />
        </section>
        <section class="panel recruitment-applicants">
          <div class="section-title"><div><span>Pelamar Aktif</span><small>Tutup hanya pendaftaran yang belum menjadi Staff.</small></div></div>
          <div v-if="recruitmentSubmissions.length" class="recap-list">
            <article v-for="item in recruitmentSubmissions" :key="item.id">
              <div><b>{{ item.applicant_name }}</b><small>#{{ item.ticket_name }} • Posisi {{ item.position }} • <a :href="`https://discord.com/channels/1524448659951849666/${item.ticket_channel_id}`" target="_blank">Buka tiket</a></small></div>
              <div><small>Discord ID</small><b>{{ item.applicant_id }}</b></div>
              <Button label="Tutup pendaftaran" severity="danger" icon="pi pi-lock" @click="closeRegistration(item)" />
            </article>
          </div>
          <div v-else class="empty">Tidak ada pendaftaran aktif.</div>
        </section>
      </template>
    <div v-if="closeRegistrationTarget" class="modal-backdrop" @click.self="closeRegistrationTarget = null">
      <form class="modal-card" @submit.prevent="confirmCloseRegistration">
        <div class="modal-head"><div><p class="eyebrow">TUTUP PENDAFTARAN</p><h3>{{ closeRegistrationTarget.applicant_name }}</h3></div><button type="button" @click="closeRegistrationTarget = null">×</button></div>
        <p class="confirm-warning">Channel <b>#{{ closeRegistrationTarget.ticket_name }}</b> akan dihapus permanen. Pilih alasan penutupan.</p>
        <div class="form-grid"><label class="wide">Alasan<select v-model="closeRegistrationReason"><option>Batal mendaftar</option><option>Tidak aktif / tidak melanjutkan</option><option>Tidak memenuhi persyaratan</option><option>Posisi rekrutmen ditutup</option></select></label></div>
        <div class="modal-actions"><Button label="Batal" severity="secondary" type="button" @click="closeRegistrationTarget = null"/><Button label="Hapus channel tiket" severity="danger" icon="pi pi-trash" type="submit" :loading="loading"/></div>
      </form>
    </div>
      <template v-if="page === 'deadlines'"
        ><div class="table-card">
          <DataTable :value="deadlines" :loading="loading"
            ><Column field="deadline_at" header="Deadline" sortable /><Column header="Urgensi"><template #body="{ data }"><Tag :value="deadlineUrgency(data.deadline_at).label" :severity="deadlineUrgency(data.deadline_at).severity" /></template></Column><Column
              field="manga"
              header="Manga" /><Column
              field="chapter"
              header="Chapter" /><Column
              field="staff_name"
              header="Staff" /><Column header="Status"
              ><template #body="{ data }"
                ><Tag
                  :value="statusLabel[data.status]"
                  :severity="severity(data.status)" /></template></Column
          ></DataTable></div>
      </template>
      <template v-if="page === 'recap'"
        ><div class="toolbar recap-toolbar">
          <label>Periode<input v-model="period" type="month" /></label
          ><Button label="Tampilkan" icon="pi pi-filter" @click="loadPage" />
        </div>
        <div class="salary-summary">
          <article>
            <small>Saldo seluruh periode</small><strong>{{ money(recapSummary.unpaid_amount) }}</strong>
          </article>
          <article>
            <small>Total penghasilan</small><strong>{{ money(recapSummary.total_earned) }}</strong>
          </article>
          <article>
            <small>Total sudah dibayar</small><strong>{{ money(recapSummary.paid_amount) }}</strong>
          </article>
          <article>
            <small>Total periode {{ period }}</small><strong>{{ money(recapTotal) }}</strong>
          </article>
          <article>
            <small>Belum dibayar periode ini</small><strong>{{ money(pendingTotal) }}</strong>
          </article>
          <article>
            <small>Invoice periode ini</small><strong>{{ invoices.length }}</strong>
          </article>
        </div>
        <div class="recap-layout">
          <section>
            <div class="section-title">
              <div>
                <span>Rekap per staf</span
                ><small>Dikelompokkan berdasarkan username Discord</small>
              </div>
            </div>
            <div class="recap-list">
              <article v-for="r in recap" :key="r.staff_id">
                <div class="person">
                  <img v-if="r.staff_avatar" :src="r.staff_avatar" /><span
                    v-else
                    class="mini-avatar"
                    >{{ initials(r.staff_name) }}</span
                  >
                  <div>
                    <b>{{ r.staff_name }}</b
                    ><small>{{ r.chapter_count }} chapter</small>
                  </div>
                </div>
                <div>
                  <small>Belum dibayar</small
                  ><b>{{ money(r.pending_amount) }}</b>
                </div>
                <div>
                  <small>Total periode</small><b>{{ money(r.total_amount) }}</b>
                </div>
                <Button
                  label="Buat invoice"
                  icon="pi pi-file"
                  :disabled="!r.pending_amount"
                  @click="createInvoice(r)"
                />
              </article>
              <p v-if="!recap.length" class="empty">
                Belum ada tugas approved/paid pada periode ini.
              </p>
            </div>
          </section>
          <section>
            <div class="section-title">
              <div><span>Invoice</span><small>Riwayat pembayaran</small></div>
            </div>
            <div class="invoice-list">
              <article v-for="inv in invoices" :key="inv.id">
                <div>
                  <Tag
                    :value="inv.status === 'paid' ? 'Lunas' : 'Terbit'"
                    :severity="inv.status === 'paid' ? 'success' : 'warn'"
                  />
                  <h4>{{ inv.invoice_number }}</h4>
                  <p>{{ inv.staff_name }} · {{ inv.chapter_count }} chapter</p>
                </div>
                <strong>{{ money(inv.total_amount) }}</strong>
                <div class="invoice-actions">
                  <Button
                    icon="pi pi-print"
                    text
                    rounded
                    title="Cetak"
                    @click="printInvoice(inv)"
                  /><Button
                    v-if="inv.status === 'issued'"
                    icon="pi pi-sync"
                    text
                    rounded
                    title="Hitung ulang"
                    @click="refreshInvoice(inv)"
                  /><Button
                    v-if="inv.status === 'issued'"
                    icon="pi pi-trash"
                    severity="danger"
                    text
                    rounded
                    title="Hapus invoice"
                    @click="deleteInvoice(inv)"
                  /><Button
                    v-if="inv.status === 'issued'"
                    label="Proses pembayaran"
                    size="small"
                    @click="payInvoice(inv)"
                  /><Button
                    v-if="inv.status === 'paid'"
                    label="Koreksi"
                    severity="secondary"
                    size="small"
                    @click="correctionInvoice(inv)"
                  />
                </div>
              </article>
              <p v-if="!invoices.length" class="empty">
                Belum ada invoice untuk periode ini.
              </p>
            </div>
          </section>
        </div></template
      >
      <template v-if="page === 'audit'"
        ><div class="table-card">
          <DataTable :value="audit" :loading="loading"
            ><Column field="created_at" header="Waktu" /><Column
              field="actor_id"
              header="Pelaku" /><Column
              field="action"
              header="Aktivitas" /><Column
              field="target_type"
              header="Target" /><Column field="target_id" header="ID"
          /></DataTable></div>
          <div class="server-pager">
            <Button icon="pi pi-chevron-left" severity="secondary" :disabled="auditPage <= 1" @click="changeServerPage('audit', -1)" />
            <span>Halaman {{ auditPage }} / {{ auditPages }} • {{ auditTotal }} aktivitas</span>
            <Button icon="pi pi-chevron-right" severity="secondary" :disabled="auditPage >= auditPages" @click="changeServerPage('audit', 1)" />
          </div>
      </template>
      <template v-if="page === 'payouts'">
        <div class="toolbar">
          <select v-model="payoutStatus" @change="loadPage">
            <option value="">Semua status</option><option value="issued">Menunggu transfer</option>
            <option value="awaiting_method">Menunggu metode</option>
            <option value="paid">Sudah dibayar</option><option value="rejected">Ditolak</option>
          </select>
          <Button label="Muat ulang" icon="pi pi-refresh" @click="loadPage" />
        </div>
        <div class="table-card">
          <DataTable :value="payouts" :loading="loading" responsiveLayout="scroll">
            <Column header="Staff"><template #body="{ data }"><div class="person">
              <img v-if="data.staff_avatar" :src="data.staff_avatar" /><span v-else class="mini-avatar">{{ initials(data.staff_name) }}</span>
              <span>{{ data.staff_name }}</span></div></template></Column>
            <Column header="Jenis"><template #body="{ data }">{{ data.payout_type === "instant" ? "Langsung" : "Terjadwal" }}</template></Column>
            <Column field="invoice_number" header="Invoice" />
            <Column header="Jumlah"><template #body="{ data }">{{ data.chapter_count }} chapter · {{ money(data.total_amount) }}</template></Column>
            <Column header="Status"><template #body="{ data }"><Tag
              :value="data.status === 'awaiting_method' ? 'Menunggu metode' : data.status === 'issued' ? 'Menunggu transfer' : data.status === 'paid' ? 'Dibayar' : 'Ditolak'"
              :severity="data.status === 'paid' ? 'success' : ['issued','awaiting_method'].includes(data.status) ? 'warn' : 'danger'" /></template></Column>
            <Column header="Aksi"><template #body="{ data }"><div class="button-row">
              <Button label="Detail" size="small" severity="secondary" @click="openPayout(data)" />
              <Button v-if="data.status === 'paid'" label="PDF" size="small" icon="pi pi-file-pdf" text @click="openPayoutPdf(data)" />
              <Button v-if="data.status === 'paid' && (!data.invoice_sent_at || data.invoice_send_error)" label="Kirim ulang" size="small" text @click="resendInvoice(data)" />
              <Button v-if="data.status === 'issued'" label="Sudah ditransfer" size="small" @click="confirmPayout(data)" />
              <Button v-if="data.status === 'issued'" label="Tolak" size="small" severity="danger" @click="rejectPayout(data)" />
            </div></template></Column>
          </DataTable>
        </div>
        <div class="server-pager">
          <Button icon="pi pi-chevron-left" severity="secondary" :disabled="payoutPage <= 1" @click="changeServerPage('payouts', -1)" />
          <span>Halaman {{ payoutPage }} / {{ payoutPages }} • {{ payoutTotal }} pembayaran</span>
          <Button icon="pi pi-chevron-right" severity="secondary" :disabled="payoutPage >= payoutPages" @click="changeServerPage('payouts', 1)" />
        </div>
      </template>
    </section>
    <div v-if="payoutDetail" class="modal-backdrop" @click.self="payoutDetail = null">
      <section class="modal-card payout-detail">
        <div class="modal-head"><div><p class="eyebrow">PAYMENT DESTINATION</p><h3>{{ payoutDetail.staff_name }}</h3></div>
          <button type="button" @click="payoutDetail = null">×</button></div>
        <div class="payment-destination">
          <span><small>Metode</small><b>{{ payoutDetail.method.method_type.toUpperCase() }} · {{ payoutDetail.method.provider }}</b></span>
          <span><small>Nama pemilik</small><b>{{ payoutDetail.method.account_name }}</b></span>
          <span v-if="payoutDetail.method.account_number"><small>Nomor tujuan</small><b>{{ payoutDetail.method.account_number }}</b>
            <Button label="Salin" size="small" text @click="copyAccount(payoutDetail!.method.account_number)" /></span>
          <Button v-if="payoutDetail.method.method_type === 'qris'" label="Buka QRIS (10 menit)" icon="pi pi-qrcode" @click="openQris(payoutDetail)" />
        </div>
        <div class="salary-summary payout-summary">
          <article><small>Total transfer</small><strong>{{ money(payoutDetail.total_amount) }}</strong></article>
          <article><small>Jumlah pekerjaan</small><strong>{{ payoutDetail.chapter_count }} chapter</strong></article>
          <article><small>Invoice</small><strong>{{ payoutDetail.invoice_number }}</strong></article>
        </div>
        <div class="table-card"><DataTable :value="payoutDetail.items" scrollable scrollHeight="260px">
          <Column field="manga" header="Judul" /><Column field="chapter" header="Chapter" /><Column field="role" header="Role" />
          <Column header="Bayaran"><template #body="{ data }">{{ money(data.amount) }}</template></Column>
        </DataTable></div>
        <div v-if="payoutDetail.status === 'paid'" class="button-row payout-pdf-actions">
          <Button label="Download PDF" icon="pi pi-file-pdf" @click="openPayoutPdf(payoutDetail)" />
          <Button label="Kirim Ulang ke Tiket" severity="secondary" icon="pi pi-send" @click="resendInvoice(payoutDetail)" />
          <small v-if="payoutDetail.invoice_sent_at">Terakhir dikirim: {{ payoutDetail.invoice_sent_at }}</small>
          <small v-if="payoutDetail.invoice_send_error" class="notice-error">{{ payoutDetail.invoice_send_error }}</small>
        </div>
        <div v-if="payoutDetail.status === 'issued'" class="modal-actions">
          <Button label="Tolak" severity="danger" @click="rejectPayout(payoutDetail!)" />
          <Button label="Konfirmasi Sudah Ditransfer" icon="pi pi-check" @click="confirmPayout(payoutDetail!)" />
        </div>
      </section>
    </div>
    <div v-if="paymentConfirmation" class="modal-backdrop" @click.self="paymentConfirmation = null">
      <section class="modal-card payment-confirm-card">
        <div class="modal-head"><div><p class="eyebrow">FINAL CONFIRMATION</p>
          <h3>Konfirmasi Transfer</h3></div>
          <button type="button" @click="paymentConfirmation = null">×</button></div>
        <div class="confirm-warning"><i class="pi pi-shield"></i>
          <p>Pastikan uang sudah benar-benar berhasil ditransfer. Tindakan ini menandai seluruh tugas sebagai dibayar.</p></div>
        <div class="payment-destination">
          <span><small>Staff</small><b>{{ paymentConfirmation.staff_name }}</b></span>
          <span><small>Invoice</small><b>{{ paymentConfirmation.invoice_number }}</b></span>
          <span><small>Total transfer</small><b>{{ money(paymentConfirmation.total_amount) }}</b></span>
          <span><small>Jumlah pekerjaan</small><b>{{ paymentConfirmation.chapter_count }} chapter</b></span>
          <span><small>Metode</small><b>{{ paymentConfirmation.method.provider }}</b></span>
          <span><small>Nama pemilik</small><b>{{ paymentConfirmation.method.account_name }}</b></span>
          <span class="wide"><small>Tujuan pembayaran</small>
            <b>{{ paymentConfirmation.method.account_number || "QRIS" }}</b></span>
        </div>
        <div class="modal-actions">
          <Button label="Kembali" severity="secondary" :disabled="loading" @click="paymentConfirmation = null" />
          <Button label="Konfirmasi Transfer" icon="pi pi-check" :loading="loading"
            @click="completePayout(paymentConfirmation!)" />
        </div>
      </section>
    </div>
    <div
      v-if="showTask"
      class="modal-backdrop"
      @click.self="showTask = false; editingTask = null"
    >
      <form class="modal-card" @submit.prevent="createTask">
        <div class="modal-head">
          <div>
            <p class="eyebrow">ASSIGNMENT</p>
            <h3>{{ editingTask ? `Edit tugas #${editingTask.id}` : "Buat tugas baru" }}</h3>
          </div>
          <button type="button" @click="showTask = false; editingTask = null">×</button>
        </div>
        <div class="form-grid">
          <div class="wide manga-search-field">
            <div class="manga-search-header">
              <label>Judul manga</label>
              <div class="manga-search-filter">
                <span>Filter sumber:</span>
                <select v-model="mangaSearchSource" @change="onMangaSearchInput">
                  <option value="all">Semua sumber</option>
                  <option value="asura">Asura</option>
                  <option value="omega">Omega</option>
                  <option value="doujiva">Doujiva</option>
                  <option value="diva">Diva</option>
                  <option value="evascan">EvaScan</option>
                  <option value="thunder">Thunder</option>
                  <option value="vortex">Vortex</option>
                  <option value="qimanga">QiManga</option>
                  <option value="demon">Demon</option>
                  <option value="kagane">Kagane</option>
                  <option value="mgeko">Mgeko</option>
                </select>
              </div>
            </div>
            <div class="manga-input-wrapper">
              <InputText
                v-model="task.manga"
                required
                placeholder="Ketik judul manga untuk mencari... (contoh: Magic, Solo, Let's Do It)"
                autocomplete="off"
                @input="onMangaSearchInput"
                @focus="mangaDropdownOpen = true"
              />
              <i v-if="mangaSearching" class="pi pi-spin pi-spinner search-icon-right"></i>
              <i v-else-if="task.manga" class="pi pi-times search-icon-right clickable" @click="task.manga = ''; clearSelectedSource(); mangaSearchResults = []; mangaDropdownOpen = false"></i>
              <i v-else class="pi pi-search search-icon-right"></i>
            </div>

            <!-- Selected source badge pill -->
            <div v-if="task.raw_source" class="selected-source-pill">
              <span class="source-tag" :data-source="task.raw_source">
                <i class="pi pi-check-circle"></i> {{ task.raw_source.toUpperCase() }}
              </span>
              <span class="source-slug">{{ task.raw_id }}</span>
              <button type="button" class="btn-clear-source" title="Ganti/hapus sumber" @click="clearSelectedSource">×</button>
            </div>

            <!-- Autocomplete Dropdown List -->
            <div
              v-if="mangaDropdownOpen && (mangaSearchResults.length > 0 || (task.manga.trim().length >= 2 && !mangaSearching))"
              class="manga-search-dropdown"
            >
              <div v-if="mangaSearchResults.length > 0" class="dropdown-results-list">
                <div
                  v-for="item in mangaSearchResults"
                  :key="item.source + '-' + item.id"
                  class="dropdown-item"
                  :class="{ selected: task.manga === item.title && task.raw_source === item.source }"
                  @click="selectMangaResult(item)"
                >
                  <div class="dropdown-item-thumb">
                    <img v-if="item.image" :src="item.image" :alt="item.title" loading="lazy" @error="(e: any) => e.target.style.display = 'none'" />
                    <i v-else class="pi pi-book"></i>
                  </div>
                  <div class="dropdown-item-info">
                    <div class="dropdown-item-title">{{ item.title }}</div>
                    <div class="dropdown-item-meta">
                      <span class="source-badge" :data-source="item.source">{{ item.source_name }}</span>
                      <span v-if="item.latest_chapter" class="chapter-badge">{{ item.latest_chapter }}</span>
                      <span v-if="item.rating && item.rating !== '0'" class="rating-badge"><i class="pi pi-star-fill"></i> {{ item.rating }}</span>
                    </div>
                  </div>
                  <div class="dropdown-item-action">
                    <i class="pi pi-check"></i>
                  </div>
                </div>
              </div>
              <div v-else-if="task.manga.trim().length >= 2 && !mangaSearching" class="dropdown-empty">
                <i class="pi pi-info-circle"></i>
                <span>Tidak ada hasil langsung dari sumber RAW. Anda tetap dapat menggunakan judul manual di atas.</span>
              </div>
            </div>
          </div><label
            >Chapter (maks. 5)<InputText
              v-model="task.chapter"
              required
              placeholder="1-5 atau 1,3,7,8.5" /></label
          ><label
            >Role<select v-model="task.role">
              <option>TL</option>
              <option>TS</option>
              <option>TL+TS</option>
              <option value="PAIR">Pair TL → TS (dua staff)</option>
            </select></label
          ><div v-if="task.role === 'PAIR'" class="wide pair-guide"><b>Alur Pair: TL → TS</b><span>Tugas TL dikirim sekarang. Setelah Anda menyetujui hasil TL, tugas TS aktif otomatis dan membawa link hasil terjemahan.</span></div>
          ><div class="wide raw-rate-tool">
            <div>
              <small>REKOMENDASI OTOMATIS</small>
              <b>Analisis beban RAW</b>
              <span>Cek jumlah halaman dan tinggi gambar dari sumber RAW yang cocok.</span>
            </div>
            <Button type="button" label="Analisis RAW" icon="pi pi-sparkles" severity="secondary"
              :loading="rawRateAnalyzing" @click="analyzeRawRate" />
          </div
          ><label class="wide">Mode RAW<select v-model="task.raw_mode"><option value="editor_safe">Aman untuk Editor — maksimal 8192 px</option><option value="original">RAW Original — tanpa resize</option></select><small>{{ task.raw_mode === 'original' ? 'Kualitas dan ukuran asli dipertahankan; gambar panjang mungkin sulit dibuka di Ibis.' : 'Gambar sangat panjang dikecilkan proporsional agar aman dibuka editor.' }}</small></label
          ><label class="wide">Paket Download RAW<select v-model="task.raw_pack_mode"><option value="normal">Normal — satu file per halaman</option><option value="merge_16000">Gabung Lossless — maksimal sekitar 16.000 px</option></select><small>{{ task.raw_pack_mode === 'merge_16000' ? 'Beberapa halaman digabung vertikal sebagai PNG lossless tanpa resize. Jumlah file lebih sedikit.' : 'Setiap halaman RAW tetap menjadi file terpisah.' }}</small></label
          ><div v-if="rawRateAnalysis" class="wide raw-rate-result" :class="rawRateAnalysis.workload.toLowerCase()">
            <div>
              <small>{{ rawRateAnalysis.source.toUpperCase() }} · {{ rawRateAnalysis.matched_title }}</small>
              <b>{{ rawRateAnalysis.workload }} — {{ money(rawRateAnalysis.rate_per_chapter) }}/chapter</b>
              <span>{{ rawRateAnalysis.reason }}. {{ rawRateAnalysis.measured_pages }}/{{ rawRateAnalysis.page_count }} gambar berhasil diukur.</span>
            </div>
            <span class="rate-range">Rentang {{ money(rawRateAnalysis.minimum_rate) }}–{{ money(rawRateAnalysis.maximum_rate) }}</span>
          </div
          ><label :class="task.role === 'PAIR' ? '' : 'wide'"
            >{{ task.role === 'PAIR' ? 'Staff Translator (TL)' : 'Staff tujuan' }}<select v-model="task.staff_id" :disabled="!!editingTask" required>
              <option value="" disabled>Pilih staf Discord</option>
              <option v-for="s in staff" :value="String(s.id)">
                {{ s.username }}
              </option>
            </select></label
          ><label v-if="task.role === 'PAIR'">Staff Typesetter (TS)<select v-model="task.ts_staff_id" required><option value="" disabled>Pilih staf Discord</option><option v-for="s in staff" :value="String(s.id)">{{ s.username }}</option></select></label
          ><label
            >{{ task.role === 'PAIR' ? 'Rate TL / chapter' : 'Bayaran per chapter' }}<InputNumber
              v-model="task.final_rate"
              mode="currency"
              currency="IDR"
              locale="id-ID"
              :min="0" /></label
          ><label v-if="task.role === 'PAIR'">Rate TS / chapter<InputNumber v-model="task.ts_rate" mode="currency" currency="IDR" locale="id-ID" :min="0" /></label
          ><div class="wide upload-tip">
            <i class="pi pi-calculator"></i>
            <span>{{ taskChapterCount || 0 }} chapter × {{ money(task.final_rate) }} = <b>{{ money(taskTotalRate) }}</b></span>
          </div
          ><label
            >Deadline wajib<input v-model="task.deadline_at" type="date" :min="new Date().toISOString().slice(0, 10)" required
          /></label>
        </div>
        <div class="modal-actions">
          <Button
            type="button"
            label="Batal"
            severity="secondary"
            @click="showTask = false; editingTask = null"
          /><Button
            type="submit"
            :label="editingTask ? 'Simpan perubahan' : 'Kirim tugas'"
            :icon="editingTask ? 'pi pi-check' : 'pi pi-send'"
            :loading="loading"
          />
        </div>
      </form>
    </div>
    <div
      v-if="uploadTask"
      class="modal-backdrop"
      @click.self="uploadTask = null"
    >
      <form class="modal-card upload-card" @submit.prevent="submitUpload">
        <div class="modal-head">
          <div>
            <p class="eyebrow">SUBMIT HASIL GAMBAR</p>
            <h3>{{ uploadTask.manga }} · Ch. {{ uploadTask.chapter }}</h3>
          </div>
          <button type="button" @click="uploadTask = null">×</button>
        </div>
        <div class="upload-drop">
          <i class="pi pi-images"></i
          ><strong>Pilih semua gambar chapter</strong>
          <p>
            Pilih sekaligus dari halaman pertama sampai terakhir. Dashboard
            mengurutkan, mengganti nama menjadi 001, 002, dst., lalu membuat ZIP
            otomatis.
          </p>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            multiple
            required
            @change="selectImages"
          /><span v-if="selectedImages.length"
            ><b>{{ selectedImages.length }} gambar</b> ·
            {{
              (
                selectedImages.reduce((sum, file) => sum + file.size, 0) /
                1024 /
                1024
              ).toFixed(1)
            }}
            MB<br />{{ selectedImages[0]?.name }} →
            {{ selectedImages[selectedImages.length - 1]?.name }}</span
          >
        </div>
        <div v-if="uploadProgress" class="progress">
          <span :style="{ width: `${uploadProgress}%` }"></span
          ><b>{{ uploadStage }} · {{ uploadProgress }}%</b>
        </div>
        <div class="upload-tip">
          <i class="pi pi-info-circle"></i
          ><span
            >Pastikan nama gambar memiliki nomor halaman. Urutan natural
            digunakan sehingga `10.jpg` berada setelah `9.jpg`, bukan setelah
            `1.jpg`.</span
          >
        </div>
        <div class="modal-actions">
          <Button
            type="button"
            label="Batal"
            severity="secondary"
            @click="uploadTask = null"
          /><Button
            type="submit"
            label="Upload gambar & kirim review"
            icon="pi pi-send"
            :loading="loading"
            :disabled="!selectedImages.length"
          />
        </div>
      </form>
    </div>
    <Suspense v-if="activeQcTaskId">
      <QcViewerPage
        :assignment-id="activeQcTaskId"
        @close="activeQcTaskId = null"
        @approved="handleQcApproved"
        @revised="handleQcRevised"
      />
    </Suspense>
  </div>
</template>
