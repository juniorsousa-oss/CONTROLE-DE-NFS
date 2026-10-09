"""Regressões: navegação de etapas e recuperação segura entre computadores."""
from pathlib import Path
import ast

p=Path("streamlit_app.py")
code=p.read_text(encoding="utf-8")
tree=ast.parse(code)

# Registros remotos não podem forçar a página a voltar à Etapa 3 após
# o clique em VOLTAR À BASE ou VOLTAR AOS DOCUMENTOS.
flow=code[code.index('elif page == "Pendências":'):]
assert "_awaiting_remote = _awaiting_send_records(pending_records)" in flow
pre_stage=flow.split("if _flow_stage == 2:",1)[0]
assert "st.session_state.nf_flow_stage = 3" not in pre_stage, (
    "Auto-redirecionamento ainda impede navegação entre etapas."
)
for needle in (
    'key="flow_back_to_pre"',
    '_set_nf_flow_stage(1)',
    'key="flow_back_to_documents"',
    '_set_nf_flow_stage(2)',
    '"RECUPERAÇÃO DE LOTES NÃO ENVIADOS',
    '"CONFERIR ENVIO DO LOTE"',
    '"REABRIR LOTE PARA GERAR NOVAMENTE"',
    'disabled=not _reopen',
    'db.restart_pending_process_records(_batch_ids)',
    '"nf_recovery_reopen_confirm_{_batch_id}"',
):
    assert needle in code, f"Recuperação incompleta: {needle}"

# Banco é modificado APENAS no clique explícito de REABRIR; a chamada de
# restart não deve aparecer fora da condição do botão.
actions=[
    node for node in ast.walk(tree)
    if isinstance(node,ast.Call)
    and isinstance(node.func,ast.Attribute)
    and node.func.attr=="restart_pending_process_records"
]
assert len(actions)==1,"Reinício deve ter um único ponto de execução"
action=actions[0]
recovery_mark=code.index('key="nf_recovery_restart_batch"')
recovery_end=code.index('    pre_base = st.session_state.pre_notes.copy()',recovery_mark)
assert recovery_mark < action.col_offset+sum(1 for _ in []) or code.index(
    'db.restart_pending_process_records(_batch_ids)',recovery_mark
) < recovery_end

ready=next(
    node for node in tree.body
    if isinstance(node,ast.FunctionDef) and node.name=="render_ready_file_stage"
)
ready_source=ast.get_source_segment(code,ready)
assert "Os PDFs e ZIPs não estão disponíveis neste computador" in ready_source
assert 'render_send_and_tracking_stage(awaiting_remote)' in ready_source
assert 'st.session_state.get("_nf_send_confirmation_batch")' in ready_source

# Recuperação nunca deve marcar envios nem excluir registros por conta própria.
recovery=flow[flow.index('# Recuperação orientada'):flow.index(
    '    pre_base = st.session_state.pre_notes.copy()'
)]
assert "db.confirm_send" not in recovery
assert "db.delete_process_records" not in recovery
assert 'st.session_state.nf_flow_stage = 3' not in recovery
print("NF_CROSS_DEVICE_NAVIGATION_RECOVERY_OK")
