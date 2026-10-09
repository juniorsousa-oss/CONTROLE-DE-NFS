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
# A barra lateral não pode somar 260px a um Main travado em 100% da viewport.
# O shell divide o espaço com flex, permitindo que os filtros refluam.
shell=Path("setta_shell.py").read_text(encoding="utf-8")
main_rule=shell[shell.index('/* Main precisa ceder a largura'):
                shell.index('[data-testid="stAppViewContainer"] .main .block-container')]
for rule in ("flex:1 1 0%!important;", "width:auto!important;", "min-width:0!important;"):
    assert rule in main_rule, rule
assert "width:100%!important;max-width:100%!important;margin-left:0!important" not in main_rule

# Regressão do fluxo: consultas não podem rerenderizar o app inteiro
# após cada lote, e a escolha de NFs do Protheus deve ser um formulário.
assert "ThreadPoolExecutor(max_workers=min(4, len(records)))" in Path(
    "nf_xml_library.py"
).read_text(encoding="utf-8")
assert 'def prefill_stage2(pending_pre: pd.DataFrame)' in Path(
    "nf_xml_library.py"
).read_text(encoding="utf-8")
assert 'base_missing_select_all = st.checkbox(' not in source
assert '"RETIRAR SELECIONADAS DESTE LOTE"' in source
assert '"nf_stage2_defer_missing_button"' in source
assert 'st.session_state.nf_selected_flow_keys = _remaining' in source
assert 'st.session_state.nf_stage1_selection = set(_remaining)' in source
assert 'not any(' in source
assert 'item.get("vinculado_base")' in source
assert 'progress.empty()\n        st.rerun()\n\n    stats =' not in source

# Auditoria de NF só considera vinculada a NF que realmente existe e
# cujo CNPJ não é conflitante. Faltantes jamais viram "validadas" sozinhas.
import pandas as pd
import re
audit_node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
                and n.name=="_audit_selected_nf_batch")
audit_module=ast.Module(body=[audit_node],type_ignores=[])
ast.fix_missing_locations(audit_module)
namespace={
    "pd":pd,
    "normalized_nf":lambda value: re.sub(r"\D","",str(value or "")).lstrip("0"),
    "digits_only":lambda value: re.sub(r"\D","",str(value or "")),
}
exec(compile(audit_module,"<audit-test>","exec"),namespace)
audit=namespace["_audit_selected_nf_batch"]
selected=pd.DataFrame([
    {"numero_nf":str(i),"cnpj":"12345678000199"} for i in range(1,18)
])
actual=pd.DataFrame([
    {"numero_nf":str(i),"cnpj_fornecedor":"12345678000199"}
    for i in range(1,16)
])
pending=audit(selected,actual)
assert pending["selecionadas"]==17 and pending["vinculadas"]==15
assert {x["NF"] for x in pending["faltantes"]}=={"16","17"}
after_defer=audit(selected.iloc[:15],actual)
assert after_defer["vinculadas"]==15 and not after_defer["faltantes"]
conflict=actual.copy()
conflict.loc[0,"cnpj_fornecedor"]="99999999000199"
invalid=audit(selected.iloc[:15],conflict)
assert any(x["NF"]=="1" for x in invalid["faltantes"])

print("NFS_DASHBOARD_SIDEBAR_FILTERS_OK")
