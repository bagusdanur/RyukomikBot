import discord

from config import STAFF_LOG_CHANNEL_ID, STAFF_TASKS_CHANNEL_ID


def build_admin_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🛠️ Pusat Kontrol Administrator",
        description=(
            "Kelola seluruh alur kerja staff dari satu panel. Mulai dari membuat tugas, "
            "memeriksa hasil, sampai memproses pembayaran."
        ),
        color=discord.Color.from_rgb(220, 53, 69),
    )
    embed.add_field(
        name="📋 1. Assign Tugas",
        value=f"Buat tugas baru. Pengumuman dan tombol claim akan dikirim ke <#{STAFF_TASKS_CHANNEL_ID}>.",
        inline=False,
    )
    embed.add_field(
        name="📝 2. Review Hasil",
        value="Periksa link hasil staff, lalu pilih **Setuju** atau kirim **Revisi**.",
        inline=False,
    )
    embed.add_field(
        name="💰 3. Rekap Gaji",
        value="Pilih staff dan periode, periksa total chapter, kemudian konfirmasi pembayaran.",
        inline=False,
    )
    embed.add_field(
        name="📊 4. Statistik",
        value="Pantau tugas open, sedang dikerjakan, menunggu review, disetujui, dan dibayar.",
        inline=False,
    )
    embed.add_field(
        name="ℹ️ Catatan",
        value=(
            f"Panel admin hanya digunakan di <#{STAFF_LOG_CHANNEL_ID}>. "
            "Gunakan tombol **Panduan** jika membutuhkan penjelasan alur lengkap."
        ),
        inline=False,
    )
    embed.set_footer(text="Ryukomik Staff Management • Administrator Panel")
    return embed


def build_staff_panel_embed(staff: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title="👤 Ruang Kerja Staff",
        description=(
            f"Halo {staff.mention}, panel ini adalah pusat tugas privat kamu. "
            "Semua proses submit dan revisi dilakukan dari tiket ini."
        ),
        color=discord.Color.from_rgb(88, 101, 242),
    )
    embed.add_field(
        name="📋 Tugas Saya",
        value="Lihat tugas aktif, status review, tugas revisi, serta pekerjaan yang sudah selesai.",
        inline=False,
    )
    embed.add_field(
        name="📤 Submit Hasil",
        value="Pilih tugas berstatus **claimed/revision**, lalu kirim link Google Drive hasil kerja.",
        inline=False,
    )
    embed.add_field(
        name="💰 Penghasilan",
        value="Lihat jumlah tugas, pendapatan yang disetujui, pembayaran, dan saldo pending periode ini.",
        inline=False,
    )
    embed.add_field(
        name="🔄 Alur Singkat",
        value="**Claim → Kerjakan → Submit → Review → Approved → Paid**\nJika direvisi: perbaiki hasil lalu submit kembali.",
        inline=False,
    )
    embed.set_footer(text="Ryukomik Staff Management • Private Staff Panel")
    return embed


def build_guide_embed(audience: str = "all") -> discord.Embed:
    if audience == "staff":
        embed = discord.Embed(
            title="📚 Panduan Kerja Staff Ryukomik",
            description=(
                "Panduan singkat untuk mengerjakan tugas dari awal sampai pembayaran. "
                "Semua detail tugas dan submit dilakukan melalui tiket privat kamu."
            ),
            color=discord.Color.from_rgb(88, 101, 242),
        )
        embed.add_field(
            name="1️⃣ Ambil atau Terima Tugas",
            value=(
                f"• Buka <#{STAFF_TASKS_CHANNEL_ID}> lalu tekan **Claim Tugas** pada pekerjaan yang sesuai role kamu.\n"
                "• Jika admin assign langsung, tugas otomatis muncul di tiket privat—tidak perlu claim.\n"
                "• Jangan claim pekerjaan yang tidak dapat kamu selesaikan sesuai deadline."
            ),
            inline=False,
        )
        embed.add_field(
            name="2️⃣ Cek Detail dan Kerjakan",
            value=(
                "Tekan **Tugas Saya**, lalu pilih tugas dari dropdown untuk melihat chapter, role, "
                "bayaran, status, dan deadline. Kerjakan sesuai role **TL**, **TS**, atau **TL+TS**."
            ),
            inline=False,
        )
        embed.add_field(
            name="3️⃣ Ambil Bahan RAW",
            value=(
                "Jalankan `/raw-search`, pilih sumber **Asura/Doujiva**, lalu pilih komik dan chapter "
                "melalui dropdown. Bot akan membuat ZIP; kamu tidak perlu menyalin manga ID atau chapter ID."
            ),
            inline=False,
        )
        embed.add_field(
            name="4️⃣ Submit Hasil",
            value=(
                "Upload hasil ke Google Drive dan pastikan izin link dapat dibuka. Tekan **Submit Hasil**, "
                "pilih tugas, tempel link, lalu tambahkan catatan bila diperlukan."
            ),
            inline=False,
        )
        embed.add_field(
            name="5️⃣ Review, Revisi, dan Selesai",
            value=(
                "• `submitted` — menunggu pemeriksaan admin.\n"
                "• `revision` — baca catatan, perbaiki, lalu submit ulang dari tugas yang sama.\n"
                "• `approved` — pekerjaan diterima dan masuk rekap gaji.\n"
                "• `paid` — pembayaran sudah dikonfirmasi."
            ),
            inline=False,
        )
        embed.add_field(
            name="💰 Cek Penghasilan",
            value=(
                "Tekan **Penghasilan** untuk melihat tugas periode berjalan, nominal disetujui, "
                "yang sudah dibayar, dan yang masih menunggu proses."
            ),
            inline=False,
        )
        embed.add_field(
            name="🆘 Kalau Ada Masalah",
            value=(
                "Jelaskan kendala di tiket privat dan tag administrator. Sertakan nomor tugas, "
                "pesan error, dan screenshot agar cepat diperiksa. Jangan membuat tiket staff baru."
            ),
            inline=False,
        )
        embed.set_footer(text="Ryukomik • Panduan kerja staff")
        return embed

    embed = discord.Embed(
        title="📚 Panduan Lengkap Ryukomik Bot",
        description="Panduan alur tugas, panel, tiket privat, pembayaran, rekrutmen, dan RAW downloader.",
        color=discord.Color.from_rgb(245, 166, 35),
    )
    if audience in ("all", "admin"):
        embed.add_field(
            name="🛠️ Alur Administrator",
            value=(
                "1. `/panels admin` di channel staff-mod.\n"
                "2. **Assign Tugas** dan isi manga, chapter, role, serta rate.\n"
                "3. Setelah staff submit, buka **Review** untuk approve/revisi.\n"
                "4. Gunakan **Rekap Gaji** untuk menghitung dan mengonfirmasi pembayaran.\n"
                "5. Buat panel staff dengan `/panels staff staff:@nama`."
            ),
            inline=False,
        )
    if audience == "all":
        embed.add_field(
            name="👤 Alur Staff",
            value=(
                "1. Claim tugas yang tersedia di channel staff-tasks.\n"
                "2. Buka tiket privat dan baca detail tugas.\n"
                "3. Klik **Submit Hasil** dan kirim link Google Drive.\n"
                "4. Jika revision, perbaiki sesuai catatan dan submit ulang.\n"
                "5. Cek pendapatan melalui tombol **Penghasilan**."
            ),
            inline=False,
        )
    embed.add_field(
        name="🎫 Rekrutmen Privat",
        value=(
            "Admin mengirim panel dengan `!rekrut`. Pelamar membuat tiket dan memilih posisi. "
            "Tiket hanya terlihat oleh pelamar, administrator, dan bot. Gunakan "
            "`!fix-rekrut semua` untuk memperbaiki tiket lama."
        ),
        inline=False,
    )
    embed.add_field(
        name="🖼️ RAW Downloader",
        value=(
            "`/raw-search` cari komik • `/raw-chapters` lihat chapter • "
            "`/raw-download` unduh satu chapter • `/raw-download-batch` unduh beberapa chapter."
        ),
        inline=False,
    )
    embed.add_field(
        name="🚦 Arti Status",
        value=(
            "`open` tersedia • `claimed` sedang dikerjakan • `submitted` menunggu review • "
            "`revision` perlu diperbaiki • `approved` masuk rekap • `paid` sudah dibayar"
        ),
        inline=False,
    )
    embed.set_footer(text="Butuh bantuan? Hubungi administrator melalui tiket privat.")
    return embed
