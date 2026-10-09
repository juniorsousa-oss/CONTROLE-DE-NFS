"""Regras de regressão do fluxo real testado em 08/10/2026.

Inspeciona o código em AST sem executar Streamlit nem movimentar NFs reais.
"""
import ast
from pathlib import Path

source=Path("streamlit_app.py").read_text(encoding="utf-8")
tree=ast.parse(source)

def function(name):
    matches=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    assert len(matches)==1, f"Função {name} não encontrada"
    return matches[0]

def form_containing_editor(label):
    found=[]
    for node in ast.walk(tree):
        if not isinstance(node,(ast.With,ast.AsyncWith)):
            continue
        if not any(
            isinstance(i.context_expr,ast.Call)
            and isinstance(i.context_expr.func,ast.Attribute)
            and i.context_expr.func.attr=="form"
            and i.context_expr.args
            and isinstance(i.context_expr.args[0],ast.Constant)
            and i.context_expr.args[0].value==label
            for i in node.items
        ):
            continue
        found.append(node)
    assert len(found)==1, f"Formulário {label} ausente"
    return found[0]

for label in ("nf_stage1_pending_selection_form","missing_mrp_protheus_treat_form"):
    form=form_containing_editor(label)
    assert any(
        isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
        and n.func.id=="_setta_data_editor"
        for n in ast.walk(form)
    ), f"{label} fora do formulário: pode recarregar a cada clique"

for token in [
    '"DESMARCAR TODAS"',
    '"MARCAR TODAS"',
    '"SALVAR DADOS E SELEÇÃO"',
    "nf_stage1_selection_saved",
    "nf_stage1_selection_draft",
    'not st.session_state.get("nf_stage1_selection_saved")',
    "_new_selection = set(st.session_state.get(\"nf_stage1_selection\") or set())",
    "render_mrp_missing_pre_treatments()",
    "nf_documents_analyzed_signature",
    "nf_documents_current_signature",
    'disabled=not bool(documents_to_process)',
    'CT-e VINCULADOS ÀS NFs DESTE LOTE',
    'if updated_count == len(set(selected_send_ids)) == len(awaiting_send):',
    '_reset_nf_session_flow()',
    '"nf_dashboard_filters_form"',
    'dash_followup',
    'dash_search',
    'height=380',
]:
    assert token in source, f"Regra operacional ausente: {token}"

# Regressão Protheus: formulário não pode exigir ação/seleção antes do submit,
# pois o Streamlit só transmite os valores novos quando o botão é acionado.
protheus_func=function("render_mrp_missing_pre_treatments")
protheus_form=form_containing_editor("missing_mrp_protheus_treat_form")
submit_buttons=[
    n for n in ast.walk(protheus_form)
    if isinstance(n,ast.Call)
    and isinstance(n.func,ast.Attribute)
    and n.func.attr=="form_submit_button"
]
action_buttons=[
    n for n in submit_buttons
    if n.args and isinstance(n.args[0],ast.Constant)
    and n.args[0].value=="APLICAR TRATATIVA"
]
assert len(action_buttons)==1, "Tratativa do Protheus precisa de um único submit da ação"
assert len(submit_buttons)==3, "Marcar/desmarcar também devem enviar o mesmo formulário"
assert not any(k.arg=="disabled" for k in action_buttons[0].keywords), (
    "Submit da tratativa não pode depender da seleção antes da submissão"
)
protheus_source=ast.get_source_segment(source,protheus_func)
for check in (
    'if submit_mrp_treatment:',
    'if selected.empty:',
    'if action == "Escolha uma ação":',
    'if action == "Adicionar às Pré-notas pendentes":',
    'if not missing_receiver.empty:',
):
    assert check in protheus_source, f"Validação após clique ausente: {check}"
assert (
    protheus_source.index('if submit_mrp_treatment:')
    < protheus_source.index('if selected.empty:')
    < protheus_source.index('if action == "Escolha uma ação":')
    < protheus_source.index('if action == "Adicionar às Pré-notas pendentes":')
), "As validações das NFs devem ocorrer depois da submissão."

# Simulação do problema operacional: 17 selecionadas, somente 15 processadas.
import pandas as pd
from collections import Counter
node=function("_audit_selected_nf_batch")
scope={
    "pd":pd,
    "normalized_nf":lambda v:str(v or "").strip().lstrip("0") or "0",
    "digits_only":lambda v:"".join(x for x in str(v or "") if x.isdigit()),
}
exec(compile(ast.Module(body=[node],type_ignores=[]),"audit_test","exec"),scope)
audit=scope["_audit_selected_nf_batch"]
selected=pd.DataFrame([
    {"numero_nf":f"{i:05d}","cnpj":"11111111000191"}
    for i in range(1,18)
])
processed=pd.DataFrame([
    {"numero_nf":str(i),"cnpj_fornecedor":"11111111000191"}
    for i in range(1,16)
])
out=audit(selected,processed)
assert out["selecionadas"]==17 and out["vinculadas"]==15,out
assert [x["NF"] for x in out["faltantes"]]==["16","17"],out
assert not out["extras"],out
out_complete=audit(selected,pd.concat([
    processed,
    pd.DataFrame([
        {"numero_nf":"16","cnpj_fornecedor":"11111111000191"},
        {"numero_nf":"17","cnpj_fornecedor":"11111111000191"},
    ]),
],ignore_index=True))
assert not out_complete["faltantes"] and out_complete["vinculadas"]==17
wrong_supplier=audit(
    selected.head(1),
    pd.DataFrame([{"numero_nf":"1","cnpj_fornecedor":"99999999000199"}]),
)
assert wrong_supplier["faltantes"], "Nunca vincular nota a CNPJ divergente."
assert 'expanded=bool(st.session_state.get("_nf_missing_mrp_keep_open", False))' in source
assert 'st.session_state.nf_selected_flow_keys = set(_active_keys)' in source
assert '_lot_audit=_audit_selected_nf_batch' in source
assert 'if invalid_mask.any() or duplicate.any():' in source

ready=function("render_ready_file_stage")
ready_lines=ast.get_source_segment(source,ready)
assert ready_lines.index('CT-e VINCULADOS ÀS NFs DESTE LOTE') < ready_lines.index('"GERAR ARQUIVO PRONTO PARA IMPORTAÇÃO"')

dash_marker=source.index('st.markdown("#### FILTROS DE DOCUMENTOS ENVIADOS")')
dash_start=source.index('        display_cols = [',dash_marker)
dash_end=source.index('        table = view[display_cols]',dash_start)
dashboard_cols=source[dash_start:dash_end]
for redundant in ['"status",','"prazo_lancamento",','"lancamento_verificado_em",']:
    assert redundant not in dashboard_cols, f"Coluna redundante reapareceu: {redundant}"

print("NFS_FLOW_REAL_TEST_0810_REGRESSION_OK")
