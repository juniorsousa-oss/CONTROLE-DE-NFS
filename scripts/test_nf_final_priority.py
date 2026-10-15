"""Regressão das prioridades manuais na confirmação final (sem banco)."""
import pandas as pd
from pathlib import Path
from nf_final_priority import apply_final_manual_priorities

base = pd.DataFrame([
    dict(file_id="f1",numero_nf="123",prioridade_mrp_base=True,
         prioridade_mrp=True,prioridade_manual=False),
    dict(file_id="f2",numero_nf="123",prioridade_mrp_base=False,
         prioridade_mrp=False,prioridade_manual=False),
    dict(file_id="f3",numero_nf="456",prioridade_mrp_base=False,
         prioridade_mrp=False,prioridade_manual=True),
])
edited = base[["file_id","prioridade_manual"]].iloc[[2,0,1]].copy()
edited.loc[edited.file_id.eq("f2"),"prioridade_manual"] = True
edited.loc[edited.file_id.eq("f3"),"prioridade_manual"] = False
result = apply_final_manual_priorities(base, edited)
assert result.file_id.tolist() == ["f1","f2","f3"]
assert result.prioridade_mrp.tolist() == [True,True,False]
assert result.prioridade_mrp_base.tolist() == [True,False,False]
assert result.prioridade_manual.tolist() == [False,True,False]
assert base.prioridade_manual.tolist() == [False,False,True]
try:
    apply_final_manual_priorities(base, edited.iloc[:2])
except ValueError: pass
else: raise AssertionError("Inconsistência de seleção não pode ser aceita")
app = Path("streamlit_app.py").read_text("utf-8")
assert 'st.form("stage3_final_priority_form")' in app
assert 'apply_final_manual_priorities(' in app
assert app.index('st.form("stage3_final_priority_form")') < app.index('key="stage3_generate_ready_files"')
assert 'if bool(row.get("prioridade_mrp"))' in app
print("NF_STAGE3_FINAL_PRIORITY_OK")
