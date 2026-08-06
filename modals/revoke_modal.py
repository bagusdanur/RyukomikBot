import discord
import database as db

class RevokeModal(discord.ui.Modal, title="Penarikan Tugas"):
    reason = discord.ui.TextInput(
        label="Alasan Penarikan (Opsional)",
        style=discord.TextStyle.long,
        placeholder="Ketikkan alasan tugas ini dibatalkan...",
        required=False,
        max_length=500
    )

    def __init__(self, assignment: dict):
        super().__init__()
        self.assignment = assignment

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        
        assignment_id = self.assignment["id"]
        reason_text = self.reason.value.strip() or "Dibatalkan oleh Admin."
        
        # Revoke the assignment
        success = await db.revoke_assignment(assignment_id, reason_text)
        if not success:
            return await interaction.followup.send(f"❌ Gagal menarik tugas #{assignment_id}. Mungkin statusnya sudah berubah.")

        # Try to delete the announcement message in #・staff-tasks
        if self.assignment.get("message_id"):
            from config import STAFF_TASKS_CHANNEL_ID
            channel = interaction.client.get_channel(STAFF_TASKS_CHANNEL_ID)
            if channel:
                try:
                    msg = await channel.fetch_message(self.assignment["message_id"])
                    await msg.delete()
                except discord.NotFound:
                    pass
                except Exception as e:
                    print(f"Error deleting task message: {e}")

        # Send notification to the staff if it was claimed
        if self.assignment.get("staff_id") and self.assignment.get("ticket_channel_id"):
            ticket_channel = interaction.client.get_channel(self.assignment["ticket_channel_id"])
            if ticket_channel:
                try:
                    await ticket_channel.send(
                        f"⚠️ <@{self.assignment['staff_id']}> Tugas **{self.assignment['manga']} Ch {self.assignment['chapter']}** telah ditarik/dibatalkan oleh Admin.\n"
                        f"**Alasan:** {reason_text}"
                    )
                except Exception as e:
                    print(f"Error sending revoke notification: {e}")

        await interaction.followup.send(f"✅ Tugas #{assignment_id} ({self.assignment['manga']} Ch {self.assignment['chapter']}) berhasil ditarik.")
