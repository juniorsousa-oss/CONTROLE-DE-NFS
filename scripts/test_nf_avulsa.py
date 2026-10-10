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
nf=SimpleNamespace(chave=nfkey, numero_nf="123", cnpj_emitente="12345678000190", emitente="EMITENTE")
cte=SimpleNamespace(chave=ctekey, numero="1", refs_nfe=[nfkey], emitente="TRANSPORTADORA", tomador_nome="SETTA", cnpj_tomador="")
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
print("NFS_IMPRESSAO_AVULSA_OK")
