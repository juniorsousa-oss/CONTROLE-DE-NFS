"""Regressão do disparo automático de produção das cobranças SETTA.

Não consulta credenciais, não dispara webhooks e não modifica NFs reais.
"""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
migration = (root / "supabase/migrations/20261022_nf_email_production_activation.sql").read_text("utf-8")
edge = (root / "supabase/functions/nf-email-api/index.ts").read_text("utf-8")
app = (root / "streamlit_app.py").read_text("utf-8")

# Produção permanece desligada durante a migração. É ativada posteriormente
# somente por operação administrativa explícita e baseline da carga corrente.
assert "add column if not exists producao_inicio timestamptz" in migration
assert "add column if not exists producao_destinatarios text" in migration
assert "add column if not exists producao_cc text" in migration
assert "producao_ativa=true" in migration
assert "or v_sync.synced_at <= v_cfg.producao_inicio" in migration
assert "or v_sync.synced_at <= v_config.producao_inicio" in migration
assert "or now() - v_sync.synced_at > interval '24 hours'" in migration
assert "or now()-v_sync.synced_at > interval '24 hours'" in migration
assert "v_sync.version_token=v_cfg.versao_baseline" in migration
assert "v_sync.version_token = v_config.versao_baseline" in migration
assert "where modo='PRODUCAO' and source_version=v_sync.version_token" in migration
assert "where modo='PRODUCAO'" in migration
assert ">= 2" in migration
assert "lancamento_verificado_em is not null" in migration
assert "lancamento_conferencia_pendente" in migration
assert "p.lancado_em is null" in migration
assert "if not exists(" in migration
assert "v_token is null or length(v_token)<32" in migration
assert "select cron.schedule(" in migration
assert "'setta-nfs-producao-hourly'" in migration
assert "'0 10-21 * * 1-5'" in migration
assert "if extract(isodow from v_local)>5" in migration

# Sem destinos fornecidos pelo cliente ou por acessos não autenticados.
assert '.select("producao_ativa,producao_destinatarios,producao_cc")' in edge
assert '!productionConfig?.data?.producao_ativa' in edge
assert 'NFS_EMAIL_PRODUCTION_ENABLED' not in edge
assert 'const productionTo = String(productionConfig?.data?.producao_destinatarios || "").trim()' in edge
assert 'const productionCc = String(productionConfig?.data?.producao_cc || "").trim()' in edge
assert 'data?.mode === "PRODUCAO" ? "PRODUCAO"' in edge
assert '"x-nfs-notification-token"' in edge
assert "nf_email_claim" in edge and "nf_email_finish" in edge
assert '"INCERTO"' in edge
assert "PRODUÇÃO CONTROLADA PELO AGENDADOR DO SUPABASE" in app
assert "dias úteis, entre 07h e 18h" in app
assert "PRODUÇÃO DEFINITIVA DESATIVADA" not in app

print("NFS_EMAIL_PRODUCTION_ACTIVATION_OK")
