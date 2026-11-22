#!/usr/bin/env python3
"""
scripts/v2_build_pyodide_bundle.py
==================================
Empacota os modulos puros congelados de `vitirule_v2/rules/` e `vitirule_v2/lwd.py`
em `docs/app/vitirule_bundle.json` para execucao direta no navegador via Pyodide,
garantindo identidade byte-a-byte com o pacote congelado em `v2-freeze`.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BUNDLE_FILES = (
    "vitirule_v2/lwd.py",
    "vitirule_v2/rules/__init__.py",
    "vitirule_v2/rules/common.py",
    "vitirule_v2/rules/phenology.py",
    "vitirule_v2/rules/downy_mildew.py",
    "vitirule_v2/rules/apple_scab.py",
    "vitirule_v2/rules/tomcast.py",
    "vitirule_v2/rules/params.json",
)


def build_bundle(out_path: Path | None = None) -> dict[str, str]:
    files: dict[str, str] = {
        "vitirule_v2/__init__.py": '"""vitirule_v2 pure-Python subset loaded in Pyodide."""\n',
    }
    for rel in BUNDLE_FILES:
        src = ROOT / rel
        files[rel] = src.read_text(encoding="utf-8")
    target = out_path or (ROOT / "docs" / "app" / "vitirule_bundle.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(files, ensure_ascii=False, indent=2), encoding="utf-8")
    return files


if __name__ == "__main__":
    data = build_bundle()
    print(f"Built docs/app/vitirule_bundle.json with {len(data)} files.")
