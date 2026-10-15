"""Cliente privado de homologação de e-mails no Streamlit SETTA.

Chaves nunca são fornecidas por widgets nem exibidas no navegador. A função
Supabase verifica novamente sua própria cópia do segredo. Não permite
selecionar destinatários a partir do cliente.
"""
from __future__ import annotations

import hmac

import requests

import db


def acesso_teste_configurado() -> bool:
    token = db._secret("NFS_EMAIL_API_TOKEN")
    senha = db._secret("NFS_EMAIL_OPERATOR_PIN")
    return len(token) >= 32 and len(senha) >= 10


def verificar_pin_operador(pin_informado: str) -> bool:
    senha = db._secret("NFS_EMAIL_OPERATOR_PIN")
    if not acesso_teste_configurado() or len(pin_informado or "") > 256:
        return False
    return hmac.compare_digest(pin_informado, senha)


def _enviar_homologacao(pin: str, mode: str) -> dict:
    if mode not in ("TESTE", "SIMULACAO"):
        raise ValueError("Modo de homologação inválido.")
    if not verificar_pin_operador(pin):
        raise PermissionError("PIN de autorização inválido ou acesso não configurado.")
    token = db._secret("NFS_EMAIL_API_TOKEN")
    url = db.supabase_url().rstrip("/") + "/functions/v1/nf-email-api"
    response = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "x-nfs-notification-token": token,
        },
        json={"mode": mode},
        timeout=(8, 35),
    )
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError("API de notificação retornou uma resposta inválida.") from exc
    # Nunca exibir corpo livre do provedor, pois poderia conter segredos.
    if not response.ok or not result.get("ok"):
        raise RuntimeError(
            str(result.get("error") or "FALHA_DE_ENVIO")[:150]
        )
    return result.get("data") or {}


def enviar_teste_contabilidade(pin: str) -> dict:
    """Teste com NFs reais elegíveis, sem acionamento da produção."""
    return _enviar_homologacao(pin, "TESTE")


def enviar_simulacao_contabilidade(pin: str) -> dict:
    """Um e-mail fictício com PIN; não altera dados fiscais."""
    return _enviar_homologacao(pin, "SIMULACAO")
