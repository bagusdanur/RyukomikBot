import discord

from config import STAFF_LOG_CHANNEL_ID, STAFF_TASKS_CHANNEL_ID


def build_admin_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ Pusat Kontrol Administrator",
        description=(
            "Kelola seluruh alur kerja staff dari satu panel: membuat tugas, "
            "memeriksa hasil, dan memproses pembayaran."
        ),
        color=discord.Color.from_rgb(220, 53, 69),
    )
    embed.add_field(
        name="📋 1. Assign Tugas",
        value=f"Buat tugas baru. Pengumuman dan tombol claim dikirim ke <#{STAFF_TASKS_CHANNEL_ID}>.",
        inline=False,
    )
    embed.add_field(
        name="📝 2. Review Hasil",
        value="Periksa link Google Drive, lalu pilih **Setuju** atau kirim **Revisi**.",
        inline=False,
    )
    embed.add_field(
        name="💰 3. Gaji & Invoice",
        value=(
            "Pantau invoice otomatis tanggal 4/19 atau pencairan langsung, "
            "kemudian konfirmasi setelah transfer benar-benar dilakukan."
        ),
        inline=False,
    )
    embed.add_field(
        name="📊 4. Statistik",
        value="Pantau tugas tersedia, dikerjakan, menunggu review, disetujui, dan dibayar.",
        inline=False,
    )
    embed.add_field(
        name="ℹ️ Catatan",
        value=(
            f"Panel admin hanya digunakan di <#{STAFF_LOG_CHANNEL_ID}>. "
            "Gunakan tombol **Panduan** jika membutuhkan penjelasan lengkap."
        ),
        inline=False,
    )
    embed.set_footer(text="Ryukomik Staff Management • Administrator Panel")
    return embed


def build_staff_panel_embed(staff: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="👤 Ruang Kerja Staff",
        description=(
            f"Halo {staff.mention}, panel ini adalah pusat kerja privat kamu. "
            "Detail tugas, submit, revisi, dan informasi gaji tersedia di sini."
        ),
        color=discord.Color.from_rgb(88, 101, 242),
    )
    embed.add_field(
        name="📋 Tugas & Hasil",
        value=(
            "Gunakan **Tugas Saya** untuk melihat pekerjaan dan **Submit Hasil** "
            "untuk mengirim folder Google Drive."
        ),
        inline=False,
    )
    embed.add_field(
        name="💰 Penghasilan & Gaji",
        value=(
            "Lihat saldo dan invoice, atur bank/e-wallet/QRIS, ajukan pencairan langsung, "
            "serta lihat riwayat pembayaran dari satu submenu."
        ),
        inline=False,
    )
    embed.add_field(
        name="🧰 Peralatan",
        value="Gunakan **Download RAW**, **Bantuan Tugas**, dan **Panduan** sesuai kebutuhan.",
        inline=False,
    )
    embed.add_field(
        name="🔄 Alur Singkat",
        value="**Claim → Kerjakan → Submit → Review → Approved → Paid**\nJika direvisi, perbaiki lalu submit kembali.",
        inline=False,
    )
    embed.set_footer(text="Ryukomik Staff Management • Private Staff Panel")
    return embed


def build_guide_embed(audience: str = "all") -> discord.Embed:
    if audience == "staff":
        embed = discord.Embed(
            title="📚 Panduan Kerja Staff Ryukomik",
            description=(
                "Ikuti panduan ini dari menerima tugas sampai menerima invoice pembayaran. "
                "Semua proses dilakukan melalui tiket staff privat kamu."
            ),
            color=discord.Color.from_rgb(88, 101, 242),
        )
        embed.add_field(
            name="1️⃣ Ambil atau Terima Tugas",
            value=(
                f"• Buka <#{STAFF_TASKS_CHANNEL_ID}> dan tekan **Claim Tugas** sesuai role.\n"
                "• Tugas yang di-assign langsung oleh admin otomatis masuk ke tiketmu.\n"
                "• Satu tugas dapat berisi hingga lima chapter; cek seluruh chapter dan deadline sebelum mulai."
            ),
            inline=False,
        )
        embed.add_field(
            name="2️⃣ Cek Detail dan Download RAW",
            value=(
                "Tekan **Tugas Saya** untuk melihat judul, chapter, role, bayaran per chapter, total, dan deadline.\n"
                "Tekan **Download RAW**, pilih tugas aktif, lalu unduh hanya chapter yang tercantum pada tugas."
            ),
            inline=False,
        )
        embed.add_field(
            name="3️⃣ Kerjakan dan Submit",
            value=(
                "Upload seluruh hasil ke satu folder Google Drive dan aktifkan akses "
                "**siapa saja yang memiliki link**. Tekan **Submit Hasil**, pilih tugas, "
                "tempel link folder, lalu tambahkan catatan jika diperlukan."
            ),
            inline=False,
        )
        embed.add_field(
            name="4️⃣ Review dan Revisi",
            value=(
                "• `submitted` — menunggu pemeriksaan administrator.\n"
                "• `revision` — baca catatan, perbaiki, lalu submit ulang pada tugas yang sama.\n"
                "• `approved` — pekerjaan diterima dan siap ditagihkan.\n"
                "• `paid` — transfer telah dikonfirmasi."
            ),
            inline=False,
        )
        embed.add_field(
            name="5️⃣ Penghasilan & Metode Pembayaran",
            value=(
                "Tekan **Penghasilan & Gaji** untuk melihat saldo, jadwal, invoice aktif, dan metode utama.\n"
                "Pilih **Atur Metode Pembayaran** untuk menyimpan bank, e-wallet, atau QRIS. "
                "Bank/e-wallet diisi melalui form; gambar QRIS dipilih langsung dari form upload, bukan dikirim ke chat.\n"
                "Pastikan nama pemilik dan tujuan pembayaran benar sebelum menjadikannya metode utama."
            ),
            inline=False,
        )
        embed.add_field(
            name="6️⃣ Invoice Otomatis dan Ambil Gaji",
            value=(
                "• Tanggal **19**: tugas approved tanggal 1–15 bulan berjalan.\n"
                "• Tanggal **4**: tugas approved tanggal 16–akhir bulan sebelumnya.\n"
                "• Invoice tetap dibuat jika metode belum diatur, tetapi transfer menunggu kamu memilih metode utama.\n"
                "• Untuk pencairan sebelum jadwal, buka **Penghasilan & Gaji → Ambil Gaji Sekarang**, "
                "pilih metode, periksa nominal, lalu konfirmasi pengajuan."
            ),
            inline=False,
        )
        embed.add_field(
            name="7️⃣ Setelah Gaji Ditransfer",
            value=(
                "Setelah admin mengonfirmasi transfer, status menjadi **paid**. "
                "Ringkasan pembayaran dan file invoice PDF berstatus **LUNAS** dikirim ke tiket privat ini. "
                "Riwayatnya dapat dilihat melalui **Penghasilan & Gaji → Riwayat Pembayaran**."
            ),
            inline=False,
        )
        embed.add_field(
            name="🆘 Jika Ada Kendala",
            value=(
                "Tekan **Bantuan Tugas**, pilih proyek, lalu gunakan **Laporkan Kendala** atau "
                "**Minta Perpanjangan**. Gunakan `/menu` di tiket jika ingin memindahkan panel ke pesan terbaru."
            ),
            inline=False,
        )
        embed.set_footer(text="Ryukomik • Panduan kerja staff • Jangan bagikan data pembayaran di channel publik")
        return embed

    embed = discord.Embed(
        title="📚 Panduan Ryukomik Staff Management",
        description="Panduan pengelolaan tugas, review, invoice, rekrutmen, dan RAW downloader.",
        color=discord.Color.from_rgb(245, 166, 35),
    )
    if audience in ("all", "admin"):
        embed.add_field(
            name="🛠️ Alur Administrator",
            value=(
                "1. Gunakan `/panels admin` di staff-mod.\n"
                "2. Buat tugas dan tentukan manga, chapter, role, serta rate per chapter.\n"
                f"3. Review submit Google Drive dari <#{STAFF_LOG_CHANNEL_ID}>.\n"
                "4. Pantau invoice otomatis tanggal 4/19 atau pencairan langsung pada dashboard.\n"
                "5. Setelah transfer, konfirmasi pembayaran agar PDF LUNAS dikirim ke tiket staff."
            ),
            inline=False,
        )
    if audience == "all":
        embed.add_field(
            name="👤 Alur Staff",
            value=(
                "Claim tugas → cek chapter → download RAW → submit Google Drive → review → "
                "buka **Penghasilan & Gaji** untuk metode pembayaran, invoice, dan riwayat."
            ),
            inline=False,
        )
    embed.add_field(
        name="🎫 Rekrutmen Privat",
        value=(
            "Pelamar membuat tiket melalui panel rekrutmen. Tiket hanya terlihat oleh pelamar, "
            "administrator, dan bot."
        ),
        inline=False,
    )
    embed.add_field(
        name="🖼️ RAW Downloader",
        value=(
            "Staff menggunakan **Download RAW** dari tiket agar hanya chapter tugas yang tampil. "
            "Akses pencarian RAW bebas melalui slash command hanya tersedia untuk administrator."
        ),
        inline=False,
    )
    embed.set_footer(text="Butuh bantuan? Gunakan tiket privat atau hubungi administrator.")
    return embed
