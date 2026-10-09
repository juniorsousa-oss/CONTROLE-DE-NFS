"""Regressão do envio incremental sem XMLs duplicados (sem comunicação com rede)."""
import hashlib
from unittest.mock import patch

import nf_xml_library as lib

def fixture(key: str, marker: str="A") -> bytes:
    if key[20:22]=="57":
        return ('<cteProc><CTe><infCte Id="CTe'+key+'"><ide><nCT>'+marker+
                '</nCT></ide></infCte></CTe></cteProc>').encode()
    return ('<nfeProc><NFe><infNFe Id="NFe'+key+'"><ide><nNF>'+marker+
            '</nNF></ide></infNFe></NFe></nfeProc>').encode()

def key(model: str, suffix: int) -> str:
    return "0"*20+model+f"{suffix:022d}"

existing_key=key("55",1)
new_key=key("57",2)
conflicting_key=key("55",3)
old=fixture(existing_key)
candidate=fixture(new_key)
first=fixture(conflicting_key,"C")
second=fixture(conflicting_key,"D")
unknown=b"<xml><outro>sem chave</outro></xml>"

assert lib._fiscal_key(old)==existing_key
assert lib._fiscal_key(candidate)==new_key
assert lib._fiscal_key(unknown)==""
assert lib._fiscal_key(b'<nota Id="NFe'+existing_key.encode()+b'">')==""

calls=[]
def fake_api(action,payload,timeout=60):
    assert action=="check_existing"
    calls.append(payload)
    results=[]
    for row in payload["items"]:
        status="DUPLICADO" if row["chave"]==existing_key else "NOVO"
        results.append({"chave":row["chave"],"status":status})
    return {"results":results}

with patch.object(lib,"library_api",side_effect=fake_api):
    queued,reports=lib._preflight_files([
        ("antigo.xml",old),("novo.xml",candidate),
        ("conflito-a.xml",first),("conflito-b.xml",second),
        ("sem-chave.xml",unknown),
    ])
assert [i["filename"] for i in queued]==["novo.xml","sem-chave.xml"],queued
assert sum(x["RESULTADO"]=="DUPLICADO" for x in reports)==1
assert sum(x["RESULTADO"]=="CONFLITO" for x in reports)==2
assert len(calls)==1 and len(calls[0]["items"])==2,calls
assert all("raw" not in d and "raw_base64" not in d for d in calls[0]["items"])
assert calls[0]["items"][0]["sha256"]==hashlib.sha256(old).hexdigest()

# A conferência deve abortar se a biblioteca não responder, sem transferir tudo.
with patch.object(lib,"library_api",return_value={"results":[]}):
    try:lib._preflight_files([("antigo.xml",old)])
    except RuntimeError as exc:
        assert "incompleta" in str(exc)
    else:raise AssertionError("Falha de conferência não pode autorizar upload.")

class Response:
    ok=True
    status_code=200
    def json(self):
        return {"ok":True,"data":{"resultado":"INCLUIDO","chave":new_key}}

with patch.object(lib.requests,"post",return_value=Response()) as post:
    result=lib._upload_new_xml(
        {"filename":"novo.xml","raw":candidate},"https://example.invalid",
        {"Authorization":"Bearer key"},"fake-token"
    )
assert result["RESULTADO"]=="INCLUIDO"
sent=post.call_args.kwargs["json"]
assert sent["payload"]["token"]=="fake-token"
assert sent["action"]=="ingest"
assert "raw_base64" in sent["payload"]
print("NFS_XML_INCREMENTAL_UPLOAD_OK")
