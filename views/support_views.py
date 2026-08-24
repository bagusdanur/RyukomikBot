import discord
from datetime import date, datetime

import database as db
from config import STAFF_LOG_CHANNEL_ID
from helpers.utils import find_ticket, is_admin, is_staff


class TaskSupportView(discord.ui.View):
    def __init__(self, assignments):
        super().__init__(timeout=300)
        self.add_item(TaskSupportSelect(assignments[:25]))


class TaskSupportSelect(discord.ui.Select):
    def __init__(self, assignments):
        self.assignments = {str(item["id"]): item for item in assignments}
        options = [
            discord.SelectOption(
                label=f"#{item['id']} {item['manga']}"[:100],
                value=str(item["id"]),
                description=f"Ch. {item['chapter']} • deadline {item.get('deadline_at') or 'tidak ada'}"[:100],
            )
            for item in assignments
        ]
        super().__init__(placeholder="Pilih tugas yang mengalami kendala", options=options)

    async def callback(self, interaction):
        assignment = self.assignments[self.values[0]]
        if assignment["staff_id"] != interaction.user.id:
            return await interaction.response.send_message("Tugas ini bukan milikmu.")
        embed = discord.Embed(
            title="Bantuan Tugas",
            description=(
                f"**#{assignment['id']} • {assignment['manga']} Ch. {assignment['chapter']}**\n"
                "Pilih bantuan yang kamu perlukan. Administrator akan menerima detail proyek otomatis."
            ),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, view=TaskSupportActionView(assignment))


class TaskSupportActionView(discord.ui.View):
    def __init__(self, assignment):
        super().__init__(timeout=300)
        self.assignment = assignment

    @discord.ui.button(label="Laporkan Kendala", style=discord.ButtonStyle.danger)
    async def problem_button(self, interaction, _button):
        await interaction.response.send_modal(TaskSupportModal(self.assignment, "kendala"))

    @discord.ui.button(label="Minta Perpanjangan", style=discord.ButtonStyle.primary)
    async def extension_button(self, interaction, _button):
        await interaction.response.send_modal(DeadlineExtensionModal(self.assignment))


class DeadlineExtensionModal(discord.ui.Modal, title="Minta Perpanjangan Deadline"):
    requested_deadline = discord.ui.TextInput(
        label="Deadline baru",
        placeholder="YYYY-MM-DD, contoh: 2026-08-30",
        min_length=10,
        max_length=10,
    )
    reason = discord.ui.TextInput(
        label="Alasan perpanjangan",
        placeholder="Jelaskan kendala dan progres tugas saat ini...",
        style=discord.TextStyle.paragraph,
        min_length=10,
        max_length=1000,
    )

    def __init__(self, assignment):
        super().__init__()
        self.assignment = assignment

    async def on_submit(self, interaction):
        if not is_staff(interaction.user) or int(self.assignment["staff_id"] or 0) != interaction.user.id:
            return await interaction.response.send_message("Permintaan tidak valid.")
        try:
            requested = datetime.strptime(self.requested_deadline.value.strip(), "%Y-%m-%d").date()
            if requested <= date.today():
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "Deadline baru harus berformat YYYY-MM-DD dan setelah hari ini."
            )
        current = await db.get_assignment(int(self.assignment["id"]))
        if not current or current["status"] not in {"claimed", "revision"}:
            return await interaction.response.send_message("Tugas ini sudah tidak dapat diperpanjang.")
        request = await db.create_deadline_extension_request(
            int(current["id"]), interaction.user.id, str(current.get("deadline_at") or ""),
            requested.isoformat(), self.reason.value,
        )
        if not request:
            return await interaction.response.send_message(
                "Permintaan perpanjangan untuk tugas ini masih menunggu keputusan Administrator."
            )
        log_channel = interaction.guild.get_channel(STAFF_LOG_CHANNEL_ID) if interaction.guild else None
        if not isinstance(log_channel, discord.TextChannel):
            return await interaction.response.send_message("Channel administrator tidak ditemukan.")
        embed = discord.Embed(
            title=f"⏳ Permintaan Perpanjangan #{request['id']}",
            description=f"**Tugas #{current['id']} • {current['manga']} Ch. {current['chapter']}**",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Staff", value=interaction.user.mention, inline=True)
        embed.add_field(name="Deadline Lama", value=request["old_deadline"], inline=True)
        embed.add_field(name="Deadline Diminta", value=request["requested_deadline"], inline=True)
        embed.add_field(name="Alasan", value=request["reason"], inline=False)
        if interaction.channel:
            embed.add_field(name="Tiket Staff", value=interaction.channel.mention, inline=False)
        embed.set_footer(text="Submit tetap terkunci sampai permintaan disetujui")
        await log_channel.send(embed=embed, view=DeadlineExtensionReviewView(int(request["id"])))
        await interaction.response.send_message(
            f"Permintaan perpanjangan sampai **{requested.isoformat()}** sudah dikirim. "
            "Submit tetap terkunci sampai Administrator menyetujuinya."
        )


class DeadlineExtensionDecisionDynamic(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"deadline_extension:(?P<action>approve|reject):(?P<request_id>\d+):v1",
):
    def __init__(self, request_id: int, action: str):
        self.request_id, self.action = request_id, action
        super().__init__(discord.ui.Button(
            label="Setujui" if action == "approve" else "Tolak",
            emoji="✅" if action == "approve" else "❌",
            style=discord.ButtonStyle.success if action == "approve" else discord.ButtonStyle.danger,
            custom_id=f"deadline_extension:{action}:{request_id}:v1",
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["request_id"]), match["action"])

    async def callback(self, interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya Administrator yang dapat memutuskan.", ephemeral=True)
        request = await db.get_deadline_extension_request(self.request_id)
        if not request or request["status"] != "pending":
            return await interaction.response.send_message("Permintaan ini sudah diproses.", ephemeral=True)
        approved = self.action == "approve"
        if approved and datetime.strptime(request["requested_deadline"], "%Y-%m-%d").date() <= date.today():
            return await interaction.response.send_message(
                "Tanggal yang diminta sudah lewat. Tolak permintaan ini dan minta staff mengajukan tanggal baru.",
                ephemeral=True,
            )
        if not await db.resolve_deadline_extension_request(self.request_id, interaction.user.id, approved):
            return await interaction.response.send_message("Permintaan gagal diproses.", ephemeral=True)
        await interaction.response.edit_message(view=None)
        result = "disetujui" if approved else "ditolak"
        ticket = await find_ticket(interaction.guild, int(request["staff_id"])) if interaction.guild else None
        if isinstance(ticket, discord.TextChannel):
            await ticket.send(
                content=f"<@{request['staff_id']}>",
                embed=discord.Embed(
                    title=f"{'✅' if approved else '❌'} Perpanjangan Deadline {result.title()}",
                    description=(
                        f"Tugas **#{request['assignment_id']}** mendapat deadline baru **{request['requested_deadline']}**. Submit kembali dibuka."
                        if approved else f"Permintaan perpanjangan tugas **#{request['assignment_id']}** ditolak. Submit tetap terkunci setelah deadline."
                    ),
                    color=discord.Color.green() if approved else discord.Color.red(),
                ),
            )
        await interaction.followup.send(f"Permintaan #{self.request_id} berhasil {result}.", ephemeral=True)


class DeadlineExtensionReviewView(discord.ui.View):
    def __init__(self, request_id: int):
        super().__init__(timeout=None)
        self.add_item(DeadlineExtensionDecisionDynamic(request_id, "approve"))
        self.add_item(DeadlineExtensionDecisionDynamic(request_id, "reject"))


class TaskSupportModal(discord.ui.Modal):
    detail = discord.ui.TextInput(
        label="Jelaskan kebutuhanmu",
        placeholder="Contoh: RAW halaman 12 rusak / butuh tambahan waktu sampai 2026-07-25",
        style=discord.TextStyle.paragraph,
        min_length=5,
        max_length=1000,
    )

    def __init__(self, assignment, request_type):
        super().__init__(title="Lapor Kendala" if request_type == "kendala" else "Minta Perpanjangan")
        self.assignment = assignment
        self.request_type = request_type

    async def on_submit(self, interaction):
        if not is_staff(interaction.user) or self.assignment["staff_id"] != interaction.user.id:
            return await interaction.response.send_message("Permintaan tidak valid.")
        log_channel = interaction.guild.get_channel(STAFF_LOG_CHANNEL_ID) if interaction.guild else None
        if not log_channel:
            return await interaction.response.send_message("Channel administrator tidak ditemukan. Hubungi admin secara langsung.")
        label = "Kendala Tugas" if self.request_type == "kendala" else "Permintaan Perpanjangan"
        embed = discord.Embed(title=label, color=discord.Color.red() if self.request_type == "kendala" else discord.Color.orange())
        embed.add_field(name="Staff", value=interaction.user.mention, inline=True)
        embed.add_field(name="Tugas", value=f"#{self.assignment['id']} • {self.assignment['manga']} Ch. {self.assignment['chapter']}", inline=False)
        embed.add_field(name="Deadline Sekarang", value=self.assignment.get("deadline_at") or "Tidak ditentukan", inline=True)
        embed.add_field(name="Penjelasan", value=self.detail.value, inline=False)
        if interaction.channel:
            embed.add_field(name="Tiket Staff", value=interaction.channel.mention, inline=False)
        await log_channel.send(embed=embed)
        await interaction.response.send_message(
            f"Permintaan **{label.lower()}** sudah dikirim ke administrator. Lanjutkan komunikasi di tiket ini."
        )
