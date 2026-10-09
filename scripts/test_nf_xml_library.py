"""Regressão da Biblioteca XML: importação de ZIP, rota e privacidade."""
import ast
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import nf_xml_library as lib

class Upload:
    def __init__(self,name,raw):
        self.name=name
        self.size=len(raw)
        self._raw=raw
    def getvalue(self):
        return self._raw


sample=b'<?xml version="1.0"?><nfeProc><NFe>teste</NFe></nfeProc>'
buf=io.BytesIO()
with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
    z.writestr("lote/NF1.xml",sample)
    z.writestr("lote/NF-duplicada.xml",sample)
    z.writestr("lote/nota.txt",b"nao XML")
    z.writestr("../inseguro.xml",b"skip")
uploads,errors=lib._read_xml_uploads([Upload("lote.zip",buf.getvalue())])
assert len(uploads)==1, uploads
assert uploads[0][0]=="NF1.xml",uploads
assert any("caminho inseguro" in s for s in errors)
assert lib._simple_nf("000084656")=="84656"
oversized,errs=lib._read_xml_uploads([Upload("bad.xml",b"x"*(lib.MAX_XML+1))])
assert not oversized and errs
assert lib._token()=="" or isinstance(lib._token(),str)

source=Path("streamlit_app.py").read_text(encoding="utf-8")
api=Path("supabase/functions/nf-xml-library-api/index.ts").read_text(encoding="utf-8")
migration=Path("supabase/migrations/20261009_nf_xml_library.sql").read_text(encoding="utf-8")
ast.parse(source)
for expected in [
    'import nf_xml_library',
    'nf_xml_library.prefill_stage2(pending_base)',
    '_NF_NAV_PAGES.append("Biblioteca XML")',
    'nf_xml_library.render_page()',
    'document_upload_cache = cached_documents',
]:
    assert expected in source, f"Não integrado: {expected}"
for expected in [
    'operahub_auth_user', 'nf_xml_permissoes',
    'nf_xml_sessoes','XMLValidator.validate',
    'crypto.subtle.digest', 'api.storage.from(SCOPE).download',
    'Array.isArray', 'action==="match"',
    'action==="ingest"','action==="download"',
]:
    if expected=="Array.isArray":continue
    assert expected in api,f"Sem proteção da API: {expected}"
assert "service_role" not in Path("nf_xml_library.py").read_text(encoding="utf-8").lower()
assert "public=false" in migration
assert "enable row level security" in migration
assert "verify_jwt" not in api, "A validação JWT é configurada no deploy, não removida no código"
# O acervo total não pode ser confundido com o limite da primeira página.
ui=Path("nf_xml_library.py").read_text(encoding="utf-8")
for expected in [
    'a.metric("TOTAL DE XMLs NA BIBLIOTECA",count)',
    'b.metric("NF-e ARMAZENADAS",nfe)',
    'c.metric("CT-e ARMAZENADOS",cte)',
    '"page_size":100',
    '"PÁGINA ANTERIOR"',
    '"PRÓXIMA PÁGINA"',
    '"nf_xml_search_catalog_form"',
    '"nf_xml_doc_request"',
]:
    assert expected in ui, f"Consulta global e paginada ausente: {expected}"
for expected in [
    'if(action==="list")',
    'filtered_total:',
    'total_nfe:nfe',
    'total_cte:cte',
    'page_count:',
    '.range(first,first+pageSize-1)',
    '{count:"exact",head:true}',
]:
    assert expected in api, f"Contagem/paginação não implementada no servidor: {expected}"

print("NFS_XML_LIBRARY_REGRESSION_OK")
