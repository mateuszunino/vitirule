#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/render_report_pdf.py
============================
Converte `docs/technical_report.md` em HTML acadêmico limpo (com figuras SVG
embutidas inline) e gera `docs/technical_report.pdf` via Chrome/Edge headless,
sem adicionar nenhuma dependência Python externa.
"""
from __future__ import annotations

import html
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD_PATH = ROOT / "docs" / "technical_report.md"
HTML_PATH = ROOT / "docs" / "technical_report.html"
PDF_PATH = ROOT / "docs" / "technical_report.pdf"


def _inline_fmt(text: str) -> str:
    # Preserva fórmulas simples em itálico/code e aplica bold/italic/code
    s = html.escape(text)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"<a href='\2'>\1</a>", s)
    # Converte notação LaTeX inline simples ($...$) para texto tipográfico limpo
    def _math_sub(m: re.Match) -> str:
        expr = m.group(1)
        reps = [
            (r"\Delta", "Δ"), (r"\tau", "τ"), (r"\beta", "β"), (r"\phi", "φ"),
            (r"\mathcal{N}", "N"), (r"\ge", "≥"), (r"\le", "≤"), (r"\sim", "~"),
            (r"\dots", "…"), (r"\to", "→"), (r"\cdot", "·"), (r"\times", "×"),
            (r"\in", "∈"), (r"\mid", "|"), (r"\max", "max"), (r"\min", "min"),
            (r"\text{", ""), (r"\,", " "), (r"\;", " "), (r"^\circ", "°"),
        ]
        for a, b in reps:
            expr = expr.replace(a, b)
        # Brace-grouped sub/superscripts first
        expr = re.sub(r"_\{([^}]+)\}", r"<sub>\1</sub>", expr)
        expr = re.sub(r"\^\{([^}]+)\}", r"<sup>\1</sup>", expr)
        # Single-token sub/superscripts
        expr = re.sub(r"_([A-Za-z0-9,]+)", r"<sub>\1</sub>", expr)
        expr = re.sub(r"\^([A-Za-z0-9.-]+)", r"<sup>\1</sup>", expr)
        expr = expr.replace("{", "").replace("}", "").replace("\\", "")
        return f"<span class='math'>{expr}</span>"
    s = re.sub(r"\$([^$]+)\$", _math_sub, s)
    return s


def md_to_html(md_text: str, base_dir: Path) -> str:
    lines = md_text.splitlines()
    out: list[str] = []
    i = 0
    in_ul = False
    in_ol = False

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    while i < len(lines):
        ln = lines[i]
        stripped = ln.strip()

        if not stripped:
            close_lists()
            i += 1
            continue

        if stripped == "---":
            close_lists()
            out.append("<hr/>")
            i += 1
            continue

        # Display math $$...$$
        if stripped.startswith("$$") and stripped.endswith("$$"):
            close_lists()
            expr = stripped[2:-2].strip()
            expr = expr.replace(r"\left(", "(").replace(r"\right)", ")")
            expr = expr.replace(r"\qquad", "&emsp;&emsp;").replace(r"\cdot", "·")
            expr = expr.replace(r"\text{AUDPC}", "AUDPC").replace(r"\text{Net Return (€/ha)}", "Net Return (€/ha)")
            expr = expr.replace(r"_{\max}", "<sub>max</sub>").replace(r"_{\text{sprays}}", "<sub>sprays</sub>").replace(r"_{\text{spray}}", "<sub>spray</sub>")
            expr = expr.replace(r"^{-k · AUDPC}", "<sup>−k · AUDPC</sup>")
            out.append(f"<div class='eq'>{expr}</div>")
            i += 1
            continue

        # Image / SVG embed: ![caption](rel_path) — agrupa 2 figuras consecutivas lado a lado
        m_img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if m_img:
            close_lists()
            imgs = []
            while i < len(lines):
                s_cur = lines[i].strip()
                if not s_cur:
                    i += 1
                    continue
                m2 = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", s_cur)
                if not m2:
                    break
                imgs.append((m2.group(1), m2.group(2)))
                i += 1
            # Optional shared caption line immediately following: *Figure N. ...*
            shared_cap = None
            if i < len(lines) and re.match(r"^\*\*Figure\s+\d+\.?\*\*", lines[i].strip()):
                shared_cap = lines[i].strip()
                i += 1
            if len(imgs) == 2:
                parts = []
                for cap, rel in imgs:
                    img_path = (base_dir / rel).resolve()
                    if img_path.suffix.lower() == ".svg" and img_path.is_file():
                        subcap = f"<div class='subcap'>{_inline_fmt(cap)}</div>" if (cap and not shared_cap) else ""
                        parts.append(f"<div class='fig-half'>{img_path.read_text(encoding='utf-8')}{subcap}</div>")
                cap_html = f"<figcaption>{_inline_fmt(shared_cap)}</figcaption>" if shared_cap else ""
                out.append("<figure class='fig-group'><div class='fig-row'>" + "".join(parts) + "</div>" + cap_html + "</figure>")
            else:
                for cap, rel in imgs:
                    img_path = (base_dir / rel).resolve()
                    if img_path.suffix.lower() == ".svg" and img_path.is_file():
                        cls = "fig fig-tall" if "timeline" in img_path.name else "fig"
                        cap_text = shared_cap if shared_cap else cap
                        out.append(f"<figure class='{cls}'>{img_path.read_text(encoding='utf-8')}<figcaption>{_inline_fmt(cap_text)}</figcaption></figure>")
            continue

        # Headings
        m_h = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if m_h:
            close_lists()
            lvl = len(m_h.group(1))
            out.append(f"<h{lvl}>{_inline_fmt(m_h.group(2))}</h{lvl}>")
            i += 1
            continue

        # Tables
        if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|---"):
            close_lists()
            headers = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            body_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body_rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline_fmt(h)}</th>" for h in headers) + "</tr></thead><tbody>")
            for row in body_rows:
                out.append("<tr>" + "".join(f"<td>{_inline_fmt(c)}</td>" for c in row) + "</tr>")
            out.append("</tbody></table>")
            continue

        # Unordered list
        if stripped.startswith("* ") or stripped.startswith("- "):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline_fmt(stripped[2:])}</li>")
            i += 1
            continue

        # Ordered list
        m_ol = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if m_ol:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline_fmt(m_ol.group(2))}</li>")
            i += 1
            continue

        # Paragraph (preserving explicit trailing two-space Markdown line breaks)
        close_lists()
        para_raw = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(("#", "|", "* ", "- ", "---", "![", "$$")) and not re.match(r"^\d+\.\s+", lines[i].strip()):
            para_raw.append(lines[i])
            i += 1
        parts_p = []
        for idx_p, raw_ln in enumerate(para_raw):
            fmt_ln = _inline_fmt(raw_ln.strip())
            if idx_p < len(para_raw) - 1 and raw_ln.endswith("  "):
                parts_p.append(fmt_ln + "<br/>")
            elif idx_p < len(para_raw) - 1:
                parts_p.append(fmt_ln + " ")
            else:
                parts_p.append(fmt_ln)
        out.append(f"<p>{''.join(parts_p)}</p>")

    close_lists()
    return "\n".join(out)


CSS = """
@page {
  size: A4;
  margin: 13mm 13mm 15mm 13mm;
  @bottom-center {
    content: counter(page) " / " counter(pages);
    font-family: Georgia, serif;
    font-size: 8.5pt;
    color: #4b5563;
  }
}
body {
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 9.0pt;
  line-height: 1.38;
  color: #111827;
  max-width: 100%;
}
h1 {
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: 15.5pt;
  line-height: 1.22;
  color: #0f172a;
  margin-top: 0;
  margin-bottom: 8pt;
  border-bottom: 2px solid #0f172a;
  padding-bottom: 5pt;
}
h2 {
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: 11.5pt;
  color: #0f172a;
  margin-top: 12pt;
  margin-bottom: 5pt;
  border-bottom: 1px solid #d1d5db;
  padding-bottom: 2pt;
  page-break-after: avoid;
}
h3 {
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: 10pt;
  color: #1e293b;
  margin-top: 9pt;
  margin-bottom: 3pt;
  page-break-after: avoid;
}
p { margin: 0 0 5.5pt 0; text-align: justify; }
ul, ol { margin: 3pt 0 6pt 0; padding-left: 16pt; }
li { margin-bottom: 2pt; }
code {
  font-family: "Consolas", "Courier New", monospace;
  font-size: 8pt;
  background: #f3f4f6;
  padding: 1px 2.5px;
  border-radius: 2px;
}
.math { font-style: italic; }
.eq {
  text-align: center;
  font-style: italic;
  margin: 6pt 0 7pt 0;
  padding: 5pt 8pt;
  background: #f9fafb;
  border-left: 3px solid #374151;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 6pt 0 8pt 0;
  font-size: 7.6pt;
  line-height: 1.24;
}
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
th, td {
  border: 1px solid #cbd5e1;
  padding: 2.8pt 4pt;
  text-align: left;
  vertical-align: top;
}
th {
  background: #f1f5f9;
  font-family: "Segoe UI", Arial, sans-serif;
  font-weight: 600;
  color: #0f172a;
}
tr:nth-child(even) td { background: #fafafa; }
figure.fig {
  margin: 7pt 0 9pt 0;
  text-align: center;
  page-break-inside: avoid;
}
figure.fig svg {
  width: 92%;
  max-width: 92%;
  height: auto;
  border: 1px solid #e5e7eb;
}
figure.fig-tall svg {
  width: 98%;
  max-width: 98%;
  height: auto;
  border: 1px solid #e5e7eb;
}
figure.fig-group {
  margin: 7pt 0 9pt 0;
  page-break-inside: avoid;
}
.fig-row {
  display: flex;
  gap: 8pt;
  justify-content: space-between;
}
.fig-half {
  flex: 1;
  margin: 0;
  text-align: center;
}
.fig-half svg {
  width: 100%;
  height: auto;
  border: 1px solid #e5e7eb;
}
figcaption {
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: 7.9pt;
  line-height: 1.32;
  color: #374151;
  margin-top: 4pt;
  text-align: justify;
}
.blank-box {
  border: 1px dashed #9ca3af;
  background: #f9fafb;
  padding: 10pt 12pt;
  color: #6b7280;
  font-style: italic;
  margin: 4pt 0 8pt 0;
}
hr { border: none; border-top: 1px solid #e5e7eb; margin: 7pt 0; }
"""


def main() -> int:
    body = md_to_html(MD_PATH.read_text(encoding="utf-8"), MD_PATH.parent)
    doc = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'/>"
        "<title>vitirule: Technical Report on Grapevine Downy Mildew Spray Rules</title>"
        f"<style>{CSS}</style></head><body>{body}</body></html>"
    )
    HTML_PATH.write_text(doc, encoding="utf-8")

    import shutil

    browser = next(
        (p for p in (
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            shutil.which("google-chrome") or "",
            shutil.which("chromium") or "",
            shutil.which("chromium-browser") or "",
        ) if p and Path(p).is_file()),
        None,
    )
    if not browser:
        print("HTML gerado, mas Chrome/Edge não encontrado para PDF:", HTML_PATH)
        return 1

    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={PDF_PATH}",
        HTML_PATH.resolve().as_uri(),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not PDF_PATH.is_file():
        print("Falha ao renderizar PDF:", proc.stderr)
        return 2
    print(f"PDF gerado com sucesso: {PDF_PATH} ({PDF_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
