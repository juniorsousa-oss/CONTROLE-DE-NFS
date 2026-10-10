"""Regression functional: fixed stage-1 batch survives stage-2/3 status changes.

Tests 17 selected NFs against 17 linked XML results using synthetics only.
No access to real invoices, storage or production databases.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import re
import pandas as pd

source = Path("streamlit_app.py").read_text(encoding="utf-8")
tree = ast.parse(source)
names = {
    "_activate_nf_document_batch",
    "selected_pending_pre_notes",
    "_selected_nf_selection_gaps",
    "_audit_selected_nf_batch",
}
nodes = [
    n for n in tree.body
    if isinstance(n, ast.FunctionDef) and n.name in names
]
assert len(nodes) == 4

class State(dict):
    def __getattr__(self, key):
        return self[key]
    def __setattr__(self, key, value):
        self[key] = value

def number(v):
    v = re.sub(r"\D", "", str(v or ""))
    return v.lstrip("0") or ("0" if v else "")
def cnpj(v):
    return re.sub(r"\D", "", str(v or ""))
def key(row):
    return number(row.get("numero_nf")) + "|" + cnpj(row.get("cnpj"))

records = pd.DataFrame([
    {"numero_nf": str(n), "cnpj": "12345678000199",
     "fornecedor": "EXEMPLO", "status": "Pré-nota lançada"}
    for n in range(1, 18)
])
selected = set(records.apply(key, axis=1))
state = State(
    pre_notes=records.copy(),
    nf_selected_flow_keys=set(),
    nf_stage2_batch_keys=set(),
    nf_stage2_batch_snapshot=pd.DataFrame(),
    analysis=pd.DataFrame(),
    nf_stage1_selection_saved=True,
)
def set_stage(n):
    state.nf_flow_stage = n
scope = {
    "st": SimpleNamespace(session_state=state),
    "pd": pd, "normalized_nf": number, "digits_only": cnpj,
    "flow_nf_key": key,
    "_set_nf_flow_stage": set_stage,
    "current_pending_pre_notes": lambda: pd.DataFrame(),
}
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
             "<batch-test>", "exec"), scope)

enter = scope["_activate_nf_document_batch"]
active = scope["selected_pending_pre_notes"]
gaps = scope["_selected_nf_selection_gaps"]
audit = scope["_audit_selected_nf_batch"]

assert enter(selected)
assert state.nf_flow_stage == 2
assert len(state.nf_stage2_batch_snapshot) == 17
assert len(active()) == 17

# History reports the invoice as already processed. The dynamic pending
# list becomes empty; the current batch must not disappear.
state.processed_document_count = 17
assert len(active()) == 17
assert gaps() == []
processed = pd.DataFrame([
    {"numero_nf": str(n), "cnpj_fornecedor": "12345678000199"}
    for n in range(1, 18)
])
finished = audit(active(), processed)
assert (finished["selecionadas"], finished["vinculadas"]) == (17, 17)
assert not finished["faltantes"] and not finished["extras"]

# If the operator removes two notes, only current-batch selection changes.
remaining = set(list(sorted(selected))[:15])
state.nf_selected_flow_keys = remaining
smaller = active()
assert len(smaller) == 15
assert len(state.pre_notes) == 17  # source is untouched
assert audit(smaller, processed[processed.numero_nf.isin(
    smaller.numero_nf
)])["vinculadas"] == 15

# Changing the batch resets stale documents, and reopening the same batch
# preserves its current, already validated XMLs.
state.analysis = processed.copy()
state.document_upload_cache = [{"name": "previous.xml", "raw": b"sample"}]
state.nf_stage2_batch_keys = selected
state.nf_selected_flow_keys = selected
assert enter(selected)
assert len(state.analysis) == 17
assert len(state.document_upload_cache) == 1
state.nf_stage2_batch_keys = set()
assert enter(remaining)
assert state.analysis.empty and state.document_upload_cache == []
assert len(active()) == 15

assert '"SALVAR SELEÇÃO E CONTINUAR"' in source
assert '"VALIDAR BASE E CONTINUAR"' not in source
assert 'st.session_state.nf_stage2_batch_snapshot = snapshot.reset_index(drop=True)' in source
assert 'base=st.session_state.get("pre_notes")' in source
print("NFS_STAGE3_BATCH_SNAPSHOT_OK")
