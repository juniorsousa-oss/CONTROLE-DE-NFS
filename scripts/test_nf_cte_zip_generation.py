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
cte_key = "0" * 20 + "57" + "0" * 22
nfe_key = "0" * 20 + "55" + "0" * 22

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
)
st=SimpleNamespace(session_state=state)
names={
    "pd":pd,"st":st, "digits_only":digits, "date":date,
    "now_local":lambda:datetime(2026,10,10,9,0),
    "uuid":uuid,"io":io,"zipfile":zipfile,
    "nf_package_class":lambda _: "MP",
    "normalized_nf":lambda v:digits(v).lstrip("0"),
    "normalized_business_date":lambda _:date(2026,10,9),
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
    "fornecedor_padrao":"SAREL","vencimento":date(2026,10,20),
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
    assert inner.namelist()==["CTE-987654.pdf"]
    assert inner.read("CTE-987654.pdf")==b"%PDF-1.4\nfake-dacte"
assert state.last_generation_audit["cte_gerados"] == 1

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
