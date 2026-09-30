from __future__ import annotations

import os
from datetime import date, datetime
from typing import Iterable

import requests
import streamlit as st

DEFAULT_SUPABASE_URL = "https://cuixazpxkvniqldmmnth.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN1aXhhenB4a3ZuaXFsZG1tbnRoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc1MTYwNTMsImV4cCI6MjEwMzA5MjA1M30.jNFaIG1FcDYnMAoVaI23UYMuRL1BpZmuqu_LPEYb88E"


def _secret(*names: str) -> str:
    for name in names:
        try:
            value = st.secrets.get(name)
            if value:
                return str(value).strip()
        except Exception:
            pass
        value = os.getenv(name)
        if value:
            return str(value).strip()
    try:
        supa = st.secrets.get("supabase", {})
        for name in names:
            for key in (name, name.lower(), name.replace("SUPABASE_", "").lower()):
                value = supa.get(key)
                if value:
                    return str(value).strip()
    except Exception:
        pass
    return ""


def supabase_url() -> str:
    return _secret("SUPABASE_URL") or DEFAULT_SUPABASE_URL


def supabase_key() -> str:
    return _secret("SUPABASE_ANON_KEY", "SUPABASE_KEY", "SUPABASE_PUBLISHABLE_KEY") or DEFAULT_SUPABASE_ANON_KEY


def configured() -> bool:
    return bool(supabase_url() and supabase_key())


def _headers(prefer: str | None = None) -> dict[str, str]:
    key = supabase_key()
    if not key:
        raise RuntimeError("SUPABASE_ANON_KEY não configurada nos Secrets do Streamlit.")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _raise(response: requests.Response) -> None:
    if response.ok:
        return
    try:
        payload = response.json()
        message = payload.get("message") or payload.get("error") or payload.get("hint") or str(payload)
    except Exception:
        message = response.text
    raise RuntimeError(f"Supabase HTTP {response.status_code}: {message}")


def _json_safe(value):
    """Converte datas e escalares para tipos aceitos pelo JSON do requests."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]

    # Compatibilidade com escalares NumPy/Pandas sem importar essas bibliotecas.
    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return _json_safe(item_method())
        except Exception:
            pass

    iso_method = getattr(value, "isoformat", None)
    if callable(iso_method):
        try:
            return iso_method()
        except Exception:
            pass

    return str(value)


def rpc(name: str, payload: dict | None = None, timeout: int = 60):
    response = requests.post(
        f"{supabase_url()}/rest/v1/rpc/{name}",
        headers=_headers(),
        json=_json_safe(payload or {}),
        timeout=timeout,
    )
    _raise(response)
    if not response.text.strip():
        return None
    return response.json()


def _select_all(table: str, select: str = "*", order: str | None = None, filters: dict | None = None, page_size: int = 1000, max_rows: int = 20000):
    rows: list[dict] = []
    start = 0
    params = {"select": select}
    if order:
        params["order"] = order
    for key, value in (filters or {}).items():
        params[key] = value
    while start < max_rows:
        end = min(start + page_size - 1, max_rows - 1)
        headers = _headers()
        headers["Range"] = f"{start}-{end}"
        response = requests.get(
            f"{supabase_url()}/rest/v1/{table}",
            headers=headers,
            params=params,
            timeout=45,
        )
        _raise(response)
        batch = response.json() or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return rows


def load_config() -> dict:
    if not configured():
        return {}
    rows = _select_all("nf_configuracoes", filters={"chave": "eq.app"}, max_rows=2)
    if not rows:
        return {}
    value = rows[0].get("valor") or {}
    return value if isinstance(value, dict) else {}


def save_config(config: dict) -> None:
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    rpc("nf_salvar_configuracao", {"p_chave": "app", "p_valor": config}, timeout=45)


def load_suppliers() -> list[dict]:
    if not configured():
        return []
    data = rpc("nf_fornecedores_snapshot", {}, timeout=60)
    return data if isinstance(data, list) else []


def replace_suppliers(rows: Iterable[dict], file_name: str, stats: dict) -> dict:
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    result = rpc(
        "nf_substituir_fornecedores",
        {
            "p_rows": list(rows),
            "p_arquivo_nome": file_name,
            "p_total_linhas": int(stats.get("total", 0)),
            "p_validos": int(stats.get("validos", 0)),
            "p_invalidos": int(stats.get("invalidos", 0)),
            "p_duplicados": int(stats.get("duplicados", 0)),
        },
        timeout=120,
    )
    return result or {}


def list_supplier_imports(limit: int = 20) -> list[dict]:
    if not configured():
        return []
    return _select_all(
        "nf_fornecedor_importacoes",
        order="importado_em.desc",
        max_rows=limit,
    )[:limit]


def save_process_records(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    if not rows:
        return {"inseridos": 0}
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    return rpc("nf_registrar_processamentos", {"p_rows": rows}, timeout=90) or {}


def list_process_records(limit: int = 10000) -> list[dict]:
    if not configured():
        return []
    return _select_all(
        "nf_processamentos",
        order="processado_em.desc",
        page_size=1000,
        max_rows=limit,
    )[:limit]


def save_mrp_load(
    detail: Iterable[dict],
    summary: Iterable[dict],
    files: Iterable[str],
    stats: dict | None = None,
) -> dict:
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    return rpc(
        "nf_salvar_mrp_carga",
        {
            "p_detalhe": list(detail),
            "p_resumo": list(summary),
            "p_arquivos": list(files),
            "p_stats": stats or {},
        },
        timeout=120,
    ) or {}


def load_mrp_load() -> dict:
    if not configured():
        return {}
    rows = _select_all(
        "nf_mrp_carga_atual",
        order="atualizado_em.desc",
        max_rows=1,
    )
    return rows[0] if rows else {}


def load_materials_api_status() -> dict:
    if not configured():
        return {}
    return rpc(
        "nf_materiais_api_status",
        {},
        timeout=45,
    ) or {}


def load_materials_api_current() -> dict:
    if not configured():
        return {}
    return rpc(
        "nf_materiais_api_atual",
        {},
        timeout=60,
    ) or {}


def force_materials_api_sync() -> dict:
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    response = requests.post(
        f"{supabase_url()}/functions/v1/nf-materiais-api/sync",
        headers=_headers(),
        json={},
        timeout=60,
    )
    _raise(response)
    if not response.text.strip():
        return {}
    return response.json() or {}


def list_mrp_imports(limit: int = 100) -> list[dict]:
    if not configured():
        return []
    return _select_all(
        "nf_mrp_importacoes",
        order="importado_em.desc",
        max_rows=limit,
    )[:limit]


def mark_sent(ids: Iterable[str], operator: str = "") -> dict:
    ids = [str(x) for x in ids if str(x).strip()]
    if not ids:
        return {"atualizados": 0}
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    return rpc("nf_marcar_enviados", {"p_ids": ids, "p_operador": operator or None}, timeout=45) or {}


def reconcile_launches(
    launched_ids: Iterable[str],
    checked_ids: Iterable[str],
) -> dict:
    launched_ids = [str(x) for x in launched_ids if str(x).strip()]
    checked_ids = [str(x) for x in checked_ids if str(x).strip()]
    if not checked_ids and not launched_ids:
        return {"lancados": 0, "verificados": 0}
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    return rpc(
        "nf_conciliar_lancamentos",
        {
            "p_lancados": launched_ids,
            "p_verificados": checked_ids,
        },
        timeout=60,
    ) or {}


def delete_process_records(ids: Iterable[str]) -> dict:
    ids = [str(x) for x in ids if str(x).strip()]
    if not ids:
        return {"excluidos": 0}
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    return rpc(
        "nf_excluir_processamentos",
        {"p_ids": ids},
        timeout=60,
    ) or {}


def list_excluded_documents() -> list[dict]:
    if not configured():
        return []
    data = rpc("nf_listar_desconsiderados", {}, timeout=45)
    return data if isinstance(data, list) else []


def mark_documents_excluded(
    numbers: Iterable[str],
    reason: str = "",
    source: str = "",
    operator: str = "",
) -> dict:
    values = [str(x) for x in numbers if str(x).strip()]
    if not values:
        return {"marcados": 0}
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    return rpc(
        "nf_desconsiderar_documentos",
        {
            "p_numeros": values,
            "p_motivo": str(reason or "").strip() or None,
            "p_origem": str(source or "").strip() or None,
            "p_operador": str(operator or "").strip() or None,
        },
        timeout=45,
    ) or {}


def restore_excluded_documents(numbers: Iterable[str]) -> dict:
    values = [str(x) for x in numbers if str(x).strip()]
    if not values:
        return {"restaurados": 0}
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    return rpc(
        "nf_restaurar_documentos",
        {"p_numeros": values},
        timeout=45,
    ) or {}


def restart_pending_process_records(ids: Iterable[str]) -> dict:
    ids = [str(x) for x in ids if str(x).strip()]
    if not ids:
        return {"reiniciados": 0}
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    return rpc(
        "nf_reiniciar_processamentos",
        {"p_ids": ids},
        timeout=60,
    ) or {}


def update_receipt_dates(updates: Iterable[dict]) -> dict:
    updates = [
        dict(item)
        for item in updates
        if str(item.get("id") or "").strip()
        and str(item.get("data_recebimento") or "").strip()
    ]
    if not updates:
        return {"atualizados": 0}
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    return rpc(
        "nf_atualizar_datas_recebimento",
        {"p_updates": updates},
        timeout=60,
    ) or {}


def replace_pre_notes(rows: Iterable[dict], file_name: str) -> dict:
    rows = list(rows)
    if not configured():
        raise RuntimeError("Supabase não configurado.")
    return rpc(
        "nf_substituir_pre_notas",
        {"p_rows": rows, "p_arquivo_nome": file_name, "p_total_linhas": len(rows)},
        timeout=90,
    ) or {}


def load_pre_notes() -> list[dict]:
    if not configured():
        return []
    return _select_all(
        "nf_pre_notas_atual",
        order="data_pre_nota.desc.nullslast",
        page_size=1000,
        max_rows=30000,
    )


def list_pre_note_imports(limit: int = 20) -> list[dict]:
    if not configured():
        return []
    return _select_all(
        "nf_pre_nota_importacoes",
        order="importado_em.desc",
        max_rows=limit,
    )[:limit]


def list_users(active_only: bool = False) -> list[dict]:
    if not configured():
        return []
    filters = {"ativo": "eq.true"} if active_only else None
    return _select_all(
        "nf_usuarios",
        select="id,nome,email,ativo,criado_em,atualizado_em",
        order="nome.asc",
        filters=filters,
        max_rows=1000,
    )


def create_user(name: str, email: str = "") -> dict:
    return rpc(
        "nf_criar_usuario",
        {"p_nome": str(name or "").strip(), "p_email": str(email or "").strip() or None},
        timeout=45,
    ) or {}


def update_user(user_id: str, name: str, email: str, active: bool) -> dict:
    return rpc(
        "nf_atualizar_usuario",
        {
            "p_id": str(user_id),
            "p_nome": str(name or "").strip(),
            "p_email": str(email or "").strip() or None,
            "p_ativo": bool(active),
        },
        timeout=45,
    ) or {}


def delete_user(user_id: str) -> dict:
    return rpc("nf_excluir_usuario", {"p_id": str(user_id)}, timeout=45) or {}

def db_status() -> dict:
    return {
        "configured": configured(),
        "url": supabase_url(),
        "key_present": bool(supabase_key()),
    }
