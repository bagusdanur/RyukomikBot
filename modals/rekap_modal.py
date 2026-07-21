import discord
from helpers.utils import is_admin, format_currency, get_current_period
from views.select_views import ConfirmPayView
import database as db


class RekapModal(discord.ui.Modal, title="Rekap Pembayaran"):
    """Modal for payment recap."""
    
    function_name = "RekapModal"
    
    staff_id = discord.ui.TextInput(
        label="Staff ID",
        placeholder="ID Discord staff",
        style=discord.TextStyle.short,
        required=True
    )
    
    period = discord.ui.TextInput(
        label="Periode",
        placeholder="YYYY-MM (contoh: 2024-01)",
        style=discord.TextStyle.short,
        required=False
    )
    
    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Hanya admin yang bisa menggunakan fitur ini!",
                ephemeral=True
            )
        
        # Parse period
        period = self.period.value if self.period.value else get_current_period()
        
        # Validate period format
        try:
            parts = period.split("-")
            if len(parts) != 2 or not all(p.isdigit() for p in parts):
                raise ValueError
            year, month = int(parts[0]), int(parts[1])
            if month < 1 or month > 12:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(
                "❌ Format periode harus YYYY-MM (contoh: 2024-01)!",
                ephemeral=True
            )
        
        # Get staff
        try:
            staff_id = int(self.staff_id.value)
        except ValueError:
            return await interaction.response.send_message(
                "❌ Staff ID harus berupa angka!",
                ephemeral=True
            )
        
        staff = interaction.guild.get_member(staff_id)
        if not staff:
            return await interaction.response.send_message(
                "❌ Staff tidak ditemukan di server!",
                ephemeral=True
            )
        
        # Get stats
        stats = await db.get_staff_stats(staff_id, period)
        
        # Get detailed assignments
        db_conn = await db.get_db()
        try:
            cursor = await db_conn.execute("""
                SELECT * FROM assignments 
                WHERE staff_id = ? AND paid_period = ? AND status = 'approved'
                ORDER BY approved_at DESC
            """, (staff_id, period))
            rows = await cursor.fetchall()
            assignments = [dict(row) for row in rows]
        finally:
            await db_conn.close()
        
        if not assignments:
            return await interaction.response.send_message(
                f"📋 Tidak ada tugas yang disetujui untuk **{staff.display_name}** di periode **{period}**.",
                ephemeral=True
            )
        
        # Build recap embed
        embed = discord.Embed(
            title="📊 Rekap Pembayaran",
            description=f"**{staff.display_name}** - Periode {period}",
            color=discord.Color.gold()
        )
        
        # Summary
        embed.add_field(
            name="Ringkasan",
            value=(
                f"📊 Total Tugas: {stats['total']}\n"
                f"✅ Diterima: {stats['total']}\n"
                f"💰 Total: {format_currency(stats['total_earned'])}"
            ),
            inline=False
        )
        
        # Detailed list
        detail_text = ""
        for a in assignments:
            detail_text += f"• {a['manga']} Ch.{a['chapter']}: {format_currency(a['final_rate'])}\n"
        
        embed.add_field(name="Detail Tugas", value=detail_text, inline=False)
        
        # Create payment view
        view = ConfirmPayView(
            staff_id=staff_id,
            period=period,
            total=stats["total_earned"],
            count=len(assignments)
        )
        
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )
