"""Regressão 96 -> 97 com NF estável, sem gravação/HTTP real."""
from __future__ import annotations

import ast
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import Mock

import pandas as pd


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


tree = ast.parse(Path("streamlit_app.py").read_text(encoding="utf-8"))
names = {
    "_join_unique", "_clean_mrp_materials_api_snapshot", "_materials_load_id",
    "refresh_mrp_from_materials_api", "_sync_materials_mrp", "_sync_central_nfs_on_page_load",
}
functions = ast.Module(
    body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names],
    type_ignores=[],
)
code = compile(functions, "streamlit_app.py", "exec")


class MaterialsAutoSyncTests(TestCase):
    def setUp(self):
        self.state = State(
            mrp_priority_stats={"carga_materiais_id": 96},
            mrp_priority_files=("carga 96", "stsup01.xlsx"),
            mrp_impact_detail=pd.DataFrame([
                {"numero_nf":"100", "produto":"001", "data_pre_nota":date(2026, 11, 27)}
            ]),
        )
        self.payload = {
            "disponivel":True, "carga":{"carga_id":97,"total_itens":2},
            "itens":[
                {"produto":"001","projeto":"01","data_cm":"2026-12-01"},
                {"produto":"002","projeto":"02","data_cm":"2026-11-28"},
            ],
        }
        self.save = Mock(return_value={"ok":True})
        self.load = Mock(return_value=self.payload)
        self.status = Mock(return_value={"disponivel":True,"carga_id":97})
        self.refresh_missing = Mock()
        self.normal_sync = Mock(return_value={"changed":False,"errors":[]})
        self.filter_nfs = Mock(side_effect=lambda frame: frame[frame["numero_nf"]!="900"].copy())
        self.clean_cache = Mock()
        self.namespace = {
            "pd":pd,
            "db": SimpleNamespace(configured=lambda:True, save_mrp_load=self.save),
            "st":SimpleNamespace(session_state=self.state,spinner=lambda _: __import__("contextlib").nullcontext()),
            "SAVE_NF_HISTORY":True,
            "_cached_materials_api_status":self.status,
            "_load_materials_api_current_cached":self.load,
            "_invalidate_mrp_cache":Mock(),
            "_invalidate_pre_notes_cache":Mock(),
            "_invalidate_materials_status_cache":Mock(),
            "_ensure_operational_reference_data":Mock(),
            "_sync_central_nfs_sources":self.normal_sync,
            "_refresh_missing_mrp_analysis":self.refresh_missing,
            "_filter_excluded_nfs":self.filter_nfs,
            "_build_mrp_impact":self.impact,
            "dataframe_records_for_db":lambda f:f.to_dict("records"),
            "now_local":lambda:datetime(2026,11,27,13,26),
            "normalized_material_code":str,
        }
        exec(code,self.namespace)
        self.refresh=self.namespace["refresh_mrp_from_materials_api"]
        self.page=self.namespace["_sync_central_nfs_on_page_load"]

    def impact(self, materials, entries):
        self.material_dates=materials["data_cm"].tolist()
        self.assertEqual(len(entries),1)
        frame=pd.DataFrame([
            {"numero_nf":"100","prioridade":"ALTA","data_nf":"2026-11-27|100"},
            {"numero_nf":"900","prioridade":"ALTA","data_nf":"2026-11-27|900"},
        ])
        return frame,frame.copy(),{"fake":True}

    def test_new_materials_reprocesses_even_if_nf_did_not_change_and_only_once(self):
        result=self.page()
        self.normal_sync.assert_called_once_with(force=False)
        self.assertTrue(result["materials"]["recalculado"])
        self.assertEqual(self.state.mrp_priority_stats["carga_materiais_id"],97)
        self.assertEqual(self.state.mrp_priority_files[1],"stsup01.xlsx")
        self.assertEqual(self.state.priority_nf_numbers,{"100"})
        self.assertEqual(self.state.mrp_impact_detail["numero_nf"].tolist(),["100"])
        self.assertEqual(self.material_dates,[date(2026,12,1),date(2026,11,28)])
        self.save.assert_called_once()
        self.refresh_missing.assert_called_once()
        self.assertEqual(self.page(),{"checked":False})
        self.normal_sync.assert_called_once()

    def test_same_id_is_noop_and_older_id_is_rejected(self):
        self.state.mrp_priority_stats["carga_materiais_id"]=97
        self.assertFalse(self.refresh()["recalculado"])
        self.state.mrp_priority_stats["carga_materiais_id"]=98
        self.assertEqual(self.refresh()["motivo"],"CARGA_ANTERIOR")
        self.load.assert_not_called()
        self.save.assert_not_called()

    def test_mismatch_or_truncated_load_never_changes_the_analysis(self):
        self.payload["carga"]["carga_id"]=98
        self.assertEqual(self.refresh()["motivo"],"VERSAO_MUDOU")
        self.payload["carga"]["carga_id"]=97
        self.payload["itens"].pop()
        self.assertEqual(self.refresh()["motivo"],"CARGA_INCOMPLETA")
        self.assertEqual(self.state.mrp_priority_stats["carga_materiais_id"],96)
        self.save.assert_not_called()

    def test_confirmed_zero_item_source_is_a_valid_load(self):
        self.payload["carga"]["total_itens"]=0
        self.payload["itens"]=[]
        self.assertTrue(self.refresh()["ok"])
        self.assertEqual(self.material_dates,[])

    def test_bad_date_and_missing_stsup01_preserve_prior_state(self):
        self.payload["itens"][0]["data_cm"]="2026-13-31"
        self.assertEqual(self.refresh()["motivo"],"CARGA_INCOMPLETA")
        self.state.mrp_impact_detail=pd.DataFrame()
        self.assertEqual(self.refresh()["motivo"],"SEM_BASE_STSUP01")
        self.save.assert_not_called()

    def test_persistence_failure_does_not_claim_success(self):
        self.save.return_value={"ok":False}
        result=self.page()
        self.assertFalse(result["materials"]["ok"])
        self.assertEqual(self.state.mrp_priority_stats["carga_materiais_id"],96)
        self.assertIn("preservada",self.state["_central_materials_warning"])
        self.refresh_missing.assert_not_called()


if __name__=="__main__":
    main()
