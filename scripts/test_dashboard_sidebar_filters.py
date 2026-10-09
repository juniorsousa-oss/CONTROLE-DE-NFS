"""Dashboard: filtros permanecem ao abrir/fechar a lateral do SETTA.

Teste estático das estruturas do Streamlit: impede retorno a quatro colunas
rígidas, alteração da pesquisa fora do submit e CSS que corta os inputs.
"""
import ast
from pathlib import Path

source=Path("streamlit_app.py").read_text(encoding="utf-8")
tree=ast.parse(source)

assert 'with st.form("nf_dashboard_filters_form", clear_on_submit=False):' in source
start=source.index('with st.form("nf_dashboard_filters_form"')
end=source.index('if clear_filters:',start)
layout=source[start:end]
assert 'st.columns(2, gap="medium")' in layout
assert 'st.columns([1, 2], gap="medium")' in layout
assert 'st.columns([1,1,1.4,2])' not in layout
assert 'apply_filters = find_col.form_submit_button(' in layout
assert 'clear_filters = clear_col.form_submit_button(' in layout

# Pesquisa só muda quando o operador clica em aplicar, não ao abrir menu.
pos_apply=source.index('if apply_filters:',end)
pos_state=source.index('st.session_state["nf_dash_applied"] = {',pos_apply)
pos_filter=source.index('_active_filters = dict(st.session_state.get("nf_dash_applied")',pos_state)
assert pos_apply < pos_state < pos_filter
filtered=source[pos_filter:source.index('st.caption(f"EXIBINDO',pos_filter)]
for token in (
    '_active_filters["tipo"]',
    '_active_filters["empresa"]',
    '_active_filters["acompanhamento"]',
    '_active_filters["pesquisa"]',
):
    assert token in filtered, token
assert "view=view[view[" not in filtered, "Filtro legado não deve substituir estado aplicado"

# Menu executa callbacks separados; não limpa os filtros já aplicados.
for fn in ("_setta_toggle_sidebar", "_setta_close_sidebar"):
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==fn)
    code=ast.get_source_segment(source,node)
    assert "nf_dash_applied" not in code
assert ':has(.st-key-nf_dash_search)' in source
assert 'flex-wrap:wrap!important;' in source
assert 'min-width:min(100%,215px)!important;' in source
print("NFS_DASHBOARD_SIDEBAR_FILTERS_OK")
