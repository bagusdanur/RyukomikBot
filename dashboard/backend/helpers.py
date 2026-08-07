"""Shared Discord/staff helper functions used across multiple routers."""

import hashlib
import json
import re
import time
from datetime import datetime

import aiohttp

from config import GUILD_ID, ROLE_ADMIN_ID, ROLE_STAFF_ID, REKRUT_CAT_ID, STAFF_LOG_CHANNEL_ID, TOKEN
from dashboard.backend.deps import (
    _staff_cache,
    _staff_cache_lock,
    dashboard_db,
    DEV_BYPASS,
    DEFAULT_RATE_RANGES,
)


async def discord_api(method: str, path: str, payload=None):
    if not TOKEN:
        return None
    async with aiohttp.ClientSession() as session:
        async with session.request(
            method,
            f"https://discord.com/api/v10{path}",
            headers={"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if 200 <= response.status < 300:
                if response.status == 204:
                    return {}
                try:
                    return await response.json()
                except (aiohttp.ContentTypeError, json.JSONDecodeError):
                    return {}
            return None


async def fetch_member(user_id: int):
    if not TOKEN:
        return None
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{user_id}",
            headers={"Authorization": f"Bot {TOKEN}"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            return await response.json() if response.status == 200 else None


def discord_avatar(member: dict) -> str | None:
    user = member.get("user", {})
    avatar = member.get("avatar") or user.get("avatar")
    if not avatar:
        return None
    if member.get("avatar"):
        return f"https://cdn.discordapp.com/guilds/{GUILD_ID}/users/{user['id']}/avatars/{avatar}.png?size=128"
    return f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.png?size=128"


def member_profile(member: dict):
    discord_user = member.get("user", {})
    if not discord_user.get("id"):
        return None
    return {
        "id": str(discord_user["id"]),
        "username": member.get("nick") or discord_user.get("global_name") or discord_user.get("username", "Staff"),
        "avatar": discord_avatar(member),
    }


async def cache_staff_profile(profile: dict):
    connection = await dashboard_db()
    try:
        await connection.execute("""
            INSERT INTO dashboard_staff_cache(staff_id,username,avatar,updated_at)
            VALUES(?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(staff_id) DO UPDATE SET username=excluded.username,
                avatar=excluded.avatar, updated_at=CURRENT_TIMESTAMP
        """, (profile["id"], profile["username"], profile.get("avatar")))
        await connection.commit()
    finally:
        await connection.close()


async def staff_directory(force=False):
    if DEV_BYPASS:
        connection = await dashboard_db()
        try:
            rows = await (await connection.execute(
                "SELECT DISTINCT staff_id FROM assignments WHERE staff_id IS NOT NULL"
            )).fetchall()
            return [{"id": str(row[0]), "username": f"Staff {row[0]}", "avatar": None} for row in rows]
        finally:
            await connection.close()
    if not force and _staff_cache["items"] and time.monotonic() < _staff_cache["expires_at"]:
        return _staff_cache["items"]
    async with _staff_cache_lock:
        if not force and _staff_cache["items"] and time.monotonic() < _staff_cache["expires_at"]:
            return _staff_cache["items"]
        connection = await dashboard_db()
        try:
            cached = await (await connection.execute(
                "SELECT staff_id id, username, avatar FROM dashboard_staff_cache"
            )).fetchall()
            known = await (await connection.execute(
                "SELECT DISTINCT staff_id FROM assignments WHERE staff_id IS NOT NULL"
            )).fetchall()
        finally:
            await connection.close()
        profiles = {row["id"]: dict(row) for row in cached}
        members = await discord_api("GET", f"/guilds/{GUILD_ID}/members?limit=1000")
        if members is None and profiles:
            result = sorted(profiles.values(), key=lambda item: item["username"].casefold())
            _staff_cache.update(items=result, expires_at=time.monotonic() + 120, updated_at=datetime.now().isoformat())
            return result
        if members is not None:
            profiles = {}
        for member in members or []:
            roles = {int(role) for role in member.get("roles", [])}
            if ROLE_STAFF_ID not in roles:
                continue
            profile = member_profile(member)
            if profile:
                profiles[profile["id"]] = profile
        for row in known:
            if row["staff_id"] in profiles:
                continue
            profile = member_profile(await fetch_member(row["staff_id"]) or {})
            if profile:
                profiles[profile["id"]] = profile
        for profile in profiles.values():
            await cache_staff_profile(profile)
        result = sorted(profiles.values(), key=lambda item: item["username"].casefold())
        _staff_cache.update(items=result, expires_at=time.monotonic() + 600, updated_at=datetime.now().isoformat())
        return result


async def enrich_staff(rows):
    profiles = {str(item["id"]): item for item in await staff_directory()}
    enriched = []
    for row in rows:
        item = dict(row)
        profile = profiles.get(str(item.get("staff_id")), {})
        item["staff_name"] = profile.get("username") or f"Staff {item.get('staff_id') or 'belum dipilih'}"
        item["staff_avatar"] = profile.get("avatar")
        if item.get("staff_id") is not None:
            item["staff_id"] = str(item["staff_id"])
        enriched.append(item)
    return enriched


def resolve_staff_id(staff_id: str, profiles: dict) -> str | None:
    if staff_id in profiles:
        return staff_id
    for pid in profiles:
        if pid[:14] == staff_id[:14]:
            return pid
    return None


async def resolve_staff_id_with_fallback(staff_id: str, profiles: dict) -> str | None:
    result = resolve_staff_id(staff_id, profiles)
    if result:
        return result
    connection = await dashboard_db()
    try:
        row = await (await connection.execute(
            "SELECT staff_id FROM dashboard_staff_cache WHERE staff_id=?",
            (staff_id,),
        )).fetchone()
        if row:
            return str(row[0])
        row = await (await connection.execute(
            "SELECT staff_id FROM dashboard_staff_cache WHERE SUBSTR(staff_id,1,14)=?",
            (staff_id[:14],),
        )).fetchone()
        if row:
            return str(row[0])
    finally:
        await connection.close()
    return None


async def resolve_staff_ticket_channel(staff_id: int, assignment_id: int) -> str | None:
    connection = await dashboard_db()
    try:
        row = await (await connection.execute(
            "SELECT ticket_channel_id FROM assignments WHERE staff_id=? AND ticket_channel_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (staff_id,),
        )).fetchone()
    finally:
        await connection.close()
    channel_id = str(row[0]) if row and row[0] else None
    if not channel_id:
        channels = await discord_api("GET", f"/guilds/{GUILD_ID}/channels") or []
        for channel in channels:
            if channel.get("type") != 0 or "tiket-" not in str(channel.get("name", "")).casefold():
                continue
            topic = str(channel.get("topic") or "")
            owns_overwrite = any(
                str(overwrite.get("id")) == str(staff_id) and overwrite.get("type") == 1
                for overwrite in channel.get("permission_overwrites", [])
            )
            if str(staff_id) in topic or owns_overwrite:
                channel_id = str(channel["id"])
                break
    if channel_id:
        connection = await dashboard_db()
        try:
            await connection.execute("UPDATE assignments SET ticket_channel_id=? WHERE id=?", (channel_id, assignment_id))
            await connection.commit()
        finally:
            await connection.close()
    return channel_id


async def role_rate_range(role: str) -> tuple[int, int]:
    connection = await dashboard_db()
    try:
        row = await (await connection.execute(
            "SELECT base_rate,min_rate,max_rate FROM payrates WHERE role=?",
            (role,),
        )).fetchone()
    finally:
        await connection.close()
    default_min, default_max = DEFAULT_RATE_RANGES[role]
    if not row:
        return default_min, default_max
    return (
        int(row["min_rate"] or row["base_rate"] or default_min),
        int(row["max_rate"] or default_max),
    )


def pair_panel_payload(project: dict) -> dict:
    state_labels = {
        "waiting_tl": "Menunggu TL", "ready_for_ts": "Siap TS",
        "tl_revision": "Perbaikan TL", "ts_revision": "Perbaikan TS",
        "both_revision": "Perbaikan TL + TS", "final_review": "Review Final",
        "completed": "Selesai",
    }
    progress = "\n".join(
        f"{'✅' if item['status'] == 'completed' else '🔄' if 'revision' in item['status'] else '•'} "
        f"**Chapter {item['chapter']}** — {state_labels.get(item['status'], item['status'])}"
        for item in project["chapters"]
    )
    return {
        "embeds": [{
            "title": f"Kolaborasi TL–TS • {project['manga']}",
            "description": (
                f"<@{project['tl_staff_id']}> sebagai **Translator** dan <@{project['ts_staff_id']}> "
                "sebagai **Typesetter** bekerja dalam satu ruang.\n"
                "Gaji setiap chapter dilepas untuk keduanya setelah hasil final disetujui Administrator."
            ),
            "color": 6253567,
            "fields": [
                {"name": "Progress", "value": progress, "inline": False},
                {"name": "Rate TL", "value": f"Rp {project['tl_rate_per_chapter']:,.0f}".replace(",", "."), "inline": True},
                {"name": "Rate TS", "value": f"Rp {project['ts_rate_per_chapter']:,.0f}".replace(",", "."), "inline": True},
                {"name": "Deadline", "value": project.get("deadline_at") or "Tidak ditentukan", "inline": True},
            ],
            "footer": {"text": f"Pair Project #{project['id']} • Gunakan tombol sesuai peran"},
        }],
        "components": [{"type": 1, "components": [
            {"type": 2, "style": 1, "label": "Submit Hasil TL", "custom_id": f"pair:tl:{project['id']}:v2"},
            {"type": 2, "style": 3, "label": "Submit Final TS", "custom_id": f"pair:ts:{project['id']}:v2"},
            {"type": 2, "style": 4, "label": "Minta Perbaikan TL", "custom_id": f"pair:tl-revision:{project['id']}:v2"},
            {"type": 2, "style": 2, "label": "Lihat Status Chapter", "custom_id": f"pair:status:{project['id']}:v2"},
            {"type": 2, "style": 2, "label": "Download RAW", "custom_id": f"pair:raw:{project['id']}:v2"},
        ]}],
        "allowed_mentions": {"users": [str(project["tl_staff_id"]), str(project["ts_staff_id"])]},
    }


async def create_pair_workspace(project_id: int) -> tuple[str, str]:
    import pair_workflow as pair_service
    project = await pair_service.get_project(project_id)
    if not project:
        raise RuntimeError("Pair project tidak ditemukan setelah dibuat.")
    reusable = await pair_service.find_reusable_workspace(project["manga"])
    channel = None
    created_new_channel = False
    if reusable:
        channel = await discord_api("GET", f"/channels/{reusable['channel_id']}")
    if channel:
        slug = re.sub(r"[^a-z0-9]+", "-", project["manga"].casefold()).strip("-")[:70] or "project"
        await discord_api("PATCH", f"/channels/{channel['id']}", {
            "name": f"🔒・project-{slug}",
            "topic": f"Ruang permanen {project['manga']} | Pair aktif #{project_id} | TL:{project['tl_staff_id']} | TS:{project['ts_staff_id']}",
        })
        staff_allow = str((1 << 10) | (1 << 11) | (1 << 14) | (1 << 15) | (1 << 16))
        for staff_id in {str(project["tl_staff_id"]), str(project["ts_staff_id"])}:
            await discord_api("PUT", f"/channels/{channel['id']}/permissions/{staff_id}", {
                "type": 1, "allow": staff_allow, "deny": "0",
            })
        current_staff = {str(project["tl_staff_id"]), str(project["ts_staff_id"])}
        for overwrite in channel.get("permission_overwrites", []):
            overwrite_id = str(overwrite.get("id") or "")
            if int(overwrite.get("type", 0)) == 1 and overwrite_id not in current_staff:
                await discord_api("DELETE", f"/channels/{channel['id']}/permissions/{overwrite_id}")
        await discord_api("PUT", f"/channels/{channel['id']}/permissions/{ROLE_STAFF_ID}", {
            "type": 0, "allow": "0", "deny": str(1 << 10),
        })
        if reusable.get("panel_message_id"):
            await discord_api("DELETE", f"/channels/{channel['id']}/pins/{reusable['panel_message_id']}")
    else:
        slug = re.sub(r"[^a-z0-9]+", "-", project["manga"].casefold()).strip("-")[:70] or "project"
        staff_allow = str((1 << 10) | (1 << 11) | (1 << 14) | (1 << 15) | (1 << 16))
        admin_allow = str(int(staff_allow) | (1 << 4) | (1 << 13))
        channel = await discord_api("POST", f"/guilds/{GUILD_ID}/channels", {
            "name": f"🔒・project-{slug}",
            "type": 0,
            "parent_id": str(REKRUT_CAT_ID),
            "topic": f"Ruang permanen {project['manga']} | Pair aktif #{project_id} | TL:{project['tl_staff_id']} | TS:{project['ts_staff_id']}",
            "permission_overwrites": [
                {"id": str(GUILD_ID), "type": 0, "deny": str(1 << 10), "allow": "0"},
                {"id": str(ROLE_STAFF_ID), "type": 0, "deny": str(1 << 10), "allow": "0"},
                {"id": str(project["tl_staff_id"]), "type": 1, "allow": staff_allow, "deny": "0"},
                {"id": str(project["ts_staff_id"]), "type": 1, "allow": staff_allow, "deny": "0"},
                {"id": str(ROLE_ADMIN_ID), "type": 0, "allow": admin_allow, "deny": "0"},
            ],
        })
        if not channel:
            raise RuntimeError("Discord gagal membuat channel proyek privat.")
        created_new_channel = True
    message = await discord_api("POST", f"/channels/{channel['id']}/messages", {
        "content": f"<@{project['tl_staff_id']}> <@{project['ts_staff_id']}> ruang kolaborasi kalian sudah siap.",
        **pair_panel_payload(project),
    })
    if not message:
        if created_new_channel:
            await discord_api("DELETE", f"/channels/{channel['id']}")
        raise RuntimeError("Discord gagal membuat panel pair.")
    await discord_api("PUT", f"/channels/{channel['id']}/pins/{message['id']}")
    await pair_service.set_workspace(project_id, int(channel["id"]), int(message["id"]))
    if reusable and str(reusable["channel_id"]) == str(channel["id"]):
        await pair_service.record_workspace_reuse(project_id, int(reusable["id"]))
    return str(channel["id"]), str(message["id"])


async def send_payout_ticket_notice(staff_id: int, title: str, description: str, success: bool):
    import operations
    connection = await dashboard_db()
    try:
        row = await (await connection.execute("""SELECT ticket_channel_id FROM assignments
            WHERE staff_id=? AND ticket_channel_id IS NOT NULL ORDER BY id DESC LIMIT 1""", (staff_id,))).fetchone()
    finally:
        await connection.close()
    if DEV_BYPASS:
        return True
    if not row:
        return False
    message = {
        "content": f"<@{staff_id}>",
        "embeds": [{"title": title, "description": description, "color": 5763719 if success else 15548997}],
    }
    sent = bool(await discord_api("POST", f"/channels/{row['ticket_channel_id']}/messages", message))
    if not sent:
        await operations.enqueue_notification(
            f"payout:{staff_id}:{hashlib.sha256((title+description).encode()).hexdigest()[:16]}",
            "payout_status", row["ticket_channel_id"],
            {"content": message["content"], "embed": message["embeds"][0]},
        )
    return sent


async def send_paid_invoice_pdf(payout_id: int, admin_name: str):
    import payment_service as payout_service
    import operations
    from invoice_pdf import render_paid_invoice
    detail = await payout_service.payout_detail(payout_id, include_sensitive=True)
    if not detail:
        return False, "Data invoice tidak ditemukan."
    if DEV_BYPASS:
        await payout_service.record_invoice_delivery(payout_id, message_id="dev")
        return True, None
    connection = await dashboard_db()
    try:
        row = await (await connection.execute("""SELECT ticket_channel_id FROM assignments
            WHERE staff_id=? AND ticket_channel_id IS NOT NULL ORDER BY id DESC LIMIT 1""",
            (detail["staff_id"],))).fetchone()
    finally:
        await connection.close()
    if not row:
        error = "Tiket privat staff tidak ditemukan."
        await payout_service.record_invoice_delivery(payout_id, error=error)
        return False, error
    profile = next((item for item in await staff_directory() if int(item["id"]) == int(detail["staff_id"])), None)
    try:
        pdf = render_paid_invoice(
            detail, staff_name=(profile or {}).get("username"), admin_name=admin_name
        )
        payload = {
            "content": f"<@{detail['staff_id']}>",
            "embeds": [{
                "title": "Invoice Gaji Lunas",
                "description": f"Pembayaran **Rp {detail['total_amount']:,.0f}** telah ditransfer.".replace(",", "."),
                "color": 5763719,
                "fields": [
                    {"name": "Invoice", "value": detail["invoice_number"], "inline": False},
                    {"name": "Periode", "value": detail["period"], "inline": True},
                    {"name": "Chapter", "value": str(detail["chapter_count"]), "inline": True},
                ],
            }],
            "attachments": [{"id": 0, "filename": f"{detail['invoice_number']}.pdf"}],
        }
        form = aiohttp.FormData()
        form.add_field("payload_json", json.dumps(payload))
        form.add_field(
            "files[0]", pdf, filename=f"{detail['invoice_number']}.pdf",
            content_type="application/pdf",
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://discord.com/api/v10/channels/{row['ticket_channel_id']}/messages",
                headers={"Authorization": f"Bot {TOKEN}"}, data=form,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                body = await response.json(content_type=None)
                if response.status >= 300:
                    raise RuntimeError(f"Discord HTTP {response.status}")
        await payout_service.record_invoice_delivery(payout_id, message_id=body.get("id"))
        return True, None
    except Exception as error:
        message = str(error)[:500]
        await payout_service.record_invoice_delivery(payout_id, error=message)
        await operations.record_event(
            "invoice", "error", "Dashboard gagal mengirim invoice PDF",
            {"payout_id": payout_id, "error": message},
        )
        return False, message
