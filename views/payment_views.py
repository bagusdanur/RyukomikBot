from io import BytesIO
import logging

import discord

import payment_service as payments
from config import DASHBOARD_URL, STAFF_LOG_CHANNEL_ID
from helpers.utils import format_currency, is_admin, is_staff
from invoice_pdf import render_paid_invoice

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

    @discord.ui.button(label="Ganti / Upload QRIS", style=discord.ButtonStyle.success, row=1)
    async def qris(self, interaction, _button):
        try:
            await interaction.response.send_modal(QrisMethodModal())
        except discord.HTTPException as error:
            logger.exception("Discord rejected QRIS modal")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"Form QRIS gagal dibuka: {error}", ephemeral=True
                )


class QrisMethodModal(discord.ui.Modal, title="Ganti / Upload QRIS"):
    def __init__(self):
        super().__init__()
        self.account_name_input = discord.ui.TextInput(
            custom_id="payment_qris_name", min_length=2, max_length=100,
            placeholder="Nama sesuai QRIS",
        )
        self.qris_file_input = discord.ui.FileUpload(
            custom_id="payment_qris_file", min_values=1, max_values=1, required=True
        )
        self.add_item(discord.ui.Label(
            text="Nama Pemilik QRIS", component=self.account_name_input
        ))
        self.add_item(discord.ui.Label(
            text="Gambar QRIS",
            description="PNG, JPG, atau WebP • maksimal 5 MB",
            component=self.qris_file_input,
        ))

    async def on_submit(self, interaction):
        if not is_staff(interaction.user):
            return await interaction.response.send_message("Hanya staff yang dapat menyimpan QRIS.", ephemeral=True)
        attachment = self.qris_file_input.values[0]
        await interaction.response.defer(ephemeral=True)
        try:
            content = await attachment.read()
            method_id = await payments.replace_qris_method(
                interaction.user.id, "QRIS", self.account_name_input.value,
                content, attachment.content_type or "",
            )
            await interaction.followup.send(
                f"QRIS berhasil diganti dan dijadikan metode utama (metode #{method_id}). "
                "Invoice lama tetap memakai snapshot tujuan sebelumnya.",
                ephemeral=True,
            )
        except (ValueError, RuntimeError, discord.HTTPException) as error:
            await interaction.followup.send(f"Upload QRIS gagal: {error}", ephemeral=True)


async def show_payment_methods(interaction):
    methods = await payments.list_methods(interaction.user.id)
    description = "Belum ada metode pembayaran." if not methods else "\n".join(
        f"**#{item['id']}** {item['provider']} • {item['account_name']} • "
        f"{'QRIS' if item['method_type'] == 'qris' else item['masked_account']}"
        f"{' • Utama' if item['is_default'] else ''}"
        for item in methods
    )
    await interaction.response.send_message(
        embed=discord.Embed(title="Metode Pembayaran Saya", description=description, color=discord.Color.blue()),
        view=PaymentMethodsView(methods), ephemeral=True,
    )


async def show_payout_request(interaction):
    methods = await payments.list_methods(interaction.user.id)
    if not methods:
        return await interaction.response.send_message(
            "Atur rekening bank, e-wallet, atau QRIS terlebih dahulu.", ephemeral=True
        )
    await interaction.response.send_message(
        embed=discord.Embed(
            title="Ambil Gaji Sekarang",
            description="Pilih tujuan transfer. Hanya saldo approved yang belum ditagihkan yang akan dimasukkan.",
            color=discord.Color.gold(),
        ),
        view=PayoutMethodView(methods), ephemeral=True,
    )


class IncomeMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Atur Metode", style=discord.ButtonStyle.secondary, custom_id="income:methods:v1")
    async def methods(self, interaction, _button):
        await show_payment_methods(interaction)

    @discord.ui.button(label="Ambil Gaji Sekarang", style=discord.ButtonStyle.success, custom_id="income:request:v1")
    async def request(self, interaction, _button):
        await show_payout_request(interaction)

    @discord.ui.button(label="Riwayat Pembayaran", style=discord.ButtonStyle.primary, custom_id="income:history:v1")
    async def history(self, interaction, _button):
        rows = await payments.list_staff_payouts(interaction.user.id)
        description = "Belum ada riwayat pembayaran." if not rows else "\n".join(
            f"**{item['invoice_number']}** • {format_currency(item['total_amount'])} • "
            f"{'Menunggu rekening' if item['status'] == 'awaiting_method' else item['status']}"
            for item in rows
        )
        await interaction.response.send_message(
            embed=discord.Embed(title="Riwayat Gaji", description=description, color=discord.Color.blue()),
            ephemeral=True,
        )


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


async def send_paid_invoice_to_ticket(interaction, payout_id):
    detail = await payments.payout_detail(payout_id, include_sensitive=True)
    if not detail:
        return False, "Data invoice tidak ditemukan."
    if not interaction.guild:
        return False, "Guild tidak tersedia."
    from helpers.utils import find_ticket
    channel = await find_ticket(interaction.guild, int(detail["staff_id"]))
    if not channel:
        error = "Tiket privat staff tidak ditemukan."
        await payments.record_invoice_delivery(payout_id, error=error)
        return False, error
    staff = interaction.guild.get_member(int(detail["staff_id"]))
    admin_name = getattr(interaction.user, "display_name", str(interaction.user))
    try:
        pdf = render_paid_invoice(
            detail, staff_name=staff.display_name if staff else None, admin_name=admin_name
        )
        embed = discord.Embed(
            title="Invoice Gaji Lunas",
            description=f"Pembayaran **{format_currency(detail['total_amount'])}** telah ditransfer.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Invoice", value=detail["invoice_number"], inline=False)
        embed.add_field(name="Periode", value=detail["period"], inline=True)
        embed.add_field(name="Chapter", value=str(detail["chapter_count"]), inline=True)
        message = await channel.send(
            content=staff.mention if staff else None, embed=embed,
            file=discord.File(BytesIO(pdf), filename=f"{detail['invoice_number']}.pdf"),
        )
        await payments.record_invoice_delivery(payout_id, message_id=message.id)
        return True, None
    except Exception as error:
        logger.exception("Failed to send paid invoice %s", payout_id)
        message = str(error)[:500]
        await payments.record_invoice_delivery(payout_id, error=message)
        return False, message


class ConfirmTransferModal(discord.ui.Modal, title="Konfirmasi Transfer Gaji"):
    amount = discord.ui.TextInput(
        label="Ketik nominal transfer", placeholder="Contoh: 60000", max_length=15
    )
    destination_last4 = discord.ui.TextInput(
        label="4 karakter terakhir tujuan", placeholder="Contoh: 1234 atau QRIS",
        min_length=4, max_length=4,
    )

    def __init__(self, payout_id):
        super().__init__()
        self.payout_id = payout_id

    async def on_submit(self, interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya administrator.", ephemeral=True)
        detail = await payments.payout_detail(self.payout_id, include_sensitive=True)
        if not detail or detail["status"] != "issued":
            return await interaction.response.send_message(
                "Permintaan sudah diproses atau tidak ditemukan.", ephemeral=True
            )
        destination = detail["method"].get("account_number") or "QRIS"
        expected = "".join(char for char in str(destination) if char.isalnum())[-4:]
        try:
            typed_amount = int(self.amount.value.replace(".", "").replace(",", "").strip())
        except ValueError:
            typed_amount = -1
        if typed_amount != int(detail["total_amount"]) or self.destination_last4.value.casefold() != expected.casefold():
            return await interaction.response.send_message(
                "Konfirmasi ditolak: nominal atau 4 karakter terakhir tujuan tidak cocok.",
                ephemeral=True,
            )
        try:
            await payments.pay_payout(self.payout_id, interaction.user.id)
        except ValueError as error:
            return await interaction.response.send_message(str(error), ephemeral=True)
        sent, error = await send_paid_invoice_to_ticket(interaction, self.payout_id)
        description = "Transfer dikonfirmasi dan invoice PDF dikirim ke tiket staff."
        view = None
        if not sent:
            description = f"Transfer berhasil, tetapi invoice gagal dikirim: {error}"
            view = InvoiceRetryView(self.payout_id)
        await interaction.response.edit_message(
            embed=discord.Embed(title="Pembayaran Selesai", description=description, color=discord.Color.green()),
            view=view,
        )


class PayPayoutDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"payout:pay:(?P<payout_id>\d+):v1"):
    def __init__(self, payout_id):
        self.payout_id = payout_id
        super().__init__(discord.ui.Button(label="Sudah Ditransfer", style=discord.ButtonStyle.success, custom_id=f"payout:pay:{payout_id}:v1"))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["payout_id"]))
    async def callback(self, interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya administrator.", ephemeral=True)
        detail = await payments.payout_detail(self.payout_id, include_sensitive=True)
        if not detail or detail["status"] != "issued":
            return await interaction.response.send_message("Permintaan sudah diproses.", ephemeral=True)
        destination = detail["method"].get("account_number") or "QRIS"
        await interaction.response.send_modal(ConfirmTransferModal(self.payout_id))


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


class RetryInvoiceDynamic(discord.ui.DynamicItem[discord.ui.Button], template=r"payout:invoice-retry:(?P<payout_id>\d+):v1"):
    def __init__(self, payout_id):
        self.payout_id = payout_id
        super().__init__(discord.ui.Button(
            label="Kirim Ulang Invoice", style=discord.ButtonStyle.primary,
            custom_id=f"payout:invoice-retry:{payout_id}:v1",
        ))
    @classmethod
    async def from_custom_id(cls, interaction, item, match): return cls(int(match["payout_id"]))
    async def callback(self, interaction):
        if not is_admin(interaction.user):
            return await interaction.response.send_message("Hanya administrator.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        sent, error = await send_paid_invoice_to_ticket(interaction, self.payout_id)
        await interaction.followup.send(
            "Invoice berhasil dikirim ulang." if sent else f"Invoice masih gagal dikirim: {error}",
            ephemeral=True,
        )


class InvoiceRetryView(discord.ui.View):
    def __init__(self, payout_id):
        super().__init__(timeout=None)
        self.add_item(RetryInvoiceDynamic(payout_id))


class PayoutAdminView(discord.ui.View):
    def __init__(self, payout_id, status="issued"):
        super().__init__(timeout=None)
        if status == "issued":
            self.add_item(PayPayoutDynamic(payout_id))
            self.add_item(RejectPayoutDynamic(payout_id))
        self.add_item(discord.ui.Button(label="Buka Dashboard", style=discord.ButtonStyle.link, url=f"{DASHBOARD_URL}/?page=payouts&id={payout_id}"))
