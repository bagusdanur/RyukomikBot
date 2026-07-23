import asyncio
import logging

import discord

import payment_service as payments
from config import DASHBOARD_URL, STAFF_LOG_CHANNEL_ID
from helpers.utils import format_currency, is_admin, is_staff

logger = logging.getLogger(__name__)


def method_label(method, sensitive=False):
    account = method.get("account_number") if sensitive else method.get("masked_account")
    detail = "QRIS" if method["method_type"] == "qris" else account
    default = " • Utama" if method.get("is_default") else ""
    return f"{method['provider']} • {method['account_name']} • {detail}{default}"


class AccountMethodModal(discord.ui.Modal):
    provider = discord.ui.TextInput(label="Bank / Provider", placeholder="BCA, BRI, DANA, GoPay...", max_length=40)
    account_name = discord.ui.TextInput(label="Nama Pemilik", max_length=100)
    account_number = discord.ui.TextInput(label="Nomor Rekening / E-wallet", min_length=5, max_length=40)

    def __init__(self, method_type):
        self.method_type = method_type
        super().__init__(title="Tambah Rekening Bank" if method_type == "bank" else "Tambah E-wallet")

    async def on_submit(self, interaction):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Hanya staff yang dapat menyimpan metode pembayaran.", ephemeral=True)
        try:
            method_id = await payments.create_method(
                interaction.user.id, self.method_type, self.provider.value,
                self.account_name.value, self.account_number.value,
            )
        except (ValueError, RuntimeError) as error:
            return await interaction.response.send_message(str(error), ephemeral=True)
        await interaction.response.send_message(
            f"Metode pembayaran **{self.provider.value} • {payments.mask_account(self.account_number.value)}** tersimpan (ID #{method_id}).",
            ephemeral=True,
        )


class PaymentMethodManageSelect(discord.ui.Select):
    def __init__(self, methods):
        self.methods = {str(item["id"]): item for item in methods}
        options = []
        for item in methods[:12]:
            options.append(discord.SelectOption(
                label=f"Jadikan utama: {method_label(item)}"[:100], value=f"default:{item['id']}"
            ))
            options.append(discord.SelectOption(
                label=f"Nonaktifkan: {item['provider']} • #{item['id']}"[:100], value=f"disable:{item['id']}"
            ))
        super().__init__(
            placeholder="Kelola metode pembayaran",
            options=options,
        )

    async def callback(self, interaction):
        action, raw_id = self.values[0].split(":", 1)
        try:
            if action == "default":
                await payments.set_default_method(interaction.user.id, int(raw_id))
                message = "Metode pembayaran utama berhasil diperbarui."
            else:
                await payments.deactivate_method(interaction.user.id, int(raw_id))
                message = "Metode pembayaran dinonaktifkan."
        except (ValueError, RuntimeError) as error:
            return await interaction.response.send_message(str(error), ephemeral=True)
        await interaction.response.send_message(message, ephemeral=True)


class PaymentMethodsView(discord.ui.View):
    def __init__(self, methods):
        super().__init__(timeout=300)
        if methods:
            self.add_item(PaymentMethodManageSelect(methods))

    @discord.ui.button(label="Tambah Bank", style=discord.ButtonStyle.primary, row=1)
    async def bank(self, interaction, _button):
        await interaction.response.send_modal(AccountMethodModal("bank"))

    @discord.ui.button(label="Tambah E-wallet", style=discord.ButtonStyle.primary, row=1)
    async def ewallet(self, interaction, _button):
        await interaction.response.send_modal(AccountMethodModal("ewallet"))

    @discord.ui.button(label="Upload QRIS", style=discord.ButtonStyle.success, row=1)
    async def qris(self, interaction, _button):
        await interaction.response.send_message(
            "Kirim **satu gambar QRIS** (PNG/JPG/WebP, maksimal 5 MB) ke tiket ini dalam 2 menit. "
            "Pesan gambarnya akan dihapus setelah tersimpan privat di R2.",
            ephemeral=True,
        )
        try:
            message = await interaction.client.wait_for(
                "message", timeout=120,
                check=lambda item: item.author.id == interaction.user.id and item.channel.id == interaction.channel.id and len(item.attachments) == 1,
            )
        except asyncio.TimeoutError:
            return await interaction.followup.send("Waktu upload QRIS habis. Tekan tombol Upload QRIS untuk mencoba lagi.", ephemeral=True)
        attachment = message.attachments[0]
        try:
            content = await attachment.read()
            method_id = await payments.create_qris_method(
                interaction.user.id, "QRIS", interaction.user.display_name,
                content, attachment.content_type or "",
            )
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            await interaction.followup.send(f"QRIS berhasil disimpan secara privat (metode #{method_id}).", ephemeral=True)
        except (ValueError, RuntimeError, discord.HTTPException) as error:
            await interaction.followup.send(f"Upload QRIS gagal: {error}", ephemeral=True)


class PayoutMethodSelect(discord.ui.Select):
    def __init__(self, methods):
        self.methods = {str(item["id"]): item for item in methods}
        super().__init__(
            placeholder="Pilih tujuan transfer",
            options=[discord.SelectOption(label=method_label(item)[:100], value=str(item["id"])) for item in methods],
        )

    async def callback(self, interaction):
        method = self.methods[self.values[0]]
        embed = discord.Embed(
            title="Konfirmasi Ambil Gaji",
            description="Saldo approved yang belum pernah masuk invoice akan diajukan kepada administrator.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Tujuan", value=method_label(method), inline=False)
        embed.set_footer(text="Transfer tidak otomatis. Status menjadi lunas setelah admin mengonfirmasi.")
        await interaction.response.edit_message(embed=embed, view=ConfirmPayoutView(int(self.values[0])))


class PayoutMethodView(discord.ui.View):
    def __init__(self, methods):
        super().__init__(timeout=300)
        self.add_item(PayoutMethodSelect(methods))


class ConfirmPayoutView(discord.ui.View):
    def __init__(self, method_id):
        super().__init__(timeout=180)
        self.method_id = method_id

    @discord.ui.button(label="Konfirmasi Pengajuan", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, _button):
        await interaction.response.defer(ephemeral=True)
        try:
            payout = await payments.create_payout(interaction.user.id, self.method_id, "instant", actor_id=interaction.user.id)
        except (ValueError, RuntimeError) as error:
            return await interaction.followup.send(str(error), ephemeral=True)
        await interaction.followup.send(
            f"Permintaan gaji **{format_currency(payout['total_amount'])}** berhasil dibuat. "
            "Tunggu administrator mengonfirmasi transfer.",
            ephemeral=True,
        )
        channel = interaction.guild.get_channel(STAFF_LOG_CHANNEL_ID) if interaction.guild else None
        if channel:
            embed = discord.Embed(
                title=f"Permintaan Gaji #{payout['id']}",
                description=f"{interaction.user.mention} meminta pencairan langsung.",
                color=discord.Color.gold(),
            )
            embed.add_field(name="Total", value=format_currency(payout["total_amount"]), inline=True)
            embed.add_field(name="Chapter", value=str(payout["chapter_count"]), inline=True)
            embed.add_field(name="Invoice", value=payout["invoice_number"], inline=False)
            await channel.send(embed=embed, view=PayoutAdminView(payout["id"]))


class RejectPayoutModal(discord.ui.Modal, title="Tolak Pengajuan Gaji"):
    reason = discord.ui.TextInput(label="Alasan", style=discord.TextStyle.paragraph, min_length=3, max_length=500)

    def __init__(self, payout_id):
        super().__init__()
        self.payout_id = payout_id

    async def on_submit(self, interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya administrator.", ephemeral=True)
        try:
            payout = await payments.reject_payout(self.payout_id, interaction.user.id, self.reason.value)
        except ValueError as error:
            return await interaction.response.send_message(str(error), ephemeral=True)
        await interaction.response.edit_message(
            embed=discord.Embed(title="Pengajuan Ditolak", description=self.reason.value, color=discord.Color.red()),
            view=None,
        )
        await notify_staff_ticket(interaction, payout["staff_id"], "Pengajuan Gaji Ditolak", self.reason.value, discord.Color.red())


async def notify_staff_ticket(interaction, staff_id, title, description, color):
    if not interaction.guild:
        return
    from helpers.utils import find_ticket
    channel = await find_ticket(interaction.guild, int(staff_id))
    if channel:
        member = interaction.guild.get_member(int(staff_id))
        await channel.send(content=member.mention if member else None, embed=discord.Embed(title=title, description=description, color=color))


class PayPayoutDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"payout:pay:(?P<payout_id>\d+):v1"):
    def __init__(self, payout_id):
        self.payout_id = payout_id
        super().__init__(discord.ui.Button(label="Sudah Ditransfer", style=discord.ButtonStyle.success, custom_id=f"payout:pay:{payout_id}:v1"))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["payout_id"]))
    async def callback(self, interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya administrator.", ephemeral=True)
        try:
            payout = await payments.pay_payout(self.payout_id, interaction.user.id)
        except ValueError as error:
            return await interaction.response.send_message(str(error), ephemeral=True)
        await interaction.response.edit_message(embed=discord.Embed(title="Pembayaran Selesai", description="Transfer sudah dikonfirmasi.", color=discord.Color.green()), view=None)
        await notify_staff_ticket(interaction, payout["staff_id"], "Gaji Sudah Ditransfer", f"Pembayaran **{format_currency(payout['total_amount'])}** sudah dikonfirmasi administrator.", discord.Color.green())


class RejectPayoutDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"payout:reject:(?P<payout_id>\d+):v1"):
    def __init__(self, payout_id):
        self.payout_id = payout_id
        super().__init__(discord.ui.Button(label="Tolak", style=discord.ButtonStyle.danger, custom_id=f"payout:reject:{payout_id}:v1"))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["payout_id"]))
    async def callback(self, interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya administrator.", ephemeral=True)
        await interaction.response.send_modal(RejectPayoutModal(self.payout_id))


class PayoutAdminView(discord.ui.View):
    def __init__(self, payout_id):
        super().__init__(timeout=None)
        self.add_item(PayPayoutDynamic(payout_id))
        self.add_item(RejectPayoutDynamic(payout_id))
        self.add_item(discord.ui.Button(label="Buka Dashboard", style=discord.ButtonStyle.link, url=f"{DASHBOARD_URL}/?page=payouts&id={payout_id}"))
