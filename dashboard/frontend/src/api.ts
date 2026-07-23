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
    }>("/api/overview"),
  assignments: (status = "", search = "") =>
    request<Assignment[]>(
      `/api/assignments?status=${encodeURIComponent(status)}&search=${encodeURIComponent(search)}`,
    ),
  staff: () => request<Staff[]>("/api/staff"),
  createAssignment: (payload: Record<string, unknown>) =>
    request<{ id: number; notified: boolean }>("/api/assignments", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  approveAssignment: (id: number) =>
    request(`/api/assignments/${id}/approve`, { method: "POST" }),
  reviseAssignment: (id: number, notes: string) =>
    request(`/api/assignments/${id}/revision`, {
      method: "POST",
      body: JSON.stringify({ notes }),
    }),
  payrates: () =>
    request<Array<{ role: string; base_rate: number; updated_at: string }>>(
      "/api/payrates",
    ),
  updatePayrate: (role: string, base_rate: number) =>
    request(`/api/payrates/${encodeURIComponent(role)}`, {
      method: "PUT",
      body: JSON.stringify({ base_rate }),
    }),
  deadlines: () => request<Assignment[]>("/api/deadlines"),
  recap: (period: string) => request<Recap[]>(`/api/recap?period=${period}`),
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
  payout: (id: number) => request<PayoutDetail>(`/api/payouts/${id}`),
  payoutQris: (id: number) =>
    request<{ download_url: string; expires_in: number }>(`/api/payouts/${id}/qris`),
  payPayout: (id: number) => request(`/api/payouts/${id}/pay`, { method: "POST" }),
  rejectPayout: (id: number, reason: string) =>
    request(`/api/payouts/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  submissions: (assignmentId?: number) =>
    request<Submission[]>(
      `/api/submissions${assignmentId ? `?assignment_id=${assignmentId}` : ""}`,
    ),
  downloadSubmission: (id: number) =>
    request<{ download_url: string }>(`/api/submissions/${id}/download`),
  audit: () =>
    request<Array<Record<string, string | number | null>>>("/api/audit"),
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
  }),
  assignments: async (status = "", search = "") =>
    sampleAssignments.filter(
      (item) =>
        (!status || item.status === status) &&
        (!search ||
          `${item.manga} ${item.chapter}`
            .toLowerCase()
            .includes(search.toLowerCase())),
    ),
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
  approveAssignment: async () => ({ ok: true }),
  reviseAssignment: async () => ({ ok: true }),
  payrates: async () => [
    { role: "TL", base_rate: 5000, updated_at: "2026-07-22" },
    { role: "TS", base_rate: 8000, updated_at: "2026-07-22" },
    { role: "TL+TS", base_rate: 12000, updated_at: "2026-07-22" },
  ],
  updatePayrate: async (role: string, base_rate: number) => ({
    role,
    base_rate,
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
  invoices: async () => [
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
  invoice: async (id: number) => ({
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
  payPayout: async () => ({ ok: true }),
  rejectPayout: async () => ({ ok: true }),
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
  logout: async () => ({ ok: true }),
};

export const api =
  import.meta.env.VITE_DEMO_MODE === "true" ? demoApi : liveApi;
