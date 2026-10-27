"""Remessa sem pré-nota: validação fiscal e segregação dos documentos.

Não acessa produção; o XML e o DANFE são substituídos por fixtures sintéticas.
"""
import base64
from unittest.mock import patch
from types import SimpleNamespace

from nf_batch_integrity import validate_batch_selection, cte_reference_coverage
import nf_remessa_auxiliary as remessa


def key(number, issuer):
    return ("31" + "2610" + issuer + "55" + "001" +
            number.zfill(9) + "1" + "12345678" + "0")

issuer = "43071109000122"
k293, k501 = key("344293", issuer), key("344501", issuer)
record = {"id": "fiscal-record", "numero": "344293",
          "chave": k293, "cnpj_emitente": issuer}
info = {"numero_nf": "344293", "cnpj_fornecedor": issuer,
        "natureza_fiscal": "SIMPLES REMESSA", "fornecedor_lido": "TASCO LIMITADA"}
meta = SimpleNamespace(emitente="TASCO LIMITADA")

def api(action, payload, timeout=30):
    if action == "match":
        assert payload["nfs"][0]["chave"] == k293
        return {"nfe": [record]}
    if action == "download":
        assert payload["id"] == record["id"]
        return {"raw_base64": base64.b64encode(b"<xml-fixture/>").decode()}
    raise AssertionError(action)

with patch.object(remessa.nf_xml_library,"library_api",side_effect=api),\
     patch.object(remessa,"safe_nfe_record",return_value=(meta,info)),\
     patch.object(remessa,"generate_danfe_pdf",return_value=b"%PDF-1.4 remessa"):
    result = remessa.load_auxiliary_remessa(k293,{k293,k501},{issuer})

assert result["numero"] == "344293"
assert result["chave"] == k293
assert result["natureza_fiscal"] == "SIMPLES REMESSA"
assert result["arquivo_final"] == "NF-344293 - REMESSA SEM PRE-NOTA.pdf"
assert result["bytes"].startswith(b"%PDF")
cte = {"numero_cte": "13287494", "chave_cte": "CHAVE-C-1",
       "refs_nfe":[k293,k501], "linked_file_ids":["pdf-501"],
       "linked_nf_numbers":["344501"]}
selected = [{"_selection_key":"344501|TASCO", "numero_nf":"344501","cnpj":issuer}]
work = [{"_selection_key":"344501|TASCO", "numero_nf":"344501",
         "cnpj_fornecedor":issuer,"chave_nfe":k501,"file_id":"pdf-501"}]
pdfs = {"pdf-501":{"bytes":b"%PDF-1.4"}}
aux = {k293:result}
assert cte_reference_coverage(cte,work,aux)["complete"]
validate_batch_selection({"344501|TASCO"},selected,work,pdfs,[cte],aux)
try:
    validate_batch_selection({"344501|TASCO"},selected,work,pdfs,[cte],{})
except ValueError:
    pass
else:
    raise AssertionError("CT-e não pode omitir remessa sem validação.")

# Sem inventar uma natureza para documento genérico ou de compra.
with patch.object(remessa,"safe_nfe_record",return_value=(
    meta,{**info,"natureza_fiscal":"COMPRA DE MATERIA PRIMA"}
)):
    try:
        remessa.validate_auxiliary_remessa(record,b"<xml/>",{k293},{issuer})
    except ValueError as exc:
        assert "não confirma remessa" in str(exc)
    else:
        raise AssertionError("Uma compra não pode virar remessa auxiliar.")
with patch.object(remessa,"safe_nfe_record",return_value=(meta,info)):
    for keys, issuers in [({k501},{issuer}),({k293},{"82110818000393"})]:
        try:
            remessa.validate_auxiliary_remessa(record,b"<xml/>",keys,issuers)
        except ValueError:
            pass
        else:
            raise AssertionError("Chave ou emissor divergentes não podem passar.")

# Não contaminar seleção original ou a natureza de cobrança.
assert len(work) == 1 and work[0]["numero_nf"] == "344501"
assert "344293" not in {row["numero_nf"] for row in work}
print("NFS_CTE_AUXILIARY_REMESSA_OK")
