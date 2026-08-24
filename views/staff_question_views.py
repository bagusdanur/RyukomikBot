import discord

import database as db
from config import STAFF_LOG_CHANNEL_ID
from helpers.utils import is_staff


class StaffQuestionAnswerModal(discord.ui.Modal, title="Jawab Pertanyaan Admin"):
    answer = discord.ui.TextInput(
        label="Jawaban",
        placeholder="Tulis jawaban kamu di sini...",
        style=discord.TextStyle.paragraph,
        min_length=1,
        max_length=1800,
    )

    def __init__(self, question_id: int):
        super().__init__()
        self.question_id = question_id

    async def on_submit(self, interaction: discord.Interaction):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Hanya Staff yang dapat menjawab.", ephemeral=True)
        question = await db.get_staff_question(self.question_id)
        if not question or question["status"] != "open":
            return await interaction.response.send_message("Pertanyaan ini sudah ditutup atau tidak ditemukan.", ephemeral=False)
        saved = await db.answer_staff_question(self.question_id, interaction.user.id, self.answer.value)
        if not saved:
            return await interaction.response.send_message("Jawaban tidak dapat disimpan.", ephemeral=False)

        embed = discord.Embed(
            title=f"✅ Jawaban Terkirim • {question['title']}",
            description=self.answer.value,
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Pertanyaan Staff #{self.question_id} • Jawaban dapat diperbarui")
        await interaction.response.send_message(embed=embed, ephemeral=False)

        if interaction.guild:
            log_channel = interaction.guild.get_channel(STAFF_LOG_CHANNEL_ID)
            if isinstance(log_channel, discord.TextChannel):
                log_embed = discord.Embed(
                    title=f"💬 Jawaban Pertanyaan Staff #{self.question_id}",
                    description=self.answer.value,
                    color=discord.Color.blue(),
                )
                log_embed.add_field(name="Pertanyaan", value=question["title"], inline=False)
                log_embed.add_field(name="Staff", value=interaction.user.mention, inline=True)
                if interaction.channel:
                    log_embed.add_field(name="Tiket", value=interaction.channel.mention, inline=True)
                await log_channel.send(embed=log_embed, allowed_mentions=discord.AllowedMentions.none())


class StaffQuestionAnswerDynamic(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"staff_question:answer:(?P<question_id>\d+):v1",
):
    def __init__(self, question_id: int):
        self.question_id = question_id
        super().__init__(discord.ui.Button(
            label="Jawab Pertanyaan",
            style=discord.ButtonStyle.primary,
            custom_id=f"staff_question:answer:{question_id}:v1",
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["question_id"]))

    async def callback(self, interaction: discord.Interaction):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Hanya Staff yang dapat menjawab.", ephemeral=True)
        await interaction.response.send_modal(StaffQuestionAnswerModal(self.question_id))
