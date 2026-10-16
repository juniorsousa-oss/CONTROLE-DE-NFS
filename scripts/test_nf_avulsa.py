"""Testes de regressão da impressão avulsa: somente dados fictícios."""
import io
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nf_avulsa as av

assert av.normalized_number("000123") == "123"
for value in ("", "123A", "1234567890"):
    try:
        av.normalized_number(value)
    except ValueError:
        pass
    else:
        raise AssertionError("Número fiscal inválido foi aceito.")
assert av.parse_br_date("10/10/2026") == date(2026, 10, 10)
assert av.parse_br_date("31/02/2026") is None

nfkey="31261012345678000190550010000001231000000000"
ctekey="31261099887766000190570010000000011000000000"
nf=SimpleNamespace(chave=nfkey, numero_nf="123", serie="1", cnpj_emitente="12345678000190", emitente="EMITENTE", status_codigo="100")
cte=SimpleNamespace(chave=ctekey, numero="1", refs_nfe=[nfkey], emitente="TRANSPORTADORA", cnpj_emitente="99887766000190", tomador_nome="SETTA", cnpj_tomador="12345678000190", status_codigo="100")
record={"chave":nfkey,"numero":"123","cnpj_emitente":"12345678000190"}
cterecord={"chave":ctekey,"numero":"1"}
with patch.object(av,"extract_danfe_metadata",return_value=nf), patch.object(av,"extract_nfe_processing_data",return_value={}):
    assert av.safe_nfe_record(record,b"xml")[0] is nf
    try:
        av.safe_nfe_record({**record,"cnpj_emitente":"0"},b"xml")
    except ValueError:
        pass
    else:
        raise AssertionError("CNPJ divergente não bloqueado.")
with patch.object(av,"extract_cte_metadata",return_value=cte):
    assert av.safe_cte_record(cterecord,b"xml",{nfkey},lambda *a,**kw:True,[]) is cte
    try:
        av.safe_cte_record(cterecord,b"xml",{nfkey},lambda *a,**kw:False,[])
    except ValueError:
        pass
    else:
        raise AssertionError("Tomador externo não bloqueado.")

docs=[{"record":record,"raw":b"xml","meta":nf,"info":{}}]
ctes=[{"record":cterecord,"raw":b"xml","meta":cte}]
stamp={"data_chegada":date(2026,10,9),"cr":"10","desc_cr":"TESTE","natureza":"TESTE","recebido_por":"OP"}
with patch.object(av,"generate_danfe_pdf",return_value=b"DANFE"),patch.object(av,"generate_dacte_pdf",return_value=b"DACTE"),patch.object(av,"apply_operational_stamp",side_effect=lambda raw,**kw:raw+b"-CARIMBO"):
    dates={nfkey:date(2026,10,21)}
    raw=av.make_documents(docs,ctes,dates,None,lambda _: "FORNECEDOR")
    assert len(raw)==2 and b"DANFE" in raw.values() and b"DACTE" in raw.values()
    stamped=av.make_documents(docs,ctes,dates,{nfkey:stamp},lambda _: "FORNECEDOR")
    assert b"DANFE-CARIMBO" in stamped.values() and b"DACTE" in stamped.values()
    try:
        av.make_documents(docs,[],{},None,lambda _: "FORNECEDOR")
    except ValueError:
        pass
    else:
        raise AssertionError("Vencimento ausente não bloqueado.")

with zipfile.ZipFile(io.BytesIO(av._zip_outputs(stamped))) as z:
    assert set(z.namelist())==set(stamped)

app=Path("streamlit_app.py").read_text()
edge=Path("supabase/functions/nf-xml-library-api/index.ts").read_text()
assert 'nf_avulsa.render_page(' in app
assert 'if(action==="buscar_avulso")' in edge
assert 'if(action==="cte_avulso")' in edge
# refs_nfe é JSONB. O operador 'cs' precisa receber array JSON, não
# sintaxe de array SQL (cs.{chave}), que retorna HTTP 400 no PostgREST.
assert '.filter("refs_nfe","cs",JSON.stringify([k]))' in edge
assert '.contains("refs_nfe",[k])' not in edge

# O botão original continua atendendo os lotes, com o rótulo configurável.
assert '_NF_NAV_PAGES.append("Pendências")' in app
assert 'if _page == "Pendências"' in app
assert '_control_docs_label.upper()' in app
assert '_NF_NAV_PAGES.append("Impressão Avulsa")' in app
assert '_NF_NAV_PAGES.append("Geração de Arquivos")' not in app

# A navegação antiga é migrada para o novo título, sem jogar o operador no dashboard.
assert 'if value == "Geração de Arquivos":' in app
assert 'value = "Impressão Avulsa"' in app

# Impressão avulsa não possui mais aba duplicada nem retorno à geração convencional.
start = app.index('elif page == "Impressão Avulsa":')
end = app.index('elif page == "Biblioteca XML":', start)
avulsa_page = app[start:end]
assert 'nf_avulsa.render_page(' in avulsa_page
assert 'st.tabs(' not in avulsa_page
assert 'GERAÇÃO CONVENCIONAL DE LOTES' not in avulsa_page
assert 'ABRIR GERAÇÃO CONVENCIONAL' not in avulsa_page
assert 'nf_avulsa_abrir_lote' not in avulsa_page

# A impressão avulsa só registra quando os PDFs do lote estão gerados.
date_values={nfkey:date(2026,10,21)}
doc={"record":record,"raw":b"xml","meta":nf,
     "info":{"destinatario":"SETTA ENERGY","cnpj_destinatario":"12345678000190"}}
with patch.object(av,"cte_output_name",return_value="DACTE.pdf"):
    rows=av.build_avulsa_manifest(
        [doc], [{"record":cterecord,"raw":b"xml","meta":cte}],
        date_values,{},lambda _: "FORNECEDOR",
        lambda *a: {"data_chegada":date(2026,10,9),
                    "natureza":"COMPRA DE MATERIA PRIMA",
                    "recebido_por":"TESTE","pre_nota_status":"PRE-NOTA LANCADA"},
        lambda *a:"SEN",
        {av.build_final_name(date(2026,10,21),"123","FORNECEDOR"):b"PDF",
         "DACTE.pdf":b"CTE"},"AVULSA-TST")
assert len(rows)==2 and rows[0]["tipo_documento"]=="NF-e"
assert rows[0]["status"]=="REALIZADO" and rows[1]["status"]=="REALIZADO"
from datetime import datetime, timezone
fixed = datetime(2026, 10, 16, 15, 33, tzinfo=timezone.utc)
with patch.object(av,"cte_output_name",return_value="DACTE.pdf"):
    with_timestamp=av.build_avulsa_manifest(
        [doc], [{"record":cterecord,"raw":b"xml","meta":cte}],
        date_values, {}, lambda _: "FORNECEDOR",
        lambda *a: {"data_chegada":date(2026,10,9), "natureza":"EPI GERA ESTOQUE"},
        lambda *a: "SEN",
        {av.build_final_name(date(2026,10,21),"123","FORNECEDOR"):b"PDF","DACTE.pdf":b"PDF"},
        "AVULSA-TIMESTAMP", pdf_criado_em=fixed,
    )
assert all(r["pdf_criado_em"]==fixed.isoformat() for r in with_timestamp)
assert all(r["recebido_em"]==fixed.isoformat() for r in with_timestamp)
assert rows[0]["pdf_criado_em"] and rows[1]["pdf_criado_em"]
assert all("enviado_em" not in row for row in rows)
assert rows[0]["chave_nfe"]==nfkey and rows[1]["chave_cte"]==ctekey
assert rows[1]["nfs_vinculadas"]=="123"
assert rows[0]["empresa_sigla"]=="SEN" and rows[1]["empresa_sigla"]=="SEN"
assert rows[0]["natureza"]=="COMPRA DE MATERIA PRIMA"
assert rows[0]["pre_nota_em"]=="2026-10-09"
assert rows[0]["carimbo_aplicado"] is False
assert rows[0]["arquivo_final"] in (
    av.build_final_name(date(2026,10,21),"123","FORNECEDOR"),
)
try:
    av.build_avulsa_manifest(
        [doc], [], date_values, {}, lambda _: "FORNECEDOR",
        lambda *a:{},lambda *a:"SEN",{},"AVULSA-TST")
except ValueError: pass
else: raise AssertionError("PDF ausente não pode gerar registro.")

migration=Path("supabase/migrations/20261015_nf_avulsa_registro.sql").read_text("utf-8")
assert "create unique index if not exists nf_processamentos_nfe_chave_uniq" in migration
assert "nf_processamentos_cte_chave_uniq" in migration
assert "on conflict do nothing" in migration
assert "nf_registrar_avulsos" in migration
assert "'REALIZADO'" in migration
assert "enviado_em" in migration
assert "db.register_avulsa_records(rows)" in app
assert "register_records=_register_avulsa_records" in app
avsource=Path("nf_avulsa.py").read_text("utf-8")
assert 'build_avulsa_manifest(' in avsource
assert 'result = register_records(manifest)' in avsource
assert 'pdf_criado_em = datetime.now(timezone.utc)' in avsource
assert 'pdf_criado_em=pdf_criado_em' in avsource
assert 'st.session_state["avulsa_outputs"] = outputs' in avsource
assert avsource.index('result = register_records(manifest)') < avsource.index('st.session_state["avulsa_outputs"] = outputs')

print("NFS_IMPRESSAO_AVULSA_OK")
