"""Regressão CT-e: descoberta, controle de elegibilidade e ZIP real sintético."""
import ast
import io
import re
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from nf_processor import parse_operational_due_date, build_final_name
from cte_generator import cte_output_name
from cte_generator import cte_zip_safe_name, cte_supplier_from_rows
from nf_batch_integrity import validate_batch_selection, validate_zip_manifest

app=Path("streamlit_app.py").read_text(encoding="utf-8")
client=Path("nf_xml_library.py").read_text(encoding="utf-8")
edge=Path("supabase/functions/nf-xml-library-api/index.ts").read_text(encoding="utf-8")
tree=ast.parse(app)
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef)
       and n.name in {"_cte_zip_readiness","make_zip_outputs"}]
assert len(nodes)==2

# Não se pode consultar CT-es apenas pelas NF-e com CNPJ previamente confirmado.
assert "[...selected,...candidatosSemCnpj]" in edge
assert "if(keys.size)" in edge
assert 'linkedCte=(cte||[]).filter' in edge
assert '"cte_expected_keys": cte_expected_keys' in client
assert '"match_version": 2' in client

def digits(value):
    return re.sub(r"\D", "", str(value or ""))
nfe_key = "31" + "2610" + "14524129000103" + "55" + "001" + "000010913" + "1" + "12345678" + "0"
cte_key = "31" + "2610" + "99887766000190" + "57" + "001" + "000987654" + "1" + "12345678" + "0"
assert len(nfe_key) == len(cte_key) == 44

class State(dict):
    def __getattr__(self,k):
        return self[k]
    def __setattr__(self,k,v):
        self[k] = v

state=State(
    nf_stage2_search_started=True,
    nf_xml_auto_stats={
        "cte_expected_keys":[cte_key], "cte":1,
        "download_errors":0, "match_version":2,
    },
    cte_links=[],
    cte_ignored_non_setta=[],
    document_link_stats={},
    pdfs={"nf-1":{"bytes":b"%PDF-1.4\nfake-pdf"}},
    last_generation_audit={},
    nf_selected_flow_keys={"10913|SAREL"},
    nf_stage2_batch_keys={"10913|SAREL"},
    nf_stage2_batch_snapshot=pd.DataFrame([
        {"numero_nf":"10913","fornecedor":"SAREL","cnpj":"14524129000103"}
    ]),
)
st=SimpleNamespace(session_state=state)
names={
    "pd":pd,"st":st, "digits_only":digits, "date":date,
    "now_local":lambda:datetime(2026,10,10,9,0),
    "uuid":uuid,"io":io,"zipfile":zipfile,
    "nf_package_class":lambda _: "MP",
    "normalized_nf":lambda v:digits(v).lstrip("0"),
    "normalized_business_date":lambda _:date(2026,10,9),
    "parse_operational_due_date":parse_operational_due_date,
    "build_final_name":build_final_name,
    "cte_zip_safe_name":cte_zip_safe_name,
    "validate_batch_selection":validate_batch_selection,
    "validate_zip_manifest":validate_zip_manifest,
    "flow_nf_key":lambda row: digits(row.get("numero_nf")).lstrip("0")+"|"+str(row.get("fornecedor") or "").strip(),
    "selected_pending_pre_notes":lambda: state.nf_stage2_batch_snapshot.copy(),
    "_current_nf_zip_signature":lambda *args:"test-batch-token",
    "cte_supplier_from_rows":cte_supplier_from_rows,
    "apply_operational_stamp":lambda raw,**kw:raw,
    "is_cte_document_type":lambda typ:str(typ).strip().upper()=="CT-E",
}
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),
             "<cte-zip>", "exec"),names)
readiness=names["_cte_zip_readiness"]
make_zips=names["make_zip_outputs"]

df=pd.DataFrame([{
    "file_id":"nf-1", "numero_nf":"10913",
    "nome_sugerido":"VENC. 20.10 - 10913 - SAREL.pdf",
    "arquivo_original":"sarel.xml","empresa_sigla":"SEN",
    "natureza":"COMPRA DE MATERIA PRIMA",
    "prioridade_mrp":False,
    "pre_nota_recebedor":"OPERADOR",
    "cr":"1001","desc_cr":"MATERIAIS",
    "pre_nota_em":date(2026,10,9),"serie":"1",
    "chave_nfe":nfe_key,"cnpj_fornecedor":"14524129000103",
    "fornecedor_padrao":"SAREL","pre_nota_fornecedor":"SAREL",
    "vencimento":date(2026,10,20),
    "metodo_fornecedor":"XML","confianca":98,
}])
assert readiness()["missing"] == [cte_key]
try:
    make_zips(df)
except ValueError as exc:
    assert "CT-e" in str(exc)
else:
    raise AssertionError("Sem CT-e relacionado não pode liberar ZIP!")

state.cte_links=[{
    "cte_id":"cte01","chave_cte":cte_key,"numero_cte":"987654",
    "transportadora":"TRANSPORTADORA TESTE",
    "arquivo_final":"CTE-987654.pdf","arquivo_original":"cte.xml",
    "bytes":b"%PDF-1.4\nfake-dacte",
    "linked_file_ids":["nf-1"], "linked_nf_numbers":["10913"],
    "refs_nfe":[nfe_key],"origem":"XML",
}]
outputs,manifest=make_zips(df)
assert len(manifest)==2,manifest
assert {r["tipo_documento"] for r in manifest} == {"CT-e","NF-e"}
assert len(outputs)==2,outputs.keys()
cte_zip=[v for k,v in outputs.items() if k.startswith("CTE")][0]
with zipfile.ZipFile(io.BytesIO(cte_zip)) as inner:
    expected = cte_output_name(
        SimpleNamespace(numero="987654", emitente="TRANSPORTADORA TESTE", chave=cte_key),
        ["10913"], "SAREL",
    )
    assert inner.namelist()==[expected]
    assert "SAREL" in expected
    assert inner.read(expected)==b"%PDF-1.4\nfake-dacte"
assert state.last_generation_audit["cte_gerados"] == 1

# A chave da NF é estável, mesmo quando o file_id muda na reanálise.
state.cte_links[0]["linked_file_ids"]=["id-antigo"]
keys_only, manifest_only=make_zips(df)
assert sum(x["tipo_documento"]=="CT-e" for x in manifest_only)==1
with zipfile.ZipFile(io.BytesIO(
    next(data for name,data in keys_only.items() if name.startswith("CTE"))
)) as archive:
    assert expected in archive.namelist()
# Restaura o ID normal para os demais cenários.
state.cte_links[0]["linked_file_ids"]=["nf-1"]

# Remessa fiscal referenciada pelo CT-e, mas sem pré-nota: gera PDF
# separado, não altera o total de NF-e do lote principal.
aux_key = (
    "31" + "2610" + "14524129000103" + "55" + "001" +
    "000034429" + "1" + "12345678" + "0"
)
assert len(aux_key) == 44
state.cte_links[0]["refs_nfe"] = [nfe_key, aux_key]
state.cte_auxiliary_remessas = {
    aux_key: {
        "chave": aux_key, "numero": "34429", "cnpj": "14524129000103",
        "fornecedor": "SAREL", "natureza_fiscal": "SIMPLES REMESSA",
        "arquivo_final": "NF-34429 - REMESSA SEM PRE-NOTA.pdf",
        "bytes": b"%PDF-1.4 AUXILIAR",
    }
}
remessa_outputs,remessa_manifest=make_zips(df)
assert len(remessa_outputs)==3
assert len(remessa_manifest)==3
assert state.last_generation_audit["nf_geradas"]==1
assert state.last_generation_audit["nf_remessas_auxiliares"]==1
remessas = [
    r for r in remessa_manifest
    if r.get("origem_dados")=="REMESSA_AUXILIAR_SEM_PRE_NOTA"
]
assert len(remessas)==1 and remessas[0]["natureza"]=="SIMPLES REMESSA"
archive_bytes = next(
    data for name,data in remessa_outputs.items()
    if name.startswith("REMESSAS SEM PRE-NOTA")
)
with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
    assert archive.namelist()==["NF-34429 - REMESSA SEM PRE-NOTA.pdf"]
    assert archive.read(archive.namelist()[0])==b"%PDF-1.4 AUXILIAR"
with zipfile.ZipFile(io.BytesIO(
    next(v for k,v in remessa_outputs.items() if k.startswith("CTE"))
)) as archive:
    ctename=archive.namelist()[0]
    assert "NF-10913+34429" in ctename
    assert "K" not in ctename.split(" - ")[-1]

# A inclusão sem XML validado ou fora das referências permanece bloqueada.
state.cte_auxiliary_remessas={}
try:
    make_zips(df)
except ValueError as exc:
    assert "CT-e" in str(exc) or "LOTE BLOQUEADO" in str(exc)
else:
    raise AssertionError("Não pode omitir uma remessa ainda referenciada pelo CT-e.")
state.cte_links[0]["refs_nfe"]=[nfe_key]

# A exclusão fiscal documentada para tomador não-SETTA é permitida; não cria DACTE.
state.cte_links=[]
state.cte_ignored_non_setta=[{"chave_cte":cte_key,"tomador":"OUTRA EMPRESA"}]
ok=readiness()
assert not ok["errors"] and ok["excluded"]==1
outputs,manifest=make_zips(df)
assert len(outputs)==1 and all(x["tipo_documento"]=="NF-e" for x in manifest)
assert state.last_generation_audit["cte_excluidos_tomador"]==1

# Mesmo um CT-e previamente vinculado não pode sumir da empresa/ZIP
# se perder o ID da NF após reanálise.
state.cte_ignored_non_setta=[]
state.cte_links=[{
    "chave_cte":cte_key, "numero_cte":"987654","arquivo_final":"DACTE.pdf",
    "bytes":b"pdf", "linked_file_ids":["old-file-id"],
}]
try:
    make_zips(df)
except ValueError as exc:
    assert "CT-e" in str(exc)
else:
    raise AssertionError("Perda do vínculo não pode produzir ZIP NF-only")

print("NFS_CTE_ZIP_GENERATION_OK")
