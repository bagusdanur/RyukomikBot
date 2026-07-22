async function request(path, init) {
    const response = await fetch(path, {
        credentials: 'include',
        ...init,
        headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    });
    if (!response.ok) {
        const body = await response.json().catch(() => ({ detail: 'Terjadi kesalahan.' }));
        throw new Error(body.detail || `HTTP ${response.status}`);
    }
    return response.json();
}
const liveApi = {
    me: () => request('/api/me'),
    overview: () => request('/api/overview'),
    assignments: (status = '', search = '') => request(`/api/assignments?status=${encodeURIComponent(status)}&search=${encodeURIComponent(search)}`),
    staff: () => request('/api/staff'),
    payrates: () => request('/api/payrates'),
    updatePayrate: (role, base_rate) => request(`/api/payrates/${encodeURIComponent(role)}`, { method: 'PUT', body: JSON.stringify({ base_rate }) }),
    deadlines: () => request('/api/deadlines'),
    recap: (period) => request(`/api/recap?period=${period}`),
    audit: () => request('/api/audit'),
    logout: () => request('/auth/logout', { method: 'POST' }),
};
const sampleAssignments = [
    { id: 24, manga: 'Let’s Do It After Work', chapter: '12', staff_id: 1001, role: 'TS', final_rate: 12000, status: 'revision', deadline_at: '2026-07-23', assigned_at: '2026-07-21' },
    { id: 23, manga: 'Nano Machine', chapter: '271', staff_id: 1002, role: 'TL', final_rate: 6500, status: 'submitted', deadline_at: '2026-07-24', assigned_at: '2026-07-21' },
    { id: 22, manga: 'Solo Leveling', chapter: '203', staff_id: 1001, role: 'TL+TS', final_rate: 15000, status: 'claimed', deadline_at: '2026-07-25', assigned_at: '2026-07-20' },
    { id: 21, manga: 'Return of Mount Hua', chapter: '145', staff_id: null, role: 'TL', final_rate: 5000, status: 'open', deadline_at: null, assigned_at: '2026-07-20' },
    { id: 20, manga: 'Omniscient Reader', chapter: '198', staff_id: 1003, role: 'TS', final_rate: 10000, status: 'paid', deadline_at: '2026-07-19', assigned_at: '2026-07-17' },
];
const demoApi = {
    me: async () => ({ id: 1, username: 'Kanim', avatar: null, role: 'admin' }),
    overview: async () => ({ counts: { open: 3, claimed: 6, submitted: 2, revision: 1, approved: 8, paid: 32 }, total_value: 584500, urgent_deadlines: 3 }),
    assignments: async (status = '', search = '') => sampleAssignments.filter(item => (!status || item.status === status) && (!search || `${item.manga} ${item.chapter}`.toLowerCase().includes(search.toLowerCase()))),
    staff: async () => [{ staff_id: 1001, task_count: 18, active_count: 2, approved_amount: 46000, paid_amount: 128000 }, { staff_id: 1002, task_count: 12, active_count: 1, approved_amount: 22000, paid_amount: 89000 }, { staff_id: 1003, task_count: 9, active_count: 0, approved_amount: 0, paid_amount: 74000 }],
    payrates: async () => [{ role: 'TL', base_rate: 5000, updated_at: '2026-07-22' }, { role: 'TS', base_rate: 8000, updated_at: '2026-07-22' }, { role: 'TL+TS', base_rate: 12000, updated_at: '2026-07-22' }],
    updatePayrate: async (role, base_rate) => ({ role, base_rate }),
    deadlines: async () => sampleAssignments.filter(item => item.deadline_at && ['claimed', 'revision', 'submitted'].includes(item.status)),
    recap: async () => [{ staff_id: 1001, chapter_count: 6, total_amount: 68000 }, { staff_id: 1002, chapter_count: 4, total_amount: 44000 }],
    audit: async () => [{ id: 1, created_at: '2026-07-22 14:20', actor_id: 1, action: 'payrate.update', target_type: 'payrate', target_id: 'TS' }],
    logout: async () => ({ ok: true }),
};
export const api = import.meta.env.VITE_DEMO_MODE === 'true' ? demoApi : liveApi;
