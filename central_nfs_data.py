from __future__ import annotations

import base64
import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

DEFAULT_SUPABASE_URL = "https://cuixazpxkvniqldmmnth.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN1aXhhenB4a3ZuaXFsZG1tbnRoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1MTYwNTMsImV4cCI6MjEwMzA5MjA1M30.jNFaIG1FcDYnMAoVaI23UYMuRL1BpZmuqu_LPEYb88E"
CONSUMER_KEY = "controle_nfs"
TZ = ZoneInfo("America/Sao_Paulo")

SESSION = requests.Session()
SESSION.headers.update({"Connection": "keep-alive"})


def supabase_url() -> str:
    return (os.getenv("SUPABASE_URL") or DEFAULT_SUPABASE_URL).strip().rstrip("/")


def supabase_key() -> str:
    return (
        os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_KEY")
        or DEFAULT_SUPABASE_ANON_KEY
    ).strip()


def _headers() -> dict[str, str]:
    key = supabase_key()
    return {
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": "application/json",
    }


def api_call(action: str, payload: dict | None = None, timeout: int = 45) -> dict:
    response = SESSION.post(
        f"{supabase_url()}/functions/v1/setta-data-api",
        headers=_headers(),
        json={"action": action, "payload": payload or {}},
        timeout=timeout,
    )
    try:
        data = response.json()
    except Exception:
        data = {"ok": False, "error": response.text or f"HTTP {response.status_code}"}
    if not response.ok or not data.get("ok"):
        raise RuntimeError(data.get("error") or f"HTTP {response.status_code}")
    return data


def load_bundle_state() -> dict:
    payload = api_call(
        "bundle_state",
        {
            "source_keys": ["mes_pre_notas", "nf"],
            "derived_keys": [],
        },
        timeout=30,
    ).get("data") or {}
    rows = payload.get("sources") or []
    return {
        str(row.get("source_key")): row
        for row in rows
        if isinstance(row, dict)
    }


def source_token(meta: dict) -> str:
    return f"v{int(meta.get('version') or 0)}|{meta.get('last_update_at') or ''}"


def download_source_bytes(source_key: str) -> tuple[bytes, dict]:
    meta = api_call(
        "source_download",
        {"source_key": source_key},
        timeout=30,
    ).get("data") or {}
    signed_url = str(meta.get("signed_url") or "")
    if not signed_url:
        raise RuntimeError(f"Fonte {source_key} sem URL de leitura.")
    response = SESSION.get(signed_url, timeout=120)
    response.raise_for_status()
    return response.content, meta


def load_visual_config() -> dict:
    row = api_call(
        "visual_get",
        {"app_key": "setta_global"},
        timeout=30,
    ).get("data") or {}
    return {
        "logo_data": row.get("logo_data") or "",
        "logo_mime": row.get("logo_mime") or "image/png",
        "favicon_data": row.get("favicon_data") or "",
        "favicon_mime": row.get("favicon_mime") or "image/png",
    }


def favicon_bytes(config: dict | None = None) -> bytes:
    cfg = config or load_visual_config()
    data = str(cfg.get("favicon_data") or "").strip()
    if not data:
        return b""
    try:
        return base64.b64decode(data, validate=True)
    except Exception:
        return b""


def sync_state() -> dict[str, dict]:
    rows = api_call(
        "consumer_sync_status",
        {"consumer_key": CONSUMER_KEY},
        timeout=30,
    ).get("data") or []
    return {
        str(row.get("source_key")): row
        for row in rows
        if isinstance(row, dict)
    }


def commit_sync(
    source_key: str,
    version_token: str,
    source_updated_at: Any,
    rows_count: int,
    *,
    status: str = "ATUALIZADO",
    error_message: str | None = None,
) -> dict:
    return api_call(
        "consumer_sync_commit",
        {
            "consumer_key": CONSUMER_KEY,
            "source_key": source_key,
            "version_token": version_token,
            "source_updated_at": source_updated_at,
            "rows_count": int(rows_count or 0),
            "status": status,
            "error_message": error_message,
        },
        timeout=30,
    ).get("data") or {}


def format_dt(value: Any) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value)
