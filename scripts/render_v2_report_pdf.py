#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/render_v2_report_pdf.py
===============================
Converte `docs/v2/report_v2_draft.md` em HTML academico limpo (com figuras SVG
embutidas inline e suporte a citacoes em bloco) e gera `docs/v2/report_v2.pdf`
via Chrome/Edge headless, sem dependencias Python externas.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.render_report_pdf import CSS, _inline_fmt

MD_PATH = ROOT / "docs" / "v2" / "report_v2_draft.md"
HTML_PATH = ROOT / "docs" / "v2" / "report_v2.html"
PDF_PATH = ROOT / "docs" / "v2" / "report_v2.pdf"

EXTRA_CSS = """
blockquote {
  margin: 6pt 0 7pt 0;
  padding: 5pt 9pt;
  background: #f8fafc;
  border-left: 3px solid #1b5e20;
  color: #1e293b;
}
blockquote p { margin: 0; }
a { color: #1d4ed8; text-decoration: none; }
figure.fig svg { width: 96%; max-width: 96%; }
"""


def _inline_v2(text: str) -> str:
    s = _inline_fmt(text)
    # Link bare https:// URLs (e.g. DOIs in References)
    s = re.sub(
        r"(?<!href=')(https?://[^\s<>]+)",
        r"<a href='\1'>\1</a>",
        s,
    )
    return s


def md_to_html_v2(md_text: str, base_dir: Path) -> str:
    lines = md_text.splitlines()
    out: list[str] = []
    i = 0
    in_ul = False
    in_ol = False

    def close_lists() -> None:
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

        # Blockquote
        if stripped.startswith("> "):
            close_lists()
            bq_lines = []
            while i < len(lines) and lines[i].strip().startswith("> "):
                bq_lines.append(lines[i].strip()[2:])
                i += 1
            out.append(f"<blockquote><p>{_inline_v2(' '.join(bq_lines))}</p></blockquote>")
            continue

        # Image / SVG embed
        m_img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if m_img:
            close_lists()
            cap, rel = m_img.group(1), m_img.group(2)
            img_path = (base_dir / rel).resolve()
            if img_path.suffix.lower() == ".svg" and img_path.is_file():
                out.append(
                    f"<figure class='fig'>{img_path.read_text(encoding='utf-8')}"
                    f"<figcaption>{_inline_v2(cap)}</figcaption></figure>"
                )
            i += 1
            continue

        # Headings
        m_h = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if m_h:
            close_lists()
            lvl = len(m_h.group(1))
            out.append(f"<h{lvl}>{_inline_v2(m_h.group(2))}</h{lvl}>")
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
            out.append(
                "<table><thead><tr>"
                + "".join(f"<th>{_inline_v2(h)}</th>" for h in headers)
                + "</tr></thead><tbody>"
            )
            for row in body_rows:
                # Pad short rows safely
                while len(row) < len(headers):
                    row.append("")
                out.append("<tr>" + "".join(f"<td>{_inline_v2(c)}</td>" for c in row[: len(headers)]) + "</tr>")
            out.append("</tbody></table>")
            continue

        # Nested or top-level bullet list
        if stripped.startswith("- ") or stripped.startswith("* "):
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline_v2(stripped[2:])}</li>")
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
            item_parts = [_inline_v2(m_ol.group(2))]
            i += 1
            # Capture indented sub-bullets inside numbered list
            sub_items = []
            while i < len(lines) and lines[i].startswith("   - "):
                sub_items.append(f"<li>{_inline_v2(lines[i].strip()[2:])}</li>")
                i += 1
            if sub_items:
                item_parts.append("<ul>" + "".join(sub_items) + "</ul>")
            out.append(f"<li>{''.join(item_parts)}</li>")
            continue

        # Paragraph
        close_lists()
        para_raw = [ln]
        i += 1
        while (
            i < len(lines)
            and lines[i].strip()
            and not lines[i].strip().startswith(("#", "|", "* ", "- ", "---", "![", "> "))
            and not re.match(r"^\d+\.\s+", lines[i].strip())
        ):
            para_raw.append(lines[i])
            i += 1
        parts_p = []
        for idx_p, raw_ln in enumerate(para_raw):
            fmt_ln = _inline_v2(raw_ln.strip())
            if idx_p < len(para_raw) - 1 and raw_ln.endswith("  "):
                parts_p.append(fmt_ln + "<br/>")
            elif idx_p < len(para_raw) - 1:
                parts_p.append(fmt_ln + " ")
            else:
                parts_p.append(fmt_ln)
        out.append(f"<p>{''.join(parts_p)}</p>")

    close_lists()
    return "\n".join(out)


def main() -> int:
    body = md_to_html_v2(MD_PATH.read_text(encoding="utf-8"), MD_PATH.parent)
    doc = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'/>"
        "<title>vitirule v2: How reliable are disease-warning alerts driven by free weather data?</title>"
        f"<style>{CSS}{EXTRA_CSS}</style></head><body>{body}</body></html>"
    )
    HTML_PATH.write_text(doc, encoding="utf-8")

    browser = next(
        (
            p
            for p in (
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                shutil.which("google-chrome") or "",
                shutil.which("chromium") or "",
                shutil.which("msedge") or "",
            )
            if p and Path(p).is_file()
        ),
        None,
    )
    if not browser:
        print("HTML gerado, mas Chrome/Edge nao encontrado:", HTML_PATH)
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
    HTML_PATH.unlink(missing_ok=True)
    print(f"PDF v2 gerado com sucesso: {PDF_PATH} ({PDF_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
