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
        "NF", "FORNECEDOR", "NATUREZA", "DATA DE ENVIO", "DIAS DE ATRASO", "NOME DO ARQUIVO"
    ]
    assert selected.iloc[0]["DATA DE ENVIO"] == "09/10/2026 15:00"
    html = montar_email_html(selected, datetime(2026, 10, 14))
    assert "<table" in html and "</table>" in html
    assert "001234" in html and "NF_1234.pdf" in html
    assert "Metal &amp; Cia" in html and "Metal & Cia" not in html
    assert "DIAS DE ATRASO" in html
    assert "color:#ffffff" in html
    assert "sem confirmação de lançamento." in html
    assert "Controle de NFs Almoxarifado | SETTA" in html
    from nf_email_notifications import gerar_previa_visual_ficticia
    fake_preview = gerar_previa_visual_ficticia(datetime(2026,10,15,16,19))
    assert "EXEMPLO-001234" in fake_preview
    assert "EXEMPLO-005678" in fake_preview
    assert "HOMOLOGAÇÃO — DADOS FICTÍCIOS" in fake_preview
    assert "NÃO REALIZAR COBRANÇA" in fake_preview
    assert "color:#ffffff" in fake_preview
    assert "12/10/2026" in fake_preview
    assert "13/10/2026" in fake_preview
    assert "ALMOXARIFADO · CONTROLE DE NFs" in html
    assert "NOTAS FISCAIS EM ACOMPANHAMENTO" in html
    assert "max-width:920px" in html
    assert 'width="920"' in html
    assert "Referência: 14/10/2026" in html
    assert "009999" not in html and "007777" not in html
    assert "008888" not in html
    assert "marcos.rodrigues@" not in html
    assert "mailto:" not in html
    assert assunto_cobranca(datetime(2026, 10, 14)) == (
        "SETTA | Acompanhamento de lançamento de NFs vencidas — 14/10/2026"
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
    assert "BAIXAR PRÉVIA VISUAL DO E-MAIL · HTML (SEM ENVIO)" in app
    assert "PRODUÇÃO DEFINITIVA DESATIVADA" in app
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
    form_start = app.index('with st.form("nf_email_simulacao"')
    form_end = app.index('if _send_sim and not _confirm_sim:', form_start)
    simulation_form = app[form_start:form_end]
    assert "disabled=not _confirm_sim" not in simulation_form
    assert 'if _send_sim and not _confirm_sim:' in app
    assert 'elif _send_sim and not str(_pin_sim or "").strip():' in app
    assert 'elif _send_sim:' in app
    assert app.index('if _send_sim and not _confirm_sim:') < app.index('_result_sim = _sender(_pin_sim)')
    assert app.index('elif _send_sim and not str(_pin_sim or "").strip():') < app.index('_result_sim = _sender(_pin_sim)')
    assert '_sender(_pin_sim)' in app
    assert 'getattr(_email_module, _method, None)' in app
    assert '"enviar_previa_realista_contabilidade"' in app
    assert '"enviar_simulacao_contabilidade"' in app
    assert 'MODELO DO E-MAIL' in app
    assert 'ENVIAR PRÉVIA REALISTA PARA HOMOLOGAÇÃO' in app
    # O import do novo módulo deve ser tardio para não derrubar o aplicativo.
    import ast
    parsed = ast.parse(app)
    module_imports = [
        n for n in parsed.body
        if isinstance(n, ast.ImportFrom) and n.module == "nf_email_delivery"
    ]
    assert module_imports
    assert all(
        "enviar_simulacao_contabilidade" not in [a.name for a in n.names]
        for n in module_imports
    )
    assert app.index('st.form("nf_email_simulacao"') < app.index("if pendencias.empty:")
    from pathlib import Path
    edge = (Path(__file__).resolve().parents[1] /
        "supabase/functions/nf-email-api/index.ts").read_text("utf-8")
    sql = (Path(__file__).resolve().parents[1] /
        "supabase/migrations/20261014_nf_email_notifications_queue.sql").read_text("utf-8")
    assert 'nf_email_claim_simulation' in edge
    assert 'checkWorkflowUrl(Deno.env.get("NFS_EMAIL_WORKFLOW_URL") || "")' in edge
    assert '"WEBHOOK_SEGREDO_AUSENTE"' in app
    assert '"WEBHOOK_NAO_E_URL_HTTP_DO_GATILHO"' in app
    assert 'simulationRows()' in edge
    assert 'realisticSimulationRows()' in edge
    assert 'mode === "PREVIA_REALISTA"' in edge
    assert 'mode === "SIMULACAO" || mode === "PREVIA_REALISTA"' in edge
    assert 'data?.mode === "PILOTO" ? "PILOTO"' in edge
    assert '" [PILOTO — ACOMPANHAMENTO 48H]"' in edge
    assert 'mode !== "PRODUCAO" && mode !== "PILOTO"' in edge
    pilot_sql = (Path(__file__).resolve().parents[1] /
        "supabase/migrations/20261015_nf_email_piloto_48h.sql").read_text("utf-8")
    assert "interval '48 hours'" in pilot_sql
    assert "piloto_ativo boolean not null default false" in pilot_sql
    assert "v_limit := case when p_modo='TESTE' then 4 else 2 end" in pilot_sql
    assert "p.lancado_em is null" in pilot_sql
    assert "if not exists(" in pilot_sql
    assert "synced_at < v_controle.piloto_inicio" in pilot_sql
    assert "where modo='PILOTO' and source_version=v_sync.version_token" in pilot_sql
    assert "where modo='PILOTO' and data_local=v_hoje" in pilot_sql
    assert "now()>=v_controle.piloto_ate" in pilot_sql
    assert "AGUARDANDO_TOKEN_NO_VAULT" in pilot_sql
    pilot_empty = (Path(__file__).resolve().parents[1] /
        "supabase/migrations/20261016_nf_email_piloto_vazio_8h.sql").read_text("utf-8")
    assert "v_time < time '08:00'" in pilot_empty
    assert "v_hora < time '08:00'" in pilot_empty
    assert "v_count>=2" in pilot_empty
    assert "v_sync.synced_at <= v_last_sent" in pilot_empty
    assert "AGUARDANDO_STSUP01" in pilot_empty
    assert "SEM_PENDENCIAS" in pilot_empty
    assert "source_version=v_sync.version_token" in pilot_empty
    assert "nf_email_piloto_claim" in pilot_empty
    assert "nf_email_piloto_claim" in edge
    assert "pilotStatus:mode" in edge
    scheduled_guard = (Path(__file__).resolve().parents[1] /
        "supabase/migrations/20261016_nf_email_piloto_inicio_programado.sql").read_text("utf-8")
    assert "now() < v_controle.piloto_inicio" in scheduled_guard
    assert "now()>=v_controle.piloto_ate" in scheduled_guard
    assert "piloto_ativo=false" in scheduled_guard
    assert "body => '{\"mode\":\"PILOTO\"}'::jsonb" in pilot_sql
    assert 'renderSettaEmail(rows,' in edge
    assert 'normalSubject + " [HOMOLOGAÇÃO — DADOS FICTÍCIOS]"' in edge
    assert '[SIMULAÇÃO / NÃO COBRAR]' in edge
    template = (Path(__file__).resolve().parents[1] /
        "supabase/functions/nf-email-api/email_layout.ts").read_text("utf-8")
    assert 'Number(r.dias_atraso)' in template
    assert 'Controle de NFs Almoxarifado | SETTA' in template
    assert 'color:#ffffff' in template
    assert 'Acompanhamento de lançamento de NFs' in template
    assert 'HOMOLOGAÇÃO — DADOS FICTÍCIOS' in template
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
    from nf_email_delivery import enviar_previa_realista_contabilidade
    with patch("nf_email_delivery.db._secret", side_effect=lambda x: {
        "NFS_EMAIL_API_TOKEN": "a" * 40,
        "NFS_EMAIL_OPERATOR_PIN": "autorizacao-somente-teste",
    }.get(x, "")), patch("nf_email_delivery.db.supabase_url",
    return_value="https://example.supabase.co"), patch(
        "nf_email_delivery.requests.post",
        return_value=Mock(ok=True, json=lambda: {
            "ok": True, "data": {"status": "ACEITO", "mode": "PREVIA_REALISTA"}
        }),
    ) as preview_post:
        assert enviar_previa_realista_contabilidade("autorizacao-somente-teste")["mode"] == "PREVIA_REALISTA"
        assert preview_post.call_args.kwargs["json"] == {"mode": "PREVIA_REALISTA"}
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
    assert "Limite de homologação atingido: até 4 testes por dia" in app
    assert "Nenhum e-mail foi enviado nesta " in app
    assert '"configurados no Power Automate."' in app
    assert "apenas para Júnior e Washington." not in app
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
