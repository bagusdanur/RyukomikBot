import discord

from config import STAFF_LOG_CHANNEL_ID
from helpers.utils import is_staff


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
        await interaction.response.send_modal(TaskSupportModal(self.assignment, "perpanjangan"))


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
