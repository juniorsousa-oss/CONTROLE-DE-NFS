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
assert len(submit_buttons)==1, "Tratar NF do Protheus precisa de um único submit"
assert not any(k.arg=="disabled" for k in submit_buttons[0].keywords), (
    "Submit do Protheus não pode depender de seleção/tratativa pré-submissão"
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
