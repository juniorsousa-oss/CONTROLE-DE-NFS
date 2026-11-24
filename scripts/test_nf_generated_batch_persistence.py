"""Regression: one CT-e can accompany multiple independent NF-e batches.

The database is mocked. No actual invoice is inserted or confirmed.
"""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import db
import pandas as pd


def nf(number, batch="NF-NEW"):
    return {
        "lote_id": batch,
        "tipo_documento": "NF-e",
        "numero_nf": str(number),
        "chave_nfe": str(number).zfill(44),
        "arquivo_final": f"NF-{number}.pdf",
        "empresa_sigla": "SEN",
        "status": "REALIZADO",
    }


def cte(batch="NF-NEW", status="REALIZADO", company="SEN"):
    return {
        "lote_id": batch,
        "tipo_documento": "CT-e",
        "numero_cte": "700",
        "chave_cte": "7" * 44,
        "arquivo_final": "CTE-700.pdf",
        "empresa_sigla": company,
        "status": status,
        "enviado_em": "2026-11-19T19:20:32+00:00" if status == "ENVIADO" else None,
    }


class FakeBank:
    def __init__(self, rows=()):
        self.rows = [dict(r, id=str(i + 1)) for i, r in enumerate(rows)]
        self.calls = 0
        self.fail = None

    def lookup(self, manifest):
        fields = ("chave_nfe", "chave_cte")
        keys = {(f, r[f]) for f in fields for r in manifest if r.get(f)}
        return {(f, r[f]): dict(r) for f in fields for r in self.rows
                if r.get(f) and (f, r[f]) in keys}

    def batch(self, batch):
        return [dict(r) for r in self.rows if r["lote_id"] == batch]

    def save(self, rows):
        self.calls += 1
        if self.fail:
            raise RuntimeError(self.fail)
        for row in rows:
            assert not self.lookup([row]), "Duplicate fiscal key in INSERT"
            self.rows.append(dict(row, id=str(len(self.rows) + 1)))
        return {"inseridos": len(rows)}

    def persist(self, manifest):
        with patch.object(db, "configured", return_value=True), \
             patch.object(db, "_existing_fiscal_records", side_effect=self.lookup), \
             patch.object(db, "list_process_batch", side_effect=self.batch), \
             patch.object(db, "save_process_records", side_effect=self.save):
            return db.persist_generated_batch(manifest)


class BatchTests(unittest.TestCase):
    def test_sent_cte_does_not_abort_new_nfs(self):
        bank = FakeBank([cte("NF-OLD", "ENVIADO")])
        result = bank.persist([nf(101), nf(102), cte()])
        self.assertEqual(result["inseridos"], 2)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["reused"][0]["status"], "ENVIADO")
        self.assertEqual(bank.rows[0]["lote_id"], "NF-OLD")
        self.assertEqual(bank.rows[0]["enviado_em"], "2026-11-19T19:20:32+00:00")
        self.assertEqual(len(bank.rows), 3)
        self.assertEqual(len(bank.batch("NF-NEW")), 2)
        self.assertTrue(all(r["status"] == "REALIZADO" for r in bank.batch("NF-NEW")))

    def test_pending_cte_remains_in_original_batch(self):
        bank = FakeBank([cte("NF-OLD")])
        result = bank.persist([nf(101), cte()])
        self.assertEqual(result["reused"][0]["lote_id"], "NF-OLD")
        self.assertEqual(bank.batch("NF-OLD")[0]["status"], "REALIZADO")
        self.assertEqual(result["inseridos"], 1)

    def test_reopening_same_batch_does_not_insert_again(self):
        bank = FakeBank()
        manifest = [nf(101), cte()]
        first = bank.persist(manifest)
        second = bank.persist(manifest)
        self.assertEqual(first["records"], second["records"])
        self.assertEqual(bank.calls, 1)
        self.assertEqual(len(bank.rows), 2)

    def test_duplicate_nf_is_not_silently_dropped(self):
        bank = FakeBank([nf(101, "NF-OLD")])
        with self.assertRaisesRegex(RuntimeError, "já registrada"):
            bank.persist([nf(101), nf(102)])
        self.assertEqual(bank.calls, 0)

    def test_conflicting_company_does_not_release_batch(self):
        bank = FakeBank([cte("NF-OLD", company="SEE")])
        with self.assertRaisesRegex(RuntimeError, "outra empresa"):
            bank.persist([nf(101), cte()])
        self.assertEqual(bank.calls, 0)

    def test_actual_database_failure_is_not_success(self):
        bank = FakeBank()
        bank.fail = "Supabase HTTP 503"
        with self.assertRaisesRegex(RuntimeError, "503"):
            bank.persist([nf(101), cte()])
        self.assertEqual(bank.batch("NF-NEW"), [])

    def test_cte_registered_concurrently(self):
        bank = FakeBank()
        original = bank.save
        def race(rows):
            if not bank.rows:
                bank.rows.append(dict(cte("NF-OTHER", "ENVIADO"), id="existing"))
                raise RuntimeError("Supabase HTTP 409: duplicate key")
            return original(rows)
        bank.save = race
        result = bank.persist([nf(101), cte()])
        self.assertEqual(result["inseridos"], 1)
        self.assertEqual(result["reused"][0]["lote_id"], "NF-OTHER")


class State(dict):
    def __getattr__(self, key):
        return self[key]
    def __setattr__(self, key, value):
        self[key] = value


class UiTests(unittest.TestCase):
    def setUp(self):
        self.source = Path("streamlit_app.py").read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def function(self, name):
        return next(n for n in self.tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == name)

    def test_no_download_when_database_write_fails(self):
        state = State(history=[], zip_outputs={}, last_generation_audit={"lote_id": "NF-NEW"})
        def fail(manifest):
            raise RuntimeError("Supabase HTTP 409")
        scope = {"st": SimpleNamespace(session_state=state), "SAVE_NF_HISTORY": True,
                 "db": SimpleNamespace(persist_generated_batch=fail),
                 "_invalidate_process_cache": lambda: None}
        exec(compile(ast.Module(body=[self.function("_persist_and_release_nf_zip")],
                                type_ignores=[]), "<test>", "exec"), scope)
        with self.assertRaisesRegex(RuntimeError, "409"):
            scope["_persist_and_release_nf_zip"]({"zip": b"pdf"}, [nf(101)])
        self.assertEqual(state.zip_outputs, {})
        self.assertEqual(state.history, [])
        self.assertFalse(state.last_generation_audit.get("lote_persistido"))

    def test_persisted_batch_skips_generation_validations(self):
        ready = ast.get_source_segment(self.source, self.function("render_ready_file_stage"))
        self.assertLess(ready.index("_render_persisted_nf_zip()"), ready.index("recalc("))
        self.assertIn("_persist_and_release_nf_zip(outputs, manifest)", ready)
        persisted = ast.get_source_segment(self.source, self.function("_render_persisted_nf_zip"))
        self.assertIn("db.list_process_batch(batch_id)", persisted)
        self.assertIn("render_send_and_tracking_stage(awaiting)", persisted)
        self.assertIn("AGUARDANDO DECISÃO", persisted)
        self.assertIn("render_send_and_tracking_stage(awaiting_remote)", ready)


if __name__ == "__main__":
    unittest.main()
