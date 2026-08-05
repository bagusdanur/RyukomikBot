export type User = {
  id: string;
  username: string;
  avatar: string | null;
  role: "admin";
  csrf_token?: string;
};
export type Assignment = {
  id: number;
  manga: string;
  chapter: string;
  staff_id: string | null;
  role: string;
  final_rate: number;
  rate_per_chapter?: number;
  chapter_count?: number;
  chapters?: string;
  status: string;
  deadline_at: string | null;
  assigned_at: string;
  gdrive_link?: string | null;
  staff_name?: string;
  staff_avatar?: string | null;
};
export type PairChapter = {
  id: number;
  project_id: number;
  chapter: string;
  status: string;
  tl_link: string | null;
  final_link: string | null;
  notes: string | null;
};
export type PairProject = {
  id: number;
  manga: string;
  tl_staff_id: string;
  ts_staff_id: string;
  tl_staff_name: string;
  ts_staff_name: string;
  tl_rate_per_chapter: number;
  ts_rate_per_chapter: number;
  deadline_at: string | null;
  status: string;
  channel_id: string | null;
  chapters: PairChapter[];
};
export type RawRateAnalysis = {
  source: string;
  matched_title: string;
  chapter_count: number;
  page_count: number;
  measured_pages: number;
  max_height: number;
  total_height: number;
  tall_pages: number;
  workload: "Ringan" | "Sedang" | "Berat";
  reason: string;
  rate_per_chapter: number;
  minimum_rate: number;
  maximum_rate: number;
  note: string;
};
export type Staff = {
  id: string;
  staff_id: string;
  username: string;
  avatar: string | null;
  task_count: number;
  active_count: number;
  approved_amount: number;
  paid_amount: number;
};
export type Recap = {
  staff_id: string;
  staff_name: string;
  staff_avatar: string | null;
  chapter_count: number;
  total_amount: number;
  pending_amount: number;
  paid_amount: number;
};
export type RecapSummary = {
  total_earned: number;
  unpaid_amount: number;
  paid_amount: number;
  chapter_count: number;
};
export type Invoice = {
  id: number;
  invoice_number: string;
  staff_id: string;
  staff_name: string;
  staff_avatar: string | null;
  period: string;
  chapter_count: number;
  total_amount: number;
  status: string;
  issued_at: string;
  paid_at: string | null;
  invoice_type?: string;
  parent_invoice_id?: number | null;
  revised_at?: string | null;
};
export type InvoiceDetail = Invoice & {
  work_started_at: string | null;
  work_ended_at: string | null;
  items: Array<{
    assignment_id: number;
    manga: string;
    chapter: string;
    role: string;
    amount: number;
    chapter_count?: number;
    rate_per_chapter?: number;
    assigned_at: string | null;
    approved_at: string | null;
  }>;
};
export type Submission = {
  id: number;
  assignment_id: number;
  staff_id: string;
  original_name: string;
  size_bytes: number;
  uploaded_at: string;
  manga: string;
  chapter: string;
  role: string;
};
export type Payout = {
  id: number;
  staff_id: string;
  staff_name: string;
  staff_avatar: string | null;
  payout_type: "scheduled" | "instant";
  cycle_key: string | null;
  invoice_id: number;
  invoice_number: string;
  chapter_count: number;
  total_amount: number;
  status: string;
  requested_at: string;
  processed_at: string | null;
  rejection_reason: string | null;
  invoice_sent_at?: string | null;
  invoice_message_id?: string | null;
  invoice_send_attempts?: number;
  invoice_send_error?: string | null;
};
export type PayoutDetail = Payout & {
  method: {
    method_type: "bank" | "ewallet" | "qris";
    provider: string;
    account_name: string;
    account_number: string | null;
    qris_object_key: string | null;
  };
  items: InvoiceDetail["items"];
};
export type ActionItem = {
  id: number;
  item_type: "assignment" | "payout";
  action_type: string;
  title: string;
  staff_id: string | null;
  staff_name: string;
  status: string;
  due_at: string | null;
  created_at: string | null;
  priority: number;
};
export type ProjectProgress = {
  manga: string;
  chapter_count: number;
  active_chapters: number;
  review_chapters: number;
  revision_chapters: number;
  completed_chapters: number;
  last_activity: string | null;
};
export type OperationSnapshot = {
  events: Array<Record<string, any>>;
  outbox: Array<Record<string, any>>;
  schedulers: Array<Record<string, any>>;
  backups: Array<Record<string, any>>;
  staff_cache: { count: number; updated_at: string | null; ttl_seconds: number };
};
export type RecruitmentSettings = {
  open: boolean;
  test_material?: {
    url: string;
    tl_example_url: string;
    ts_assets_url: string;
    expires_at: string;
    hours_remaining: number | null;
    status: "active" | "expiring" | "expired" | "unknown";
  };
  positions: Array<{
    position: "TL" | "TS" | "TL+TS";
    enabled: boolean;
    active_count: number;
    updated_at: string | null;
    updated_by: string | null;
  }>;
};
export type RecruitmentSubmission = { id:number; applicant_id:string; applicant_name:string; ticket_name:string; position:string; ticket_channel_id:string; status:string; submitted_at:string };
export type ScoutSource = {
  id: number; source_group: "raw" | "indonesia" | "internal"; source: string;
  source_id: string | null; title: string; cover_url: string | null; synopsis: string;
  genres: string[]; latest_chapter: number | null; chapter_count: number | null;
  match_score: number; detail_url: string | null;
};
export type ScoutTitle = {
  id: number; canonical_title: string; cover_url: string | null; synopsis: string;
  genres: string[]; content_type: string | null; publication_status: string | null;
  scout_status: string; confidence: number; raw_latest_chapter: number | null;
  indonesia_latest_chapter: number | null; chapter_gap: number | null;
  first_seen_at: string; last_scanned_at: string; ignore_reason?: string | null;
  sources?: ScoutSource[]; cached?: boolean;
};
export type Paged<T> = {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
};
export type PerformanceBonus = {
  id: number; staff_id: string; staff_name?: string; staff_avatar?: string | null;
  period: string; approved_chapters: number; eligible_earnings: number;
  revision_chapters: number; deadline_chapters: number; on_time_chapters: number;
  overdue_chapters: number; quality_score: number; speed_score: number | null;
  consistency_score: number; total_score: number; tier: string | null;
  percentage: number; proposed_amount: number;
  status: "ineligible" | "pending" | "approved" | "rejected" | "invoiced" | "paid";
  rejection_reason?: string | null;
  metrics: { no_deadline_redistribution?: boolean; assignments?: Array<Record<string, unknown>> };
};
export type PerformanceBonusSettings = {
  quality_weight: number; speed_weight: number; consistency_weight: number;
  min_chapters: number; tier_1_score: number; tier_1_percent: number;
  tier_2_score: number; tier_2_percent: number; tier_3_score: number;
  tier_3_percent: number; max_amount: number;
};
export type ManualBonus = {
  id: number;
  staff_id: string;
  staff_name?: string;
  staff_avatar?: string | null;
  amount: number;
  reason: string;
  period: string | null;
  status: "approved" | "invoiced" | "paid" | "cancelled";
  created_by: string;
  created_at: string;
};


let csrfToken = "";
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: "Terjadi kesalahan." }));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

const liveApi = {
  me: async () => {
    const user = await request<User>("/api/me");
    csrfToken = user.csrf_token || "";
    return user;
  },
  overview: () =>
    request<{
      counts: Record<string, number>;
      total_value: number;
      urgent_deadlines: number;
      project_progress: ProjectProgress[];
    }>("/api/overview"),
  actionCenter: () => request<ActionItem[]>("/api/action-center"),
  operations: () => request<OperationSnapshot>("/api/operations"),
  resolveOperation: (id: number) =>
    request(`/api/operations/events/${id}/resolve`, { method: "POST" }),
  retryNotification: (id: number) =>
    request(`/api/operations/outbox/${id}/retry`, { method: "POST" }),
  syncStaff: () => request<{ count: number; updated_at: string }>("/api/staff/sync", { method: "POST" }),
  assignments: (status = "", search = "") =>
    request<Assignment[]>(
      `/api/assignments?status=${encodeURIComponent(status)}&search=${encodeURIComponent(search)}`,
    ),
  assignmentsPage: (status = "", search = "", page = 1, pageSize = 20) =>
    request<Paged<Assignment>>(
      `/api/assignments?paginated=true&page=${page}&page_size=${pageSize}&status=${encodeURIComponent(status)}&search=${encodeURIComponent(search)}`,
    ),
  staff: () => request<Staff[]>("/api/staff"),
  createAssignment: (payload: Record<string, unknown>) =>
    request<{ id: number; notified: boolean }>("/api/assignments", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  createTlTsPair: (payload: Record<string, unknown>) =>
    request<{ tl_assignment_id: number; pair_project_id: number; channel_id: string; notified: boolean }>("/api/assignments/tl-ts-pair", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  pairProjects: () => request<PairProject[]>("/api/pair-projects"),
  approvePairChapter: (id: number) =>
    request(`/api/pair-chapters/${id}/approve`, { method: "POST" }),
  revisePairChapter: (id: number, target: "tl" | "ts" | "both", notes: string) =>
    request(`/api/pair-chapters/${id}/revision`, {
      method: "POST", body: JSON.stringify({ target, notes }),
    }),
  updateAssignment: (id: number, payload: Record<string, unknown>) =>
    request<{ ok: boolean; notified: boolean }>(`/api/assignments/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  analyzeRawRate: (manga: string, chapter: string, role: string) =>
    request<RawRateAnalysis>("/api/raw-rate-analysis", {
      method: "POST",
      body: JSON.stringify({ manga, chapter, role }),
    }),
  approveAssignment: (id: number) =>
    request(`/api/assignments/${id}/approve`, { method: "POST" }),
  reviseAssignment: (id: number, notes: string) =>
    request(`/api/assignments/${id}/revision`, {
      method: "POST",
      body: JSON.stringify({ notes }),
    }),
  payrates: () =>
    request<Array<{ role: string; base_rate: number; min_rate: number; max_rate: number; updated_at: string }>>(
      "/api/payrates",
    ),
  updatePayrate: (role: string, min_rate: number, max_rate: number) =>
    request(`/api/payrates/${encodeURIComponent(role)}`, {
      method: "PUT",
      body: JSON.stringify({ min_rate, max_rate }),
    }),
  recruitmentSettings: () =>
    request<RecruitmentSettings>("/api/recruitment/settings"),
  updateRecruitmentSettings: (settings: { tl: boolean; ts: boolean; tl_ts: boolean }) =>
    request<{ ok: boolean; discord_synced: boolean }>("/api/recruitment/settings", {
      method: "PUT",
      body: JSON.stringify(settings),
    }),
  recruitmentSubmissions: () => request<RecruitmentSubmission[]>("/api/recruitment/submissions"),
  closeRecruitmentSubmission: (id:number, reason:string) => request(`/api/recruitment/submissions/${id}/close`, {method:"POST",body:JSON.stringify({reason})}),
  scoutTitles: (status = "", search = "", page = 1, pageSize = 20) =>
    request<Paged<ScoutTitle>>(`/api/scout?status=${encodeURIComponent(status)}&search=${encodeURIComponent(search)}&page=${page}&page_size=${pageSize}`),
  scoutSearch: (title: string, raw_source = "all", force = false) =>
    request<ScoutTitle>("/api/scout/search", { method: "POST", body: JSON.stringify({ title, raw_source, force }) }),
  scoutDetail: (id: number) => request<ScoutTitle>(`/api/scout/${id}`),
  scoutDecision: (id: number, action: string, notes = "") =>
    request<ScoutTitle>(`/api/scout/${id}/decision`, { method: "POST", body: JSON.stringify({ action, notes }) }),
  deadlines: () => request<Assignment[]>("/api/deadlines"),
  recap: (period: string) => request<Recap[]>(`/api/recap?period=${period}`),
  recapSummary: () => request<RecapSummary>("/api/recap-summary"),
  invoices: (period: string) =>
    request<Invoice[]>(`/api/invoices?period=${period}`),
  invoice: (id: number) => request<InvoiceDetail>(`/api/invoices/${id}`),
  createInvoice: (staff_id: string, period: string) =>
    request("/api/invoices", {
      method: "POST",
      body: JSON.stringify({ staff_id, period }),
    }),
  payInvoice: (id: number) =>
    request(`/api/invoices/${id}/pay`, { method: "POST" }),
  deleteInvoice: (id: number) =>
    request(`/api/invoices/${id}`, { method: "DELETE" }),
  refreshInvoice: (id: number) =>
    request(`/api/invoices/${id}/refresh`, { method: "POST" }),
  correctionInvoice: (id: number) =>
    request(`/api/invoices/${id}/correction`, { method: "POST" }),
  payouts: (status = "") =>
    request<Payout[]>(`/api/payouts${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  payoutsPage: (status = "", page = 1, pageSize = 20) =>
    request<Paged<Payout>>(
      `/api/payouts?paginated=true&page=${page}&page_size=${pageSize}${status ? `&status=${encodeURIComponent(status)}` : ""}`,
    ),
  payout: (id: number) => request<PayoutDetail>(`/api/payouts/${id}`),
  payoutQris: (id: number) =>
    request<{ download_url: string; expires_in: number }>(`/api/payouts/${id}/qris`),
  payoutPdfUrl: (id: number) => `/api/payouts/${id}/pdf`,
  resendPayoutInvoice: (id: number) =>
    request(`/api/payouts/${id}/resend-invoice`, { method: "POST" }),
  payPayout: (id: number, amount: number, destination_last4: string) =>
    request(`/api/payouts/${id}/pay`, {
      method: "POST",
      body: JSON.stringify({ amount, destination_last4 }),
    }),
  rejectPayout: (id: number, reason: string) =>
    request(`/api/payouts/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  performanceBonuses: (period = "", status = "") =>
    request<PerformanceBonus[]>(`/api/performance-bonuses?period=${encodeURIComponent(period)}&status=${encodeURIComponent(status)}`),
  performanceBonusSettings: () => request<PerformanceBonusSettings>("/api/performance-bonuses/settings"),
  runPerformanceBonuses: (period: string) => request<{ count: number; period: string }>("/api/performance-bonuses/run", {
    method: "POST", body: JSON.stringify({ period }),
  }),
  updatePerformanceBonusSettings: (payload: PerformanceBonusSettings) =>
    request<PerformanceBonusSettings>("/api/performance-bonuses/settings", { method: "PUT", body: JSON.stringify(payload) }),
  approvePerformanceBonus: (id: number) => request(`/api/performance-bonuses/${id}/approve`, { method: "POST" }),
  rejectPerformanceBonus: (id: number, reason: string) => request(`/api/performance-bonuses/${id}/reject`, {
    method: "POST", body: JSON.stringify({ reason }),
  }),
  manualBonuses: (staffId = "", period = "", status = "") =>
    request<ManualBonus[]>(`/api/manual-bonuses?staff_id=${encodeURIComponent(staffId)}&period=${encodeURIComponent(period)}&status=${encodeURIComponent(status)}`),
  createManualBonus: (payload: { staff_id: string; amount: number; reason: string; period?: string }) =>
    request<ManualBonus>("/api/manual-bonuses", { method: "POST", body: JSON.stringify(payload) }),
  cancelManualBonus: (id: number) =>
    request<ManualBonus>(`/api/manual-bonuses/${id}/cancel`, { method: "POST" }),

  submissions: (assignmentId?: number) =>
    request<Submission[]>(
      `/api/submissions${assignmentId ? `?assignment_id=${assignmentId}` : ""}`,
    ),
  downloadSubmission: (id: number) =>
    request<{ download_url: string }>(`/api/submissions/${id}/download`),
  audit: () =>
    request<Array<Record<string, string | number | null>>>("/api/audit"),
  auditPage: (page = 1, pageSize = 20) =>
    request<Paged<Record<string, string | number | null>>>(
      `/api/audit?paginated=true&page=${page}&page_size=${pageSize}`,
    ),
  logout: () => request("/auth/logout", { method: "POST" }),
};

const sampleAssignments: Assignment[] = [
  {
    id: 24,
    manga: "Let’s Do It After Work",
    chapter: "12",
    staff_id: "1001",
    role: "TS",
    final_rate: 12000,
    status: "revision",
    deadline_at: "2026-07-23",
    assigned_at: "2026-07-21",
  },
  {
    id: 23,
    manga: "Nano Machine",
    chapter: "271",
    staff_id: "1002",
    role: "TL",
    final_rate: 6500,
    status: "submitted",
    deadline_at: "2026-07-24",
    assigned_at: "2026-07-21",
  },
  {
    id: 22,
    manga: "Solo Leveling",
    chapter: "203",
    staff_id: "1001",
    role: "TL+TS",
    final_rate: 15000,
    status: "claimed",
    deadline_at: "2026-07-25",
    assigned_at: "2026-07-20",
  },
  {
    id: 21,
    manga: "Return of Mount Hua",
    chapter: "145",
    staff_id: null,
    role: "TL",
    final_rate: 5000,
    status: "open",
    deadline_at: null,
    assigned_at: "2026-07-20",
  },
  {
    id: 20,
    manga: "Omniscient Reader",
    chapter: "198",
    staff_id: "1003",
    role: "TS",
    final_rate: 10000,
    status: "paid",
    deadline_at: "2026-07-19",
    assigned_at: "2026-07-17",
  },
];

const demoApi = {
  me: async () => ({
    id: "1",
    username: "Kanim",
    avatar: null,
    role: "admin" as const,
  }),
  overview: async () => ({
    counts: {
      open: 3,
      claimed: 6,
      submitted: 2,
      revision: 1,
      approved: 8,
      paid: 32,
    },
    total_value: 584500,
    urgent_deadlines: 3,
    project_progress: [
      { manga: "Contoh Project", chapter_count: 8, active_chapters: 3, review_chapters: 1, revision_chapters: 0, completed_chapters: 4, last_activity: null },
    ] as ProjectProgress[],
  }),
  actionCenter: async () => [] as ActionItem[],
  operations: async () => ({
    events: [], outbox: [], schedulers: [], backups: [],
    staff_cache: { count: 3, updated_at: new Date().toISOString(), ttl_seconds: 600 },
  }),
  resolveOperation: async () => ({ ok: true }),
  retryNotification: async () => ({ ok: true }),
  syncStaff: async () => ({ count: 3, updated_at: new Date().toISOString() }),
  assignments: async (status = "", search = "") =>
    sampleAssignments.filter(
      (item) =>
        (!status || item.status === status) &&
        (!search ||
          `${item.manga} ${item.chapter}`
            .toLowerCase()
            .includes(search.toLowerCase())),
    ),
  assignmentsPage: async (status = "", search = "", page = 1, pageSize = 20) => {
    const items = await demoApi.assignments(status, search);
    return { items: items.slice((page - 1) * pageSize, page * pageSize), page, page_size: pageSize, total: items.length, total_pages: Math.max(1, Math.ceil(items.length / pageSize)) };
  },
  staff: async () => [
    {
      id: "1001",
      staff_id: "1001",
      username: "Aira",
      avatar: null,
      task_count: 18,
      active_count: 2,
      approved_amount: 46000,
      paid_amount: 128000,
    },
    {
      id: "1002",
      staff_id: "1002",
      username: "Ren",
      avatar: null,
      task_count: 12,
      active_count: 1,
      approved_amount: 22000,
      paid_amount: 89000,
    },
  ],
  createAssignment: async () => ({ id: 25, notified: true }),
  createTlTsPair: async () => ({ tl_assignment_id: 26, pair_project_id: 1, channel_id: "123", notified: true }),
  pairProjects: async (): Promise<PairProject[]> => [],
  approvePairChapter: async () => ({ ok: true }),
  revisePairChapter: async () => ({ ok: true }),
  updateAssignment: async () => ({ ok: true, notified: true }),
  analyzeRawRate: async (): Promise<RawRateAnalysis> => ({
    source: "asura", matched_title: "Contoh Manga", chapter_count: 1,
    page_count: 18, measured_pages: 18, max_height: 6200, total_height: 106000,
    tall_pages: 0, workload: "Sedang", reason: "18 halaman, tinggi maks. 6,200 px",
    rate_per_chapter: 6000, minimum_rate: 4000, maximum_rate: 8000,
    note: "Rekomendasi dapat diubah administrator sebelum tugas dikirim.",
  }),
  approveAssignment: async () => ({ ok: true }),
  reviseAssignment: async () => ({ ok: true }),
  payrates: async () => [
    { role: "TL", base_rate: 4000, min_rate: 4000, max_rate: 8000, updated_at: "2026-07-22" },
    { role: "TS", base_rate: 5000, min_rate: 5000, max_rate: 10000, updated_at: "2026-07-22" },
    { role: "TL+TS", base_rate: 9000, min_rate: 9000, max_rate: 18000, updated_at: "2026-07-22" },
  ],
  updatePayrate: async (role: string, min_rate: number, max_rate: number) => ({
    role,
    base_rate: min_rate,
    min_rate,
    max_rate,
    notified: 2,
  }),
  recruitmentSettings: async (): Promise<RecruitmentSettings> => ({
    open: true,
    test_material: {
      url: "https://filebin.net/foqyxmztslglks1h",
      tl_example_url: "https://drive.google.com/drive/folders/1QxunNgc8gQldtOmuDeIB7GPLfIOIa8fi",
      ts_assets_url: "https://drive.google.com/drive/folders/1SDLA-6M42CUfkeqSaXOF1KibE_0y9PfO?usp=sharing",
      expires_at: "2026-08-12T11:04:50+00:00",
      hours_remaining: 144,
      status: "active",
    },
    positions: [
      { position: "TL", enabled: true, active_count: 1, updated_at: "2026-07-26", updated_by: "1" },
      { position: "TS", enabled: true, active_count: 0, updated_at: "2026-07-26", updated_by: "1" },
      { position: "TL+TS", enabled: true, active_count: 0, updated_at: "2026-07-26", updated_by: "1" },
    ],
  }),
  updateRecruitmentSettings: async () => ({ ok: true, discord_synced: true }),
  recruitmentSubmissions: async () => [] as RecruitmentSubmission[],
  closeRecruitmentSubmission: async () => ({ ok: true }),
  scoutTitles: async (_status = "", _search = "", page = 1, pageSize = 20): Promise<Paged<ScoutTitle>> => ({
    items: [], page, page_size: pageSize, total: 0, total_pages: 1,
  }),
  scoutSearch: async (title: string): Promise<ScoutTitle> => ({
    id: 1, canonical_title: title, cover_url: null, synopsis: "", genres: [], content_type: null,
    publication_status: "Ongoing", scout_status: "untranslated", confidence: 0,
    raw_latest_chapter: 5, indonesia_latest_chapter: null, chapter_gap: null,
    first_seen_at: new Date().toISOString(), last_scanned_at: new Date().toISOString(), sources: [],
  }),
  scoutDetail: async (id: number): Promise<ScoutTitle> => ({
    ...(await demoApi.scoutSearch("Contoh Project")), id,
  }),
  scoutDecision: async (id: number, action: string): Promise<ScoutTitle> => ({
    ...(await demoApi.scoutDetail(id)), scout_status: action === "adopt" ? "adopted" : action,
  }),
  deadlines: async () =>
    sampleAssignments.filter(
      (item) =>
        item.deadline_at &&
        ["claimed", "revision", "submitted"].includes(item.status),
    ),
  recap: async () => [
    {
      staff_id: "1001",
      staff_name: "Aira",
      staff_avatar: null,
      chapter_count: 6,
      total_amount: 68000,
      pending_amount: 18000,
      paid_amount: 50000,
    },
  ],
  recapSummary: async (): Promise<RecapSummary> => ({
    total_earned: 168000,
    unpaid_amount: 18000,
    paid_amount: 150000,
    chapter_count: 14,
  }),
  invoices: async (): Promise<Invoice[]> => [
    {
      id: 1,
      invoice_number: "RYU-202607-1001-A1B2",
      staff_id: "1001",
      staff_name: "Aira",
      staff_avatar: null,
      period: "2026-07",
      chapter_count: 6,
      total_amount: 68000,
      status: "issued",
      issued_at: "2026-07-22",
      paid_at: null,
    },
  ],
  invoice: async (id: number): Promise<InvoiceDetail> => ({
    id,
    invoice_number: "RYU-202607-1001-A1B2",
    staff_id: "1001",
    staff_name: "Aira",
    staff_avatar: null,
    period: "2026-07",
    chapter_count: 2,
    total_amount: 18000,
    status: "issued",
    issued_at: "2026-07-22",
    paid_at: null,
    work_started_at: "2026-07-01",
    work_ended_at: "2026-07-20",
    items: [
      {
        assignment_id: 1,
        manga: "Contoh Manga",
        chapter: "1",
        role: "TL",
        amount: 6000,
        assigned_at: "2026-07-01",
        approved_at: "2026-07-03",
      },
    ],
  }),
  createInvoice: async () => ({ id: 2 }),
  payInvoice: async () => ({ ok: true }),
  deleteInvoice: async () => ({ ok: true }),
  refreshInvoice: async () => ({ ok: true }),
  correctionInvoice: async () => ({ id: 2 }),
  payouts: async () => [] as Payout[],
  payoutsPage: async (_status = "", page = 1, pageSize = 20) => ({
    items: [] as Payout[], page, page_size: pageSize, total: 0, total_pages: 1,
  }),
  payout: async (id: number) => ({
    id, staff_id: "1001", staff_name: "Aira", staff_avatar: null,
    payout_type: "instant" as const, cycle_key: null, invoice_id: 1,
    invoice_number: "RYU-DEMO", chapter_count: 2, total_amount: 18000,
    status: "issued", requested_at: "2026-07-23", processed_at: null,
    rejection_reason: null,
    method: { method_type: "bank" as const, provider: "BCA", account_name: "Aira", account_number: "1234567890", qris_object_key: null },
    items: [],
  }),
  payoutQris: async () => ({ download_url: "#", expires_in: 600 }),
  payoutPdfUrl: () => "#",
  resendPayoutInvoice: async () => ({ ok: true }),
  payPayout: async () => ({ ok: true }),
  rejectPayout: async () => ({ ok: true }),
  performanceBonuses: async () => [] as PerformanceBonus[],
  performanceBonusSettings: async (): Promise<PerformanceBonusSettings> => ({
    quality_weight: 50, speed_weight: 30, consistency_weight: 20, min_chapters: 3,
    tier_1_score: 70, tier_1_percent: 4, tier_2_score: 80, tier_2_percent: 6,
    tier_3_score: 90, tier_3_percent: 10, max_amount: 25000,
  }),
  runPerformanceBonuses: async (period: string) => ({ count: 0, period }),
  updatePerformanceBonusSettings: async (payload: PerformanceBonusSettings) => payload,
  approvePerformanceBonus: async () => ({ ok: true }),
  rejectPerformanceBonus: async () => ({ ok: true }),
  manualBonuses: async () => [] as ManualBonus[],
  createManualBonus: async (payload: { staff_id: string; amount: number; reason: string; period?: string }): Promise<ManualBonus> => ({
    id: 1, staff_id: payload.staff_id, amount: payload.amount, reason: payload.reason, period: payload.period || null,
    status: "approved", created_by: "1", created_at: new Date().toISOString()
  }),
  cancelManualBonus: async (id: number) => ({ id } as ManualBonus),

  submissions: async () => [],
  downloadSubmission: async () => ({ download_url: "#" }),
  audit: async () => [
    {
      id: 1,
      created_at: "2026-07-22 14:20",
      actor_id: 1,
      action: "payrate.update",
      target_type: "payrate",
      target_id: "TS",
    },
  ],
  auditPage: async (page = 1, pageSize = 20) => ({
    items: await demoApi.audit(), page, page_size: pageSize, total: 1, total_pages: 1,
  }),
  logout: async () => ({ ok: true }),
};

export const api =
  import.meta.env.VITE_DEMO_MODE === "true" ? demoApi : liveApi;
