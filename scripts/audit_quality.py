"""Auditoria estática do repositório sem remover código.

Funções sem referência estática são apenas candidatas a análise manual:
Streamlit e APIs também podem referenciá-las dinamicamente.
"""
from __future__ import annotations

import ast
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE = {".git", ".venv", "venv", "__pycache__", ".ci_reports"}
FILES = sorted(
    path for path in ROOT.rglob("*")
    if path.is_file()
    and not any(part in EXCLUDE for part in path.relative_to(ROOT).parts)
)
PY_FILES = [path for path in FILES if path.suffix == ".py"]
sources, definitions, references, parse_errors = {}, {}, Counter(), {}

for path in PY_FILES:
    rel = path.relative_to(ROOT).as_posix()
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=rel)
    except (UnicodeDecodeError, SyntaxError) as exc:
        parse_errors[rel] = str(exc)
        continue
    sources[rel] = content
    definitions[rel] = [
        (node.name, node.lineno)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            references[node.id] += 1
        elif isinstance(node, ast.Attribute):
            references[node.attr] += 1

duplicates, unreferenced = [], []
for rel, symbols in definitions.items():
    for name, count in Counter(name for name, _ in symbols).items():
        if count > 1:
            duplicates.append({"file": rel, "name": name, "count": count})
    if rel.startswith("scripts/"):
        continue
    for name, line in symbols:
        if references[name] == 0 and not name.startswith("__"):
            unreferenced.append({"file": rel, "line": line, "name": name})

app = sources.get("streamlit_app.py", "")
shell = sources.get("setta_shell.py", "")
files_by_size = sorted(
    [{"file": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size} for p in FILES],
    key=lambda item: item["bytes"],
    reverse=True,
)
hotspots = {
    "streamlit_app_lines": len(app.splitlines()),
    "full_page_reruns": app.count("st.rerun("),
    "dataframe_apply_calls": len(re.findall(r"\.apply\s*\(", app)),
    "mrp_reconciliation_invocations": app.count("_refresh_missing_mrp_analysis(") - 1,
    "cached_functions": app.count("@st.cache_data"),
    "shell_style_blocks": shell.count("<style>"),
    "component_style_blocks": app.count('<style id="nfs-component-style">'),
}
report = {
    "at": datetime.now(timezone.utc).isoformat(),
    "scope": "full_repository",
    "file_count": len(FILES),
    "python_files": len(PY_FILES),
    "largest_files": files_by_size[:12],
    "hotspots": hotspots,
    "same_file_duplicate_top_level_definitions": duplicates,
    "possible_unreferenced_public_symbols_manual_review_only": unreferenced,
    "syntax_errors": parse_errors,
    "interpretation": (
        "Candidatos sem referência NÃO são prova de código morto. "
        "Exigir análise de efeitos e testes antes de qualquer exclusão."
    ),
}
out = ROOT / ".ci_reports" / "maintenance_audit.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

summary = (
    "### Auditoria de qualidade — Controle de NFs\n\n"
    f"- Arquivos verificados: **{len(FILES)}** (Python: {len(PY_FILES)})\n"
    f"- Linhas do app principal: **{hotspots['streamlit_app_lines']}**\n"
    f"- Reinicializações explícitas: **{hotspots['full_page_reruns']}**\n"
    f"- Funções públicas candidatas a revisão manual: **{len(unreferenced)}**\n"
    f"- Duplicação de definições no mesmo arquivo: **{len(duplicates)}**\n"
    f"- Falhas de sintaxe: **{len(parse_errors)}**\n\n"
    "Detalhes no artefato maintenance-audit. Candidatos não são removidos automaticamente.\n"
)
print(summary)
print("AUDIT_QUALITY_REPORT:", out)
if os.environ.get("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary_file:
        summary_file.write(summary)
assert not parse_errors, parse_errors
assert not duplicates, duplicates
