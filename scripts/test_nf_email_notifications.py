"""Teste do modelo de e-mail contábil em homologação (nenhum envio real)."""
from datetime import datetime

import pandas as pd

from nf_email_notifications import (
    LIMITE_DIARIO_PREVISTO,
    STATUS_COBRANCA,
    assunto_cobranca,
    montar_email_html,
    preparar_cobrancas,
)


def run() -> None:
    assert LIMITE_DIARIO_PREVISTO == 2
    source = pd.DataFrame([
        {
            "numero_nf": "001234", "fornecedor_padrao": "Metal & Cia",
            "natureza": "COMPRA DE MATERIA PRIMA",
            "enviado_em_local": "2026-10-09 15:00:00",
            "arquivo_final": "NF_1234.pdf",
            "prazo_lancamento": "2026-10-12 15:00:00",
            "situacao_lancamento": STATUS_COBRANCA,
            "lancado_em_local": None,
        },
        {
            "numero_nf": "009999", "fornecedor_padrao": "Já lançado",
            "natureza": "COMPRA DE MATERIA PRIMA",
            "enviado_em_local": "2026-10-09 15:00:00",
            "arquivo_final": "NF_9999.pdf",
            "prazo_lancamento": "2026-10-12 15:00:00",
            "situacao_lancamento": "LANÇAMENTO CONFIRMADO",
            "lancado_em_local": "2026-10-13 12:00:00",
        },
        {
            "numero_nf": "007777", "fornecedor_padrao": "Sem relatório atualizado",
            "natureza": "COMPRA DE MATERIA PRIMA",
            "enviado_em_local": "2026-10-09 15:00:00",
            "arquivo_final": "NF_7777.pdf",
            "prazo_lancamento": "2026-10-12 15:00:00",
            "situacao_lancamento": "AGUARDANDO NOVO RELATÓRIO",
            "lancado_em_local": None,
        },
        {
            "numero_nf": "008888", "fornecedor_padrao": "Inconsistência",
            "natureza": "COMPRA DE MATERIA PRIMA",
            "enviado_em_local": "2026-10-09 15:00:00",
            "arquivo_final": "NF_8888.pdf",
            "prazo_lancamento": "2026-10-12 15:00:00",
            "situacao_lancamento": STATUS_COBRANCA,
            "lancado_em_local": "2026-10-12 14:00:00",
        },
    ])
    selected = preparar_cobrancas(source)
    assert selected["NF"].tolist() == ["001234"]
    assert list(selected.columns) == [
        "NF", "FORNECEDOR", "NATUREZA", "DATA DE ENVIO", "NOME DO ARQUIVO"
    ]
    assert selected.iloc[0]["DATA DE ENVIO"] == "09/10/2026 15:00"
    html = montar_email_html(selected, datetime(2026, 10, 14))
    assert "<table" in html and "</table>" in html
    assert "001234" in html and "NF_1234.pdf" in html
    assert "Metal &amp; Cia" in html and "Metal & Cia" not in html
    assert "009999" not in html and "007777" not in html
    assert "008888" not in html
    assert "marcos.rodrigues@" not in html
    assert "mailto:" not in html
    assert assunto_cobranca(datetime(2026, 10, 14)) == (
        "SETTA | Cobrança de lançamento de NFs vencidas — 14/10/2026"
    )
    assert preparar_cobrancas(pd.DataFrame()).empty
    try:
        montar_email_html(pd.DataFrame(), datetime(2026, 10, 14))
    except ValueError:
        pass
    else:
        raise AssertionError("Uma prévia vazia não pode ser enviada.")
    # A tela deve deixar explícito que não realiza nenhum disparo.
    from pathlib import Path
    app = (Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text("utf-8")
    assert "render_accounting_email_preview()" in app
    assert "BAIXAR PRÉVIA DO E-MAIL · HTML" in app
    assert "ENVIO AUTOMÁTICO DESATIVADO EM HOMOLOGAÇÃO" in app
    from nf_email_delivery import acesso_teste_configurado, verificar_pin_operador
    from unittest.mock import patch
    with patch("nf_email_delivery.db._secret", side_effect=lambda x: {
        "NFS_EMAIL_API_TOKEN": "a" * 40,
        "NFS_EMAIL_OPERATOR_PIN": "autorizacao-somente-teste",
    }.get(x, "")):
        assert acesso_teste_configurado()
        assert verificar_pin_operador("autorizacao-somente-teste")
        assert not verificar_pin_operador("senha-errada")
    with patch("nf_email_delivery.db._secret", return_value=""):
        assert not acesso_teste_configurado()
        assert not verificar_pin_operador("qualquer-coisa")
    assert "ENVIAR E-MAIL DE TESTE" in app
    assert 'render_accounting_email_preview()' in app
    assert "NFS_EMAIL_OPERATOR_PIN" in app
    assert "ENVIAR SIMULAÇÃO PARA HOMOLOGAÇÃO" in app
    assert "enviar_simulacao_contabilidade(_pin_sim)" in app
    assert app.index('st.form("nf_email_simulacao"') < app.index("if pendencias.empty:")
    from pathlib import Path
    edge = (Path(__file__).resolve().parents[1] /
        "supabase/functions/nf-email-api/index.ts").read_text("utf-8")
    sql = (Path(__file__).resolve().parents[1] /
        "supabase/migrations/20261014_nf_email_notifications_queue.sql").read_text("utf-8")
    assert 'nf_email_claim_simulation' in edge
    assert 'simulationRows()' in edge
    assert '[SIMULAÇÃO / NÃO COBRAR]' in edge
    from nf_email_delivery import enviar_simulacao_contabilidade
    from unittest.mock import Mock
    with patch("nf_email_delivery.db._secret", side_effect=lambda x: {
        "NFS_EMAIL_API_TOKEN": "a" * 40,
        "NFS_EMAIL_OPERATOR_PIN": "autorizacao-somente-teste",
    }.get(x, "")), patch("nf_email_delivery.db.supabase_url",
    return_value="https://example.supabase.co"), patch(
        "nf_email_delivery.requests.post",
        return_value=Mock(ok=True, json=lambda: {
            "ok": True, "data": {"status": "ACEITO", "mode": "SIMULACAO"}
        }),
    ) as mock_post:
        assert enviar_simulacao_contabilidade("autorizacao-somente-teste")["status"] == "ACEITO"
        assert mock_post.call_args.kwargs["json"] == {"mode": "SIMULACAO"}
    with patch("nf_email_delivery.db._secret", return_value=""):
        try:
            enviar_simulacao_contabilidade("PIN_INCORRETO")
        except PermissionError:
            pass
        else:
            raise AssertionError("Simulação sem autorização não pode ser enviada.")
    simulation_sql = (Path(__file__).resolve().parents[1] /
        "supabase/migrations/20261015_nf_email_simulation.sql").read_text("utf-8")
    assert "producao_ativa" in simulation_sql
    assert "where modo='TESTE'" in simulation_sql
    assert "nf_email_claim_simulation" in simulation_sql
    assert "source_version" in simulation_sql
    assert "revoke all on function" in simulation_sql

    assert '"x-nfs-notification-token"' in edge
    assert 'NFS_EMAIL_PRODUCTION_ENABLED' in edge
    assert 'mode !== "PRODUCAO" ? testAddress : productionTo' in edge
    assert 'normalizeTestRecipients(testConfig?.data?.destinatario_teste)' in edge
    assert 'import { normalizeTestRecipients } from "./recipients.ts";' in edge
    assert "os dois destinatários de TESTE" in app
    assert '.from("nf_email_controle").select("destinatario_teste")' in edge
    assert "NFS_EMAIL_TEST_RECIPIENT" not in edge
    recipient_migration = (Path(__file__).resolve().parents[1] /
        "supabase/migrations/20261014_nf_email_test_recipient.sql").read_text("utf-8")
    assert "destinatario_teste" in recipient_migration
    assert 'mode !== "PRODUCAO" ? "" : productionCc' in edge
    assert 'NFS_EMAIL_WORKFLOW_URL' in edge
    assert 'secureMatch(shared,supplied)' in edge
    assert 'html:body' in edge
    assert 'nf_email_claim' in edge and 'nf_email_finish' in edge
    assert "version_token = v_config.versao_baseline" in sql
    assert "source_key='nf'" in sql
    assert "producao_ativa boolean not null default false" in sql
    assert "v_limit := case when p_modo='TESTE' then 4 else 2 end" in sql
    assert "lancamento_verificado_em > public.nf_prazo_vencimento_24h" in sql
    assert "lancado_em is null" in sql
    assert "where modo='PRODUCAO' and source_version=v_sync.version_token" in sql

    print("NF_ACCOUNTING_EMAIL_PREVIEW_OK")


if __name__ == "__main__":
    run()
