"""
Testes automatizados dos entregaveis da Fase 5:
- Identidade byte-a-byte entre `docs/app/vitirule_bundle.json` (Pyodide) e
  os arquivos puros congelados em `vitirule_v2/rules/` e `vitirule_v2/lwd.py`
- Separacao estrita de dados publicos no CI (`--public-only`, zero Politecnico)
- Nota obrigatoria `CC BY-NC 4.0` em figuras com derivados do Politecnico
- Aviso explicito contra uso de dados em grade como recomendacao na pagina web
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.v2_build_pyodide_bundle import BUNDLE_FILES

ROOT = Path(__file__).resolve().parents[1]


def test_pyodide_bundle_matches_frozen_rules_byte_for_byte():
    bundle_path = ROOT / "docs" / "app" / "vitirule_bundle.json"
    assert bundle_path.is_file(), "vitirule_bundle.json ausente"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    for rel in BUNDLE_FILES:
        expected = (ROOT / rel).read_text(encoding="utf-8")
        assert rel in bundle, f"{rel} ausente no bundle Pyodide"
        assert bundle[rel] == expected, f"Divergencia entre {rel} e vitirule_bundle.json"


def test_browser_app_has_pyodide_and_grid_non_recommendation_warning():
    html = (ROOT / "docs" / "app" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "docs" / "app" / "app.js").read_text(encoding="utf-8")
    assert "pyodide.js" in html
    assert "Demonstração de divergência" in html
    assert "NÃO é recomendação" in html or "não é recomendação" in html
    assert "Tabela de confiabilidade medida" in html
    assert "Não passou no exploratório" in html
    assert "Não usável" not in html
    assert "Na tabela de Mills, uma estação local com termômetro, higrômetro e pluviômetro passou no critério exploratório" in html
    assert "vitirule_bundle.json" in js
    assert 'loadPackage("tzdata")' in js
    assert "run_station_csv_json" in js
    assert (ROOT / "tests" / "test_pyodide_app.mjs").is_file()


def test_figures_license_attribution_and_public_ci_isolation():
    fig_dir = ROOT / "docs" / "v2" / "figures"
    for svg_p in sorted(fig_dir.glob("*.svg")):
        txt = svg_p.read_text(encoding="utf-8")
        assert "—" not in txt, f"Travessao encontrado em {svg_p.name}"

    fig1 = fig_dir / "fig1_europe_exploratory_miss_far.svg"
    if fig1.is_file():
        txt1 = fig1.read_text(encoding="utf-8")
        assert "False alarm ratio, FAR (%)" in txt1
        assert "Station without LWD sensor not shown: input identical to reference." in txt1
        assert "F1=1.00" not in txt1

    fig2 = fig_dir / "fig2_europe_cost_loss_and_tomcast.svg"
    if fig2.is_file():
        txt2 = fig2.read_text(encoding="utf-8")
        assert "CC BY-NC 4.0" in txt2
        assert "10.17632/sd4b8vpvyb.1" in txt2
        assert "Station without LWD sensor not shown for 3-10 and Goidànich: input identical to reference." in txt2

    fig4 = fig_dir / "fig4_santa_catarina_transfer.svg"
    if fig4.is_file():
        txt4 = fig4.read_text(encoding="utf-8")
        assert "<polyline" not in txt4, "fig4 painel B nao deve ligar estacoes independentes com linhas"
        assert "São Joaquim" in txt4
        assert "Chapecó" in txt4
        assert "Caçador" in txt4

    # Arquivos publicos (fig4 + tabelas SC) nao podem conter referencias ao Politecnico
    public_files = [
        fig4,
        ROOT / "docs" / "v2" / "tables" / "table_sc_24_stations_selection.csv",
        ROOT / "docs" / "v2" / "tables" / "table_sc_results_summary.csv",
    ]
    for pf in public_files:
        if pf.is_file():
            low = pf.read_text(encoding="utf-8").lower()
            assert "politecnico" not in low
            assert "polito" not in low
            assert "sd4b8vpvyb" not in low


def test_github_actions_workflow_is_dispatch_only_and_public_only():
    wf = (ROOT / ".github" / "workflows" / "v2_reproduce.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in wf
    assert "--public-only" in wf
    assert "actions/upload-artifact@v4" in wf
    assert "politecnico" in wf.lower()  # guarda explicita contra vazamento
