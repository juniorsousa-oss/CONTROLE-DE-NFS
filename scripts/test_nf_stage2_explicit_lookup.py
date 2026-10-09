"""Regressão funcional: entrada na etapa 2 nunca dispara consulta.

A consulta exige clique explícito e preserva a seleção, sem precisar
acessar XMLs reais nem alterar o banco fiscal de produção.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import nf_xml_library

source=Path("streamlit_app.py").read_text(encoding="utf-8")
tree=ast.parse(source)
functions={
    node.name:node for node in tree.body
    if isinstance(node,ast.FunctionDef)
}
assert "_start_stage2_document_search" in functions
assert "render_document_linking_stage" in functions
handler=functions["_start_stage2_document_search"]
render=functions["render_document_linking_stage"]
render_src=ast.get_source_segment(source,render)
helper_src=ast.get_source_segment(source,handler)

# A tela inicial se monta antes de qualquer rede. Só o clique acessa a API.
assert 'key="nf_stage2_start_search"' in render_src
assert '"INICIAR BUSCA DE DOCUMENTOS"' in render_src
assert 'with st.expander("UPLOAD MANUAL DE XML/PDF · CONTINGÊNCIA", expanded=False)' in render_src
assert render_src.index('key="nf_stage2_start_search"') < render_src.index(
    '_start_stage2_document_search(pending_base, requested=True)'
)
assert 'if start_search:' in render_src
assert 'nf_xml_library.prefill_stage2(pending_base)' not in render_src
assert "if not requested or pending_base.empty:" in helper_src
assert 'st.session_state.pop("nf_xml_auto_signature", None)' in helper_src

# A função de biblioteca deixou de instanciar seu antigo segundo botão.
library_tree=ast.parse(Path("nf_xml_library.py").read_text(encoding="utf-8"))
lib_method=next(node for node in library_tree.body
                if isinstance(node,ast.FunctionDef) and node.name=="prefill_stage2")
button_calls=[
    node for node in ast.walk(lib_method)
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
    and node.func.attr=="button"
]
assert not button_calls, "A biblioteca não pode criar botões nem buscar por conta própria"

# Reproduz as transições sem rede: o comando é chamado apenas no clique.
class Session(dict):
    def __getattr__(self,key):
        return self[key]
    def __setattr__(self,key,value):
        self[key]=value

class FakeXML:
    def __init__(self):
        self.calls=[]
    def prefill_stage2(self,base):
        self.calls.append(base.copy())

state=Session(
    nf_xml_auto_signature="CONSULTA_ANTIGA",
    nf_stage2_search_started=False,
    document_upload_cache=[],
    document_reprocess_needed=False,
)
fake=FakeXML()
ns={
    "st":SimpleNamespace(session_state=state),
    "pd":pd,
    "nf_xml_library":fake,
}
mod=ast.Module(body=[handler],type_ignores=[])
ast.fix_missing_locations(mod)
exec(compile(mod,"<stage2-search>","exec"),ns)
start=ns["_start_stage2_document_search"]
base=pd.DataFrame([{"numero_nf":"4699","fornecedor":"EXEMPLO"}])
assert start(base,False) is False
assert not fake.calls
assert state.nf_xml_auto_signature=="CONSULTA_ANTIGA"
assert not state.nf_stage2_search_started
assert start(base.iloc[:0],True) is False
assert not fake.calls
assert start(base,True) is True
assert len(fake.calls)==1
assert state.nf_stage2_search_started
assert "nf_xml_auto_signature" not in state
assert not state.document_reprocess_needed
state.nf_xml_auto_signature="RESULTADO_ANTERIOR"
state.document_upload_cache=[{"name":"NF_4699.xml","raw":b"XML"}]
assert start(base,True)
assert len(fake.calls)==2
assert "nf_xml_auto_signature" not in state
assert state.document_reprocess_needed
assert state.document_upload_cache[0]["name"]=="NF_4699.xml"

# A nova seleção difere do LOTE ANTERIOR, mesmo quando o formulário já
# atualizou nf_selected_flow_keys.
assert '"nf_stage2_batch_keys": set()' in source
assert 'st.session_state.nf_stage2_batch_keys = set(_new_selection)' in source
assert 'st.session_state.get("nf_stage2_batch_keys") or set()' in source
assert 'st.session_state.nf_stage2_search_started = False' in source
assert 'st.session_state.pop("nf_xml_auto_stats", None)' in source

print("NFS_STAGE2_EXPLICIT_LOOKUP_OK")
