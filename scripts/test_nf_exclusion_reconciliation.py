"""Testes determinísticos: exclusão fica enquanto houver pré-nota não lançada."""
from pathlib import Path
import pandas as pd
from nf_exclusion_reconciliation import excluded_nfs_with_confirmed_launch

def number(value):
    digits = "".join(c for c in str(value or "") if c.isdigit())
    return digits.lstrip("0") or ("0" if digits else "")

def digits(value):
    return "".join(c for c in str(value or "") if c.isdigit())

def name(value):
    return " ".join(str(value or "").upper().split())

def supplier_code(value):
    return digits(value).lstrip("0") or ("0" if digits(value) else "")

def sim(a,b):
    return 100 if name(a)==name(b) else 0

def check(exclusions, pre, report, identities=None):
    return excluded_nfs_with_confirmed_launch(
        exclusions,pd.DataFrame(pre),pd.DataFrame(report),
        normalize_nf=number, normalize_name=name,
        supplier_similarity=sim,
        normalize_supplier_code=supplier_code,digits_only=digits,
        identities_by_nf=identities,
    )

ident="12345678000190"
source=[{"numero_nf":"000220355","cnpj":ident,"fornecedor":"FORNECEDOR A"},
        {"numero_nf":"220361","cnpj":"99999999000199","fornecedor":"FORNECEDOR B"}]
full=[{"numero_nf":"220355","fornecedor":"FORNECEDOR A",
       "fornecedor_codigo":"10","cnpj_resolvido":ident,"tes":"501"},
      {"numero_nf":"220361","fornecedor":"FORNECEDOR B",
       "fornecedor_codigo":"20","cnpj_resolvido":"99999999000199","tes":""}]
assert check({"220355","220361"},source,full)==["220355"]
assert check({"220355"},source,[])==[]
assert check({"220355"},[],full)==[]  # saída da pré-nota não confirma lançamento
assert check({"220355"},[],full,{"220355":[{"cnpj":ident,"fornecedor":"FORNECEDOR A"}]}) == ["220355"]
assert check({"220355"},[],[{**full[0],"tes":""}],
             {"220355":[{"cnpj":ident,"fornecedor":"FORNECEDOR A"}]}) == []
assert check({"220355"},[],full,{"220355":[{"cnpj":"77777777000177",
                                             "fornecedor":"OUTRO"}]}) == []
assert check({"220355"},source,[{**full[0],"tes":""}])==[]
assert check({"220355"},source,[{**full[0],"cnpj_resolvido":"99999999000199"}])==[]
assert check({"220355"},source,[{**full[0],"cnpj_resolvido":"",
                                  "fornecedor":"FORNECEDOR DIFERENTE"}])==[]
assert check({"220355"},source,[{**full[0],"tes":"0"}])==[]
assert check({"220355"},source,[full[0], {**full[0],"tes":""}])==[]
assert check({"220355"},source,[{**full[0],"fornecedor":"FORNECEDOR A LTDA",
                                  "cnpj_resolvido":""}])==[]
assert check({"220355"},[{"numero_nf":"220355","cnpj":"","fornecedor":""}],full)==[]
assert check({"220355"},source+[{"numero_nf":"220355","cnpj":"12312312000199",
                                 "fornecedor":"OUTRO FORNECEDOR"}],full)==[]
assert check({"220355","220361"},source,[full[0],{
    **full[1],"tes":"700"}])==["220355","220361"]
# Em todos os casos, apenas uma lista de números é retornada. Nunca se grava
# no banco, nem a função decide a partir de ausência no relatório.
app=Path("streamlit_app.py").read_text("utf-8")
assert 'unfiltered_source_pre_notes = pre_valid.copy()' in app
assert 'not source.get("tes_unavailable")' in app
assert 'report["cnpj_resolvido"], _ = _supplier_cnpj_lookup(report)' in app
assert 'result = _restore_excluded_nfs(confirmed)' in app
assert 'if check_pre is None:' in app
assert 'central_data.download_preferred_source(' in app
assert app.index('persisted = persist_mrp_current()') < app.index(
    '_reconcile_excluded_after_launch(', app.index('def _sync_central_nfs_sources'))
migration=Path("supabase/migrations/20261015_nf_exclusao_identidade.sql").read_text("utf-8")
assert "add column if not exists identidades jsonb" in migration
assert "nf_capturar_identidade_desconsiderada" in migration
assert "before insert or update of ativo" in migration
assert 'identities_by_nf=known_identities' in app
assert 'check_pre = pd.DataFrame()' in app
print("NFS_EXCLUSION_RECONCILIATION_OK")
