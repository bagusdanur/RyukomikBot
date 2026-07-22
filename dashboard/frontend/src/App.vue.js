import { computed, onMounted, ref, watch } from 'vue';
import Button from 'primevue/button';
import Column from 'primevue/column';
import DataTable from 'primevue/datatable';
import InputNumber from 'primevue/inputnumber';
import InputText from 'primevue/inputtext';
import Select from 'primevue/select';
import Tag from 'primevue/tag';
import { api } from './api';
const user = ref(null);
const authChecked = ref(false);
const loading = ref(false);
const error = ref('');
const page = ref('overview');
const overview = ref({ counts: {}, total_value: 0, urgent_deadlines: 0 });
const assignments = ref([]);
const staff = ref([]);
const payrates = ref([]);
const deadlines = ref([]);
const recap = ref([]);
const audit = ref([]);
const search = ref('');
const status = ref('');
const period = ref(new Date().toISOString().slice(0, 7));
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
]);
const money = (value) => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(value || 0);
const statusLabel = { open: 'Tersedia', claimed: 'Dikerjakan', submitted: 'Menunggu Review', revision: 'Perlu Revisi', approved: 'Disetujui', paid: 'Dibayar' };
const severity = (value) => ({ open: 'info', claimed: 'warn', submitted: 'secondary', revision: 'danger', approved: 'success', paid: 'contrast' }[value] || 'secondary');
async function run(operation, target) {
    loading.value = true;
    error.value = '';
    try {
        target.value = await operation();
    }
    catch (e) {
        error.value = e instanceof Error ? e.message : 'Terjadi kesalahan.';
    }
    finally {
        loading.value = false;
    }
}
async function loadPage() {
    if (!user.value)
        return;
    if (page.value === 'overview')
        await run(api.overview, overview);
    if (page.value === 'tasks')
        await run(() => api.assignments(status.value, search.value), assignments);
    if (page.value === 'staff')
        await run(api.staff, staff);
    if (page.value === 'payrates')
        await run(api.payrates, payrates);
    if (page.value === 'deadlines')
        await run(api.deadlines, deadlines);
    if (page.value === 'recap')
        await run(() => api.recap(period.value), recap);
    if (page.value === 'audit')
        await run(api.audit, audit);
}
async function saveRate(item) {
    loading.value = true;
    error.value = '';
    try {
        await api.updatePayrate(item.role, item.base_rate);
        await loadPage();
    }
    catch (e) {
        error.value = e instanceof Error ? e.message : 'Gagal menyimpan payrate.';
    }
    finally {
        loading.value = false;
    }
}
async function logout() { await api.logout(); user.value = null; }
watch(page, loadPage);
watch(status, () => page.value === 'tasks' && loadPage());
onMounted(async () => {
    try {
        user.value = await api.me();
        await loadPage();
    }
    catch {
        user.value = null;
    }
    finally {
        authChecked.value = true;
    }
});
const __VLS_ctx = {
    ...{},
    ...{},
};
let __VLS_components;
let __VLS_intrinsics;
let __VLS_directives;
if (!__VLS_ctx.authChecked) {
    __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
        ...{ class: "center-screen" },
    });
    /** @type {__VLS_StyleScopedClasses['center-screen']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
        ...{ class: "pi pi-spin pi-spinner" },
    });
    /** @type {__VLS_StyleScopedClasses['pi']} */ ;
    /** @type {__VLS_StyleScopedClasses['pi-spin']} */ ;
    /** @type {__VLS_StyleScopedClasses['pi-spinner']} */ ;
}
else if (!__VLS_ctx.user) {
    __VLS_asFunctionalElement1(__VLS_intrinsics.main, __VLS_intrinsics.main)({
        ...{ class: "login-page" },
    });
    /** @type {__VLS_StyleScopedClasses['login-page']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.section, __VLS_intrinsics.section)({
        ...{ class: "login-card" },
    });
    /** @type {__VLS_StyleScopedClasses['login-card']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
        ...{ class: "brand-mark" },
    });
    /** @type {__VLS_StyleScopedClasses['brand-mark']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.p, __VLS_intrinsics.p)({
        ...{ class: "eyebrow" },
    });
    /** @type {__VLS_StyleScopedClasses['eyebrow']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.h1, __VLS_intrinsics.h1)({});
    __VLS_asFunctionalElement1(__VLS_intrinsics.br)({});
    __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({});
    __VLS_asFunctionalElement1(__VLS_intrinsics.p, __VLS_intrinsics.p)({
        ...{ class: "login-copy" },
    });
    /** @type {__VLS_StyleScopedClasses['login-copy']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.a, __VLS_intrinsics.a)({
        ...{ class: "discord-login" },
        href: "/auth/login",
    });
    /** @type {__VLS_StyleScopedClasses['discord-login']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
        ...{ class: "pi pi-discord" },
    });
    /** @type {__VLS_StyleScopedClasses['pi']} */ ;
    /** @type {__VLS_StyleScopedClasses['pi-discord']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.p, __VLS_intrinsics.p)({
        ...{ class: "security-note" },
    });
    /** @type {__VLS_StyleScopedClasses['security-note']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
        ...{ class: "pi pi-lock" },
    });
    /** @type {__VLS_StyleScopedClasses['pi']} */ ;
    /** @type {__VLS_StyleScopedClasses['pi-lock']} */ ;
}
else {
    __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
        ...{ class: "app-shell app-dark" },
    });
    /** @type {__VLS_StyleScopedClasses['app-shell']} */ ;
    /** @type {__VLS_StyleScopedClasses['app-dark']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.aside, __VLS_intrinsics.aside)({
        ...{ class: "sidebar" },
    });
    /** @type {__VLS_StyleScopedClasses['sidebar']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
        ...{ class: "brand" },
    });
    /** @type {__VLS_StyleScopedClasses['brand']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
        ...{ class: "brand-mark small" },
    });
    /** @type {__VLS_StyleScopedClasses['brand-mark']} */ ;
    /** @type {__VLS_StyleScopedClasses['small']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({});
    __VLS_asFunctionalElement1(__VLS_intrinsics.strong, __VLS_intrinsics.strong)({});
    __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({});
    __VLS_asFunctionalElement1(__VLS_intrinsics.nav, __VLS_intrinsics.nav)({});
    for (const [item] of __VLS_vFor((__VLS_ctx.navItems))) {
        __VLS_asFunctionalElement1(__VLS_intrinsics.button, __VLS_intrinsics.button)({
            ...{ onClick: (...[$event]) => {
                    if (!!(!__VLS_ctx.authChecked))
                        throw 0;
                    if (!!(!__VLS_ctx.user))
                        throw 0;
                    return (__VLS_ctx.page = item.id);
                    // @ts-ignore
                    [authChecked, user, navItems, page,];
                } },
            key: (item.id),
            ...{ class: ({ active: __VLS_ctx.page === item.id }) },
        });
        /** @type {__VLS_StyleScopedClasses['active']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
            ...{ class: (item.icon) },
        });
        __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({});
        (item.label);
        // @ts-ignore
        [page,];
    }
    __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
        ...{ class: "profile" },
    });
    /** @type {__VLS_StyleScopedClasses['profile']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
        ...{ class: "avatar" },
    });
    /** @type {__VLS_StyleScopedClasses['avatar']} */ ;
    (__VLS_ctx.user.username.slice(0, 1).toUpperCase());
    __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({});
    __VLS_asFunctionalElement1(__VLS_intrinsics.strong, __VLS_intrinsics.strong)({});
    (__VLS_ctx.user.username);
    __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({});
    (__VLS_ctx.user.role === 'admin' ? 'Administrator' : 'Staff');
    __VLS_asFunctionalElement1(__VLS_intrinsics.button, __VLS_intrinsics.button)({
        ...{ onClick: (__VLS_ctx.logout) },
        title: "Keluar",
    });
    __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
        ...{ class: "pi pi-sign-out" },
    });
    /** @type {__VLS_StyleScopedClasses['pi']} */ ;
    /** @type {__VLS_StyleScopedClasses['pi-sign-out']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.section, __VLS_intrinsics.section)({
        ...{ class: "content" },
    });
    /** @type {__VLS_StyleScopedClasses['content']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.header, __VLS_intrinsics.header)({});
    __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({});
    __VLS_asFunctionalElement1(__VLS_intrinsics.p, __VLS_intrinsics.p)({
        ...{ class: "eyebrow" },
    });
    /** @type {__VLS_StyleScopedClasses['eyebrow']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.h2, __VLS_intrinsics.h2)({});
    (__VLS_ctx.navItems.find(i => i.id === __VLS_ctx.page)?.label);
    __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
        ...{ class: "live" },
    });
    /** @type {__VLS_StyleScopedClasses['live']} */ ;
    __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({});
    if (__VLS_ctx.error) {
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "error-banner" },
        });
        /** @type {__VLS_StyleScopedClasses['error-banner']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
            ...{ class: "pi pi-exclamation-circle" },
        });
        /** @type {__VLS_StyleScopedClasses['pi']} */ ;
        /** @type {__VLS_StyleScopedClasses['pi-exclamation-circle']} */ ;
        (__VLS_ctx.error);
        __VLS_asFunctionalElement1(__VLS_intrinsics.button, __VLS_intrinsics.button)({
            ...{ onClick: (...[$event]) => {
                    if (!!(!__VLS_ctx.authChecked))
                        throw 0;
                    if (!!(!__VLS_ctx.user))
                        throw 0;
                    if (!(__VLS_ctx.error))
                        throw 0;
                    return (__VLS_ctx.error = '');
                    // @ts-ignore
                    [user, user, user, navItems, page, logout, error, error, error,];
                } },
        });
    }
    if (__VLS_ctx.page === 'overview') {
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "hero-card" },
        });
        /** @type {__VLS_StyleScopedClasses['hero-card']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.p, __VLS_intrinsics.p)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.h3, __VLS_intrinsics.h3)({});
        (__VLS_ctx.user.username);
        __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({});
        (__VLS_ctx.user.role === 'admin' ? 'Pantau operasi tim dan selesaikan pekerjaan yang membutuhkan perhatian.' : 'Lihat tindakan berikutnya dan progres pekerjaanmu.');
        __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
            ...{ class: "pi pi-sparkles" },
        });
        /** @type {__VLS_StyleScopedClasses['pi']} */ ;
        /** @type {__VLS_StyleScopedClasses['pi-sparkles']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "stats-grid" },
        });
        /** @type {__VLS_StyleScopedClasses['stats-grid']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.article, __VLS_intrinsics.article)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({
            ...{ class: "stat-icon blue" },
        });
        /** @type {__VLS_StyleScopedClasses['stat-icon']} */ ;
        /** @type {__VLS_StyleScopedClasses['blue']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
            ...{ class: "pi pi-inbox" },
        });
        /** @type {__VLS_StyleScopedClasses['pi']} */ ;
        /** @type {__VLS_StyleScopedClasses['pi-inbox']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.small, __VLS_intrinsics.small)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.strong, __VLS_intrinsics.strong)({});
        (__VLS_ctx.overview.counts.open || 0);
        __VLS_asFunctionalElement1(__VLS_intrinsics.article, __VLS_intrinsics.article)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({
            ...{ class: "stat-icon amber" },
        });
        /** @type {__VLS_StyleScopedClasses['stat-icon']} */ ;
        /** @type {__VLS_StyleScopedClasses['amber']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
            ...{ class: "pi pi-hourglass" },
        });
        /** @type {__VLS_StyleScopedClasses['pi']} */ ;
        /** @type {__VLS_StyleScopedClasses['pi-hourglass']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.small, __VLS_intrinsics.small)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.strong, __VLS_intrinsics.strong)({});
        (__VLS_ctx.overview.counts.claimed || 0);
        __VLS_asFunctionalElement1(__VLS_intrinsics.article, __VLS_intrinsics.article)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({
            ...{ class: "stat-icon violet" },
        });
        /** @type {__VLS_StyleScopedClasses['stat-icon']} */ ;
        /** @type {__VLS_StyleScopedClasses['violet']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
            ...{ class: "pi pi-eye" },
        });
        /** @type {__VLS_StyleScopedClasses['pi']} */ ;
        /** @type {__VLS_StyleScopedClasses['pi-eye']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.small, __VLS_intrinsics.small)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.strong, __VLS_intrinsics.strong)({});
        (__VLS_ctx.overview.counts.submitted || 0);
        __VLS_asFunctionalElement1(__VLS_intrinsics.article, __VLS_intrinsics.article)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({
            ...{ class: "stat-icon red" },
        });
        /** @type {__VLS_StyleScopedClasses['stat-icon']} */ ;
        /** @type {__VLS_StyleScopedClasses['red']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
            ...{ class: "pi pi-clock" },
        });
        /** @type {__VLS_StyleScopedClasses['pi']} */ ;
        /** @type {__VLS_StyleScopedClasses['pi-clock']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.small, __VLS_intrinsics.small)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.strong, __VLS_intrinsics.strong)({});
        (__VLS_ctx.overview.urgent_deadlines);
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "summary-grid" },
        });
        /** @type {__VLS_StyleScopedClasses['summary-grid']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.article, __VLS_intrinsics.article)({
            ...{ class: "panel" },
        });
        /** @type {__VLS_StyleScopedClasses['panel']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.p, __VLS_intrinsics.p)({
            ...{ class: "eyebrow" },
        });
        /** @type {__VLS_StyleScopedClasses['eyebrow']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.h3, __VLS_intrinsics.h3)({});
        (__VLS_ctx.money(__VLS_ctx.overview.total_value));
        __VLS_asFunctionalElement1(__VLS_intrinsics.p, __VLS_intrinsics.p)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.article, __VLS_intrinsics.article)({
            ...{ class: "panel next" },
        });
        /** @type {__VLS_StyleScopedClasses['panel']} */ ;
        /** @type {__VLS_StyleScopedClasses['next']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.p, __VLS_intrinsics.p)({
            ...{ class: "eyebrow" },
        });
        /** @type {__VLS_StyleScopedClasses['eyebrow']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.h3, __VLS_intrinsics.h3)({});
        (__VLS_ctx.overview.counts.revision ? 'Ada revisi yang perlu diselesaikan' : __VLS_ctx.overview.counts.submitted ? 'Hasil sedang menunggu review' : 'Alur kerja dalam kondisi baik');
        let __VLS_0;
        /** @ts-ignore @type { | typeof __VLS_components.Button} */
        Button;
        // @ts-ignore
        const __VLS_1 = __VLS_asFunctionalComponent1(__VLS_0, new __VLS_0({
            ...{ 'onClick': {} },
            label: "Buka daftar tugas",
            icon: "pi pi-arrow-right",
            iconPos: "right",
        }));
        const __VLS_2 = __VLS_1({
            ...{ 'onClick': {} },
            label: "Buka daftar tugas",
            icon: "pi pi-arrow-right",
            iconPos: "right",
        }, ...__VLS_functionalComponentArgsRest(__VLS_1));
        let __VLS_5;
        const __VLS_6 = {
            /** @type {typeof __VLS_5.click} */
            onClick: (...[$event]) => {
                if (!!(!__VLS_ctx.authChecked))
                    throw 0;
                if (!!(!__VLS_ctx.user))
                    throw 0;
                if (!(__VLS_ctx.page === 'overview'))
                    throw 0;
                return (__VLS_ctx.page = 'tasks');
                // @ts-ignore
                [user, user, page, page, overview, overview, overview, overview, overview, overview, overview, money,];
            },
        };
        var __VLS_3;
        var __VLS_4;
    }
    if (__VLS_ctx.page === 'tasks') {
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "toolbar" },
        });
        /** @type {__VLS_StyleScopedClasses['toolbar']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({
            ...{ class: "search" },
        });
        /** @type {__VLS_StyleScopedClasses['search']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.i, __VLS_intrinsics.i)({
            ...{ class: "pi pi-search" },
        });
        /** @type {__VLS_StyleScopedClasses['pi']} */ ;
        /** @type {__VLS_StyleScopedClasses['pi-search']} */ ;
        let __VLS_7;
        /** @ts-ignore @type { | typeof __VLS_components.InputText} */
        InputText;
        // @ts-ignore
        const __VLS_8 = __VLS_asFunctionalComponent1(__VLS_7, new __VLS_7({
            ...{ 'onKeyup': {} },
            modelValue: (__VLS_ctx.search),
            placeholder: "Cari manga atau chapter",
        }));
        const __VLS_9 = __VLS_8({
            ...{ 'onKeyup': {} },
            modelValue: (__VLS_ctx.search),
            placeholder: "Cari manga atau chapter",
        }, ...__VLS_functionalComponentArgsRest(__VLS_8));
        let __VLS_12;
        const __VLS_13 = {
            /** @type {typeof __VLS_12.keyup} */
            onKeyup: (__VLS_ctx.loadPage),
        };
        var __VLS_10;
        var __VLS_11;
        let __VLS_14;
        /** @ts-ignore @type { | typeof __VLS_components.Select} */
        Select;
        // @ts-ignore
        const __VLS_15 = __VLS_asFunctionalComponent1(__VLS_14, new __VLS_14({
            modelValue: (__VLS_ctx.status),
            options: (['', 'open', 'claimed', 'submitted', 'revision', 'approved', 'paid']),
            placeholder: "Semua status",
        }));
        const __VLS_16 = __VLS_15({
            modelValue: (__VLS_ctx.status),
            options: (['', 'open', 'claimed', 'submitted', 'revision', 'approved', 'paid']),
            placeholder: "Semua status",
        }, ...__VLS_functionalComponentArgsRest(__VLS_15));
        let __VLS_19;
        /** @ts-ignore @type { | typeof __VLS_components.Button} */
        Button;
        // @ts-ignore
        const __VLS_20 = __VLS_asFunctionalComponent1(__VLS_19, new __VLS_19({
            ...{ 'onClick': {} },
            label: "Cari",
            icon: "pi pi-search",
        }));
        const __VLS_21 = __VLS_20({
            ...{ 'onClick': {} },
            label: "Cari",
            icon: "pi pi-search",
        }, ...__VLS_functionalComponentArgsRest(__VLS_20));
        let __VLS_24;
        const __VLS_25 = {
            /** @type {typeof __VLS_24.click} */
            onClick: (__VLS_ctx.loadPage),
        };
        var __VLS_22;
        var __VLS_23;
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "table-card" },
        });
        /** @type {__VLS_StyleScopedClasses['table-card']} */ ;
        let __VLS_26;
        /** @ts-ignore @type { | typeof __VLS_components.DataTable | typeof __VLS_components.DataTable} */
        DataTable;
        // @ts-ignore
        const __VLS_27 = __VLS_asFunctionalComponent1(__VLS_26, new __VLS_26({
            value: (__VLS_ctx.assignments),
            loading: (__VLS_ctx.loading),
            paginator: true,
            rows: (12),
            stripedRows: true,
            responsiveLayout: "scroll",
        }));
        const __VLS_28 = __VLS_27({
            value: (__VLS_ctx.assignments),
            loading: (__VLS_ctx.loading),
            paginator: true,
            rows: (12),
            stripedRows: true,
            responsiveLayout: "scroll",
        }, ...__VLS_functionalComponentArgsRest(__VLS_27));
        const { default: __VLS_31 } = __VLS_29.slots;
        let __VLS_32;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_33 = __VLS_asFunctionalComponent1(__VLS_32, new __VLS_32({
            field: "id",
            header: "#",
            sortable: true,
        }));
        const __VLS_34 = __VLS_33({
            field: "id",
            header: "#",
            sortable: true,
        }, ...__VLS_functionalComponentArgsRest(__VLS_33));
        let __VLS_37;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_38 = __VLS_asFunctionalComponent1(__VLS_37, new __VLS_37({
            field: "manga",
            header: "Manga",
            sortable: true,
        }));
        const __VLS_39 = __VLS_38({
            field: "manga",
            header: "Manga",
            sortable: true,
        }, ...__VLS_functionalComponentArgsRest(__VLS_38));
        let __VLS_42;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_43 = __VLS_asFunctionalComponent1(__VLS_42, new __VLS_42({
            field: "chapter",
            header: "Chapter",
        }));
        const __VLS_44 = __VLS_43({
            field: "chapter",
            header: "Chapter",
        }, ...__VLS_functionalComponentArgsRest(__VLS_43));
        let __VLS_47;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_48 = __VLS_asFunctionalComponent1(__VLS_47, new __VLS_47({
            field: "role",
            header: "Role",
        }));
        const __VLS_49 = __VLS_48({
            field: "role",
            header: "Role",
        }, ...__VLS_functionalComponentArgsRest(__VLS_48));
        let __VLS_52;
        /** @ts-ignore @type { | typeof __VLS_components.Column | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_53 = __VLS_asFunctionalComponent1(__VLS_52, new __VLS_52({
            header: "Status",
        }));
        const __VLS_54 = __VLS_53({
            header: "Status",
        }, ...__VLS_functionalComponentArgsRest(__VLS_53));
        const { default: __VLS_57 } = __VLS_55.slots;
        {
            const { body: __VLS_58 } = __VLS_55.slots;
            const [{ data }] = __VLS_vSlot(__VLS_58);
            let __VLS_59;
            /** @ts-ignore @type { | typeof __VLS_components.Tag} */
            Tag;
            // @ts-ignore
            const __VLS_60 = __VLS_asFunctionalComponent1(__VLS_59, new __VLS_59({
                value: (__VLS_ctx.statusLabel[data.status] || data.status),
                severity: (__VLS_ctx.severity(data.status)),
            }));
            const __VLS_61 = __VLS_60({
                value: (__VLS_ctx.statusLabel[data.status] || data.status),
                severity: (__VLS_ctx.severity(data.status)),
            }, ...__VLS_functionalComponentArgsRest(__VLS_60));
            // @ts-ignore
            [page, search, loadPage, loadPage, status, assignments, loading, statusLabel, severity,];
        }
        // @ts-ignore
        [];
        var __VLS_55;
        let __VLS_64;
        /** @ts-ignore @type { | typeof __VLS_components.Column | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_65 = __VLS_asFunctionalComponent1(__VLS_64, new __VLS_64({
            header: "Bayaran",
        }));
        const __VLS_66 = __VLS_65({
            header: "Bayaran",
        }, ...__VLS_functionalComponentArgsRest(__VLS_65));
        const { default: __VLS_69 } = __VLS_67.slots;
        {
            const { body: __VLS_70 } = __VLS_67.slots;
            const [{ data }] = __VLS_vSlot(__VLS_70);
            (__VLS_ctx.money(data.final_rate));
            // @ts-ignore
            [money,];
        }
        // @ts-ignore
        [];
        var __VLS_67;
        let __VLS_71;
        /** @ts-ignore @type { | typeof __VLS_components.Column | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_72 = __VLS_asFunctionalComponent1(__VLS_71, new __VLS_71({
            field: "deadline_at",
            header: "Deadline",
        }));
        const __VLS_73 = __VLS_72({
            field: "deadline_at",
            header: "Deadline",
        }, ...__VLS_functionalComponentArgsRest(__VLS_72));
        const { default: __VLS_76 } = __VLS_74.slots;
        {
            const { body: __VLS_77 } = __VLS_74.slots;
            const [{ data }] = __VLS_vSlot(__VLS_77);
            (data.deadline_at || '—');
            // @ts-ignore
            [];
        }
        // @ts-ignore
        [];
        var __VLS_74;
        // @ts-ignore
        [];
        var __VLS_29;
    }
    if (__VLS_ctx.page === 'staff') {
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "table-card" },
        });
        /** @type {__VLS_StyleScopedClasses['table-card']} */ ;
        let __VLS_78;
        /** @ts-ignore @type { | typeof __VLS_components.DataTable | typeof __VLS_components.DataTable} */
        DataTable;
        // @ts-ignore
        const __VLS_79 = __VLS_asFunctionalComponent1(__VLS_78, new __VLS_78({
            value: (__VLS_ctx.staff),
            loading: (__VLS_ctx.loading),
            paginator: true,
            rows: (12),
        }));
        const __VLS_80 = __VLS_79({
            value: (__VLS_ctx.staff),
            loading: (__VLS_ctx.loading),
            paginator: true,
            rows: (12),
        }, ...__VLS_functionalComponentArgsRest(__VLS_79));
        const { default: __VLS_83 } = __VLS_81.slots;
        let __VLS_84;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_85 = __VLS_asFunctionalComponent1(__VLS_84, new __VLS_84({
            field: "staff_id",
            header: "Discord Staff ID",
        }));
        const __VLS_86 = __VLS_85({
            field: "staff_id",
            header: "Discord Staff ID",
        }, ...__VLS_functionalComponentArgsRest(__VLS_85));
        let __VLS_89;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_90 = __VLS_asFunctionalComponent1(__VLS_89, new __VLS_89({
            field: "task_count",
            header: "Total Tugas",
            sortable: true,
        }));
        const __VLS_91 = __VLS_90({
            field: "task_count",
            header: "Total Tugas",
            sortable: true,
        }, ...__VLS_functionalComponentArgsRest(__VLS_90));
        let __VLS_94;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_95 = __VLS_asFunctionalComponent1(__VLS_94, new __VLS_94({
            field: "active_count",
            header: "Aktif",
            sortable: true,
        }));
        const __VLS_96 = __VLS_95({
            field: "active_count",
            header: "Aktif",
            sortable: true,
        }, ...__VLS_functionalComponentArgsRest(__VLS_95));
        let __VLS_99;
        /** @ts-ignore @type { | typeof __VLS_components.Column | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_100 = __VLS_asFunctionalComponent1(__VLS_99, new __VLS_99({
            header: "Approved",
        }));
        const __VLS_101 = __VLS_100({
            header: "Approved",
        }, ...__VLS_functionalComponentArgsRest(__VLS_100));
        const { default: __VLS_104 } = __VLS_102.slots;
        {
            const { body: __VLS_105 } = __VLS_102.slots;
            const [{ data }] = __VLS_vSlot(__VLS_105);
            (__VLS_ctx.money(data.approved_amount));
            // @ts-ignore
            [page, money, loading, staff,];
        }
        // @ts-ignore
        [];
        var __VLS_102;
        let __VLS_106;
        /** @ts-ignore @type { | typeof __VLS_components.Column | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_107 = __VLS_asFunctionalComponent1(__VLS_106, new __VLS_106({
            header: "Dibayar",
        }));
        const __VLS_108 = __VLS_107({
            header: "Dibayar",
        }, ...__VLS_functionalComponentArgsRest(__VLS_107));
        const { default: __VLS_111 } = __VLS_109.slots;
        {
            const { body: __VLS_112 } = __VLS_109.slots;
            const [{ data }] = __VLS_vSlot(__VLS_112);
            (__VLS_ctx.money(data.paid_amount));
            // @ts-ignore
            [money,];
        }
        // @ts-ignore
        [];
        var __VLS_109;
        // @ts-ignore
        [];
        var __VLS_81;
    }
    if (__VLS_ctx.page === 'payrates') {
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "payrate-grid" },
        });
        /** @type {__VLS_StyleScopedClasses['payrate-grid']} */ ;
        for (const [item] of __VLS_vFor((__VLS_ctx.payrates))) {
            __VLS_asFunctionalElement1(__VLS_intrinsics.article, __VLS_intrinsics.article)({
                key: (item.role),
                ...{ class: "panel rate-card" },
            });
            /** @type {__VLS_StyleScopedClasses['panel']} */ ;
            /** @type {__VLS_StyleScopedClasses['rate-card']} */ ;
            __VLS_asFunctionalElement1(__VLS_intrinsics.span, __VLS_intrinsics.span)({});
            (item.role);
            __VLS_asFunctionalElement1(__VLS_intrinsics.h3, __VLS_intrinsics.h3)({});
            (item.role === 'TL' ? 'Translator' : item.role === 'TS' ? 'Typesetter' : 'Translator + Typesetter');
            let __VLS_113;
            /** @ts-ignore @type { | typeof __VLS_components.InputNumber} */
            InputNumber;
            // @ts-ignore
            const __VLS_114 = __VLS_asFunctionalComponent1(__VLS_113, new __VLS_113({
                modelValue: (item.base_rate),
                mode: "currency",
                currency: "IDR",
                locale: "id-ID",
                min: (0),
            }));
            const __VLS_115 = __VLS_114({
                modelValue: (item.base_rate),
                mode: "currency",
                currency: "IDR",
                locale: "id-ID",
                min: (0),
            }, ...__VLS_functionalComponentArgsRest(__VLS_114));
            let __VLS_118;
            /** @ts-ignore @type { | typeof __VLS_components.Button} */
            Button;
            // @ts-ignore
            const __VLS_119 = __VLS_asFunctionalComponent1(__VLS_118, new __VLS_118({
                ...{ 'onClick': {} },
                label: "Simpan rate",
                icon: "pi pi-check",
                loading: (__VLS_ctx.loading),
            }));
            const __VLS_120 = __VLS_119({
                ...{ 'onClick': {} },
                label: "Simpan rate",
                icon: "pi pi-check",
                loading: (__VLS_ctx.loading),
            }, ...__VLS_functionalComponentArgsRest(__VLS_119));
            let __VLS_123;
            const __VLS_124 = {
                /** @type {typeof __VLS_123.click} */
                onClick: (...[$event]) => {
                    if (!!(!__VLS_ctx.authChecked))
                        throw 0;
                    if (!!(!__VLS_ctx.user))
                        throw 0;
                    if (!(__VLS_ctx.page === 'payrates'))
                        throw 0;
                    return (__VLS_ctx.saveRate(item));
                    // @ts-ignore
                    [page, loading, payrates, saveRate,];
                },
            };
            var __VLS_121;
            var __VLS_122;
            __VLS_asFunctionalElement1(__VLS_intrinsics.small, __VLS_intrinsics.small)({});
            // @ts-ignore
            [];
        }
    }
    if (__VLS_ctx.page === 'deadlines') {
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "table-card" },
        });
        /** @type {__VLS_StyleScopedClasses['table-card']} */ ;
        let __VLS_125;
        /** @ts-ignore @type { | typeof __VLS_components.DataTable | typeof __VLS_components.DataTable} */
        DataTable;
        // @ts-ignore
        const __VLS_126 = __VLS_asFunctionalComponent1(__VLS_125, new __VLS_125({
            value: (__VLS_ctx.deadlines),
            loading: (__VLS_ctx.loading),
        }));
        const __VLS_127 = __VLS_126({
            value: (__VLS_ctx.deadlines),
            loading: (__VLS_ctx.loading),
        }, ...__VLS_functionalComponentArgsRest(__VLS_126));
        const { default: __VLS_130 } = __VLS_128.slots;
        let __VLS_131;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_132 = __VLS_asFunctionalComponent1(__VLS_131, new __VLS_131({
            field: "deadline_at",
            header: "Deadline",
            sortable: true,
        }));
        const __VLS_133 = __VLS_132({
            field: "deadline_at",
            header: "Deadline",
            sortable: true,
        }, ...__VLS_functionalComponentArgsRest(__VLS_132));
        let __VLS_136;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_137 = __VLS_asFunctionalComponent1(__VLS_136, new __VLS_136({
            field: "manga",
            header: "Manga",
        }));
        const __VLS_138 = __VLS_137({
            field: "manga",
            header: "Manga",
        }, ...__VLS_functionalComponentArgsRest(__VLS_137));
        let __VLS_141;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_142 = __VLS_asFunctionalComponent1(__VLS_141, new __VLS_141({
            field: "chapter",
            header: "Chapter",
        }));
        const __VLS_143 = __VLS_142({
            field: "chapter",
            header: "Chapter",
        }, ...__VLS_functionalComponentArgsRest(__VLS_142));
        let __VLS_146;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_147 = __VLS_asFunctionalComponent1(__VLS_146, new __VLS_146({
            field: "staff_id",
            header: "Staff ID",
        }));
        const __VLS_148 = __VLS_147({
            field: "staff_id",
            header: "Staff ID",
        }, ...__VLS_functionalComponentArgsRest(__VLS_147));
        let __VLS_151;
        /** @ts-ignore @type { | typeof __VLS_components.Column | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_152 = __VLS_asFunctionalComponent1(__VLS_151, new __VLS_151({
            header: "Status",
        }));
        const __VLS_153 = __VLS_152({
            header: "Status",
        }, ...__VLS_functionalComponentArgsRest(__VLS_152));
        const { default: __VLS_156 } = __VLS_154.slots;
        {
            const { body: __VLS_157 } = __VLS_154.slots;
            const [{ data }] = __VLS_vSlot(__VLS_157);
            let __VLS_158;
            /** @ts-ignore @type { | typeof __VLS_components.Tag} */
            Tag;
            // @ts-ignore
            const __VLS_159 = __VLS_asFunctionalComponent1(__VLS_158, new __VLS_158({
                value: (__VLS_ctx.statusLabel[data.status]),
                severity: (__VLS_ctx.severity(data.status)),
            }));
            const __VLS_160 = __VLS_159({
                value: (__VLS_ctx.statusLabel[data.status]),
                severity: (__VLS_ctx.severity(data.status)),
            }, ...__VLS_functionalComponentArgsRest(__VLS_159));
            // @ts-ignore
            [page, loading, statusLabel, severity, deadlines,];
        }
        // @ts-ignore
        [];
        var __VLS_154;
        // @ts-ignore
        [];
        var __VLS_128;
    }
    if (__VLS_ctx.page === 'recap') {
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "toolbar" },
        });
        /** @type {__VLS_StyleScopedClasses['toolbar']} */ ;
        __VLS_asFunctionalElement1(__VLS_intrinsics.label, __VLS_intrinsics.label)({});
        __VLS_asFunctionalElement1(__VLS_intrinsics.input)({
            type: "month",
        });
        (__VLS_ctx.period);
        let __VLS_163;
        /** @ts-ignore @type { | typeof __VLS_components.Button} */
        Button;
        // @ts-ignore
        const __VLS_164 = __VLS_asFunctionalComponent1(__VLS_163, new __VLS_163({
            ...{ 'onClick': {} },
            label: "Tampilkan",
            icon: "pi pi-filter",
        }));
        const __VLS_165 = __VLS_164({
            ...{ 'onClick': {} },
            label: "Tampilkan",
            icon: "pi pi-filter",
        }, ...__VLS_functionalComponentArgsRest(__VLS_164));
        let __VLS_168;
        const __VLS_169 = {
            /** @type {typeof __VLS_168.click} */
            onClick: (__VLS_ctx.loadPage),
        };
        var __VLS_166;
        var __VLS_167;
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "table-card" },
        });
        /** @type {__VLS_StyleScopedClasses['table-card']} */ ;
        let __VLS_170;
        /** @ts-ignore @type { | typeof __VLS_components.DataTable | typeof __VLS_components.DataTable} */
        DataTable;
        // @ts-ignore
        const __VLS_171 = __VLS_asFunctionalComponent1(__VLS_170, new __VLS_170({
            value: (__VLS_ctx.recap),
            loading: (__VLS_ctx.loading),
        }));
        const __VLS_172 = __VLS_171({
            value: (__VLS_ctx.recap),
            loading: (__VLS_ctx.loading),
        }, ...__VLS_functionalComponentArgsRest(__VLS_171));
        const { default: __VLS_175 } = __VLS_173.slots;
        let __VLS_176;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_177 = __VLS_asFunctionalComponent1(__VLS_176, new __VLS_176({
            field: "staff_id",
            header: "Staff ID",
        }));
        const __VLS_178 = __VLS_177({
            field: "staff_id",
            header: "Staff ID",
        }, ...__VLS_functionalComponentArgsRest(__VLS_177));
        let __VLS_181;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_182 = __VLS_asFunctionalComponent1(__VLS_181, new __VLS_181({
            field: "chapter_count",
            header: "Chapter",
        }));
        const __VLS_183 = __VLS_182({
            field: "chapter_count",
            header: "Chapter",
        }, ...__VLS_functionalComponentArgsRest(__VLS_182));
        let __VLS_186;
        /** @ts-ignore @type { | typeof __VLS_components.Column | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_187 = __VLS_asFunctionalComponent1(__VLS_186, new __VLS_186({
            header: "Total",
        }));
        const __VLS_188 = __VLS_187({
            header: "Total",
        }, ...__VLS_functionalComponentArgsRest(__VLS_187));
        const { default: __VLS_191 } = __VLS_189.slots;
        {
            const { body: __VLS_192 } = __VLS_189.slots;
            const [{ data }] = __VLS_vSlot(__VLS_192);
            __VLS_asFunctionalElement1(__VLS_intrinsics.strong, __VLS_intrinsics.strong)({});
            (__VLS_ctx.money(data.total_amount));
            // @ts-ignore
            [page, money, loadPage, loading, period, recap,];
        }
        // @ts-ignore
        [];
        var __VLS_189;
        // @ts-ignore
        [];
        var __VLS_173;
    }
    if (__VLS_ctx.page === 'audit') {
        __VLS_asFunctionalElement1(__VLS_intrinsics.div, __VLS_intrinsics.div)({
            ...{ class: "table-card" },
        });
        /** @type {__VLS_StyleScopedClasses['table-card']} */ ;
        let __VLS_193;
        /** @ts-ignore @type { | typeof __VLS_components.DataTable | typeof __VLS_components.DataTable} */
        DataTable;
        // @ts-ignore
        const __VLS_194 = __VLS_asFunctionalComponent1(__VLS_193, new __VLS_193({
            value: (__VLS_ctx.audit),
            loading: (__VLS_ctx.loading),
            paginator: true,
            rows: (15),
        }));
        const __VLS_195 = __VLS_194({
            value: (__VLS_ctx.audit),
            loading: (__VLS_ctx.loading),
            paginator: true,
            rows: (15),
        }, ...__VLS_functionalComponentArgsRest(__VLS_194));
        const { default: __VLS_198 } = __VLS_196.slots;
        let __VLS_199;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_200 = __VLS_asFunctionalComponent1(__VLS_199, new __VLS_199({
            field: "created_at",
            header: "Waktu",
        }));
        const __VLS_201 = __VLS_200({
            field: "created_at",
            header: "Waktu",
        }, ...__VLS_functionalComponentArgsRest(__VLS_200));
        let __VLS_204;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_205 = __VLS_asFunctionalComponent1(__VLS_204, new __VLS_204({
            field: "actor_id",
            header: "Pelaku",
        }));
        const __VLS_206 = __VLS_205({
            field: "actor_id",
            header: "Pelaku",
        }, ...__VLS_functionalComponentArgsRest(__VLS_205));
        let __VLS_209;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_210 = __VLS_asFunctionalComponent1(__VLS_209, new __VLS_209({
            field: "action",
            header: "Aksi",
        }));
        const __VLS_211 = __VLS_210({
            field: "action",
            header: "Aksi",
        }, ...__VLS_functionalComponentArgsRest(__VLS_210));
        let __VLS_214;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_215 = __VLS_asFunctionalComponent1(__VLS_214, new __VLS_214({
            field: "target_type",
            header: "Target",
        }));
        const __VLS_216 = __VLS_215({
            field: "target_type",
            header: "Target",
        }, ...__VLS_functionalComponentArgsRest(__VLS_215));
        let __VLS_219;
        /** @ts-ignore @type { | typeof __VLS_components.Column} */
        Column;
        // @ts-ignore
        const __VLS_220 = __VLS_asFunctionalComponent1(__VLS_219, new __VLS_219({
            field: "target_id",
            header: "ID",
        }));
        const __VLS_221 = __VLS_220({
            field: "target_id",
            header: "ID",
        }, ...__VLS_functionalComponentArgsRest(__VLS_220));
        // @ts-ignore
        [page, loading, audit,];
        var __VLS_196;
    }
}
// @ts-ignore
[];
const __VLS_export = (await import('vue')).defineComponent({});
export default {};
