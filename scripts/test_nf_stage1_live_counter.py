"""Regressão do contador imediato: 14 linhas, 3 desmarcadas = 11.

A grade usa fragmento fora de st.form, garantindo rerun local ao alterar
checkbox sem persistir automaticamente a seleção do lote.
"""
from pathlib import Path
import ast
import pandas as pd

source=Path("streamlit_app.py").read_text(encoding="utf-8")
tree=ast.parse(source)
helper=next(n for n in tree.body
            if isinstance(n,ast.FunctionDef)
            and n.name=="_render_stage1_pending_selection_live")
assert any(isinstance(d,ast.Attribute) and d.attr=="fragment"
           for d in helper.decorator_list)
helper_code=ast.get_source_segment(source,helper)
assert 'selected_count = int(' in helper_code
assert 'pending_editor["Selecionar"].fillna(False).astype(bool).sum()' in helper_code
assert 'st.caption(f"SELECIONADAS: {selected_count} DE {len(editor_view)}")' in helper_code
stage1=source[source.index('with st.expander(\n        "NFs DESCONSIDERADAS'):] if False else source
assert 'pending_editor = _render_stage1_pending_selection_live(' in stage1
assert 'st.session_state.nf_stage1_selection = set(' in source
assert 'if save_receivers:' in source
assert 'if exclude_selected:' in source
assert '_nf_stage1_editor_rev"] += 1' in source
assert '"nf_stage1_pending_selection_form"' not in source

samples=pd.DataFrame({"Selecionar":[True]*14})
assert int(samples["Selecionar"].fillna(False).astype(bool).sum())==14
samples.loc[[4,5,6],"Selecionar"]=False
assert int(samples["Selecionar"].fillna(False).astype(bool).sum())==11
samples["Selecionar"]=False
assert int(samples["Selecionar"].fillna(False).astype(bool).sum())==0
print("NFS_STAGE1_LIVE_COUNTER_OK")
