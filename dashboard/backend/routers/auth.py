"""Auth router — Discord OAuth2 login/callback/logout."""

import secrets
from urllib.parse import urlencode

import aiohttp
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from config import GUILD_ID, ROLE_ADMIN_ID, ROLE_STAFF_ID
from deps import (
    DASHBOARD_ORIGIN, DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET,
    SESSION_SECRET, role_from_member,
)

router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()
oauth.register(
    name="discord",
    client_id=DISCORD_CLIENT_ID,
    client_secret=DISCORD_CLIENT_SECRET,
    access_token_url="https://discord.com/api/oauth2/token",
    authorize_url="https://discord.com/api/oauth2/authorize",
    api_base_url="https://discord.com/api/",
    client_kwargs={"scope": "identify guilds"},
)


@router.get("/login")
async def login(request: Request):
    if not DISCORD_CLIENT_ID:
        raise HTTPException(status_code=500, detail="OAuth tidak dikonfigurasi.")
    redirect_uri = f"{DASHBOARD_ORIGIN}/auth/callback"
    return await oauth.discord.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request):
    token = await oauth.discord.authorize_access_token(request)
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://discord.com/api/users/@me",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        ) as resp:
            if resp.status != 200:
                raise HTTPException(status_code=401, detail="Gagal mengambil data Discord.")
            profile = await resp.json()
        async with session.get(
            f"https://discord.com/api/users/@me/guilds/{GUILD_ID}/member",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        ) as resp:
            member = await resp.json() if resp.status == 200 else {}
    role = role_from_member(member)
    if not role:
        raise HTTPException(status_code=403, detail="Kamu bukan staff Ryukomik.")
    request.session["user"] = {
        "id": profile["id"],
        "username": profile.get("username", ""),
        "avatar": profile.get("avatar"),
        "role": role,
    }
    return RedirectResponse(url="/")


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}
