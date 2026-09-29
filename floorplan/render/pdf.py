"""PDF via headless Chrome, PNG via pdftoppm."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from .layout import Sheet


class RenderError(RuntimeError):
    """Chrome or poppler failed, or the PDF is not one page."""


def _wrapper(sheet: Sheet, svg_text: str) -> str:
    w, h = sheet.size_mm
    if sheet.sheet_level == "sketch":
        page = f"{w:.2f}mm {h:.2f}mm"
    else:
        page = "17in 11in"
    css = (f"@page{{size:{page};margin:0}} html,body{{margin:0;padding:0;overflow:hidden;background:#fff}} "
           f"svg{{display:block;width:{w:.2f}mm;height:{h:.2f}mm}}")
    return f'<!doctype html><html><head><meta charset="utf-8"><title>{sheet.title}</title><style>{css}</style></head><body>{svg_text}</body></html>'


def pages(pdf: Path) -> int:
    """Page count from pdfinfo."""
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    return int(re.search(r"^Pages:\s+(\d+)", out, re.M).group(1))


def write_pdf(sheet: Sheet, svg_text: str, pdf_path: str | Path) -> Path:
    """Print the SVG inside an HTML wrapper to a one-page PDF with Chrome."""
    pdf = Path(pdf_path).resolve()
    with tempfile.TemporaryDirectory(prefix="fp-chrome-") as tmp:
        html = Path(tmp) / "sheet.html"
        html.write_text(_wrapper(sheet, svg_text), encoding="utf-8")
        cmd = ["google-chrome", "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
               f"--user-data-dir={tmp}/profile", f"--print-to-pdf={pdf}", f"file://{html}"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not pdf.exists():
        raise RenderError(f"chrome produced no PDF: {r.stderr[-400:]}")
    n = pages(pdf)
    if n != 1:
        raise RenderError(f"{pdf.name}: expected 1 page, got {n}")
    return pdf


def write_png(pdf: str | Path, png_path: str | Path, dpi: int = 150) -> Path:
    """Rasterise a PDF to PNG with pdftoppm."""
    png = Path(png_path).resolve()
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-singlefile", str(pdf), str(png.with_suffix(""))],
                   check=True, capture_output=True)
    return png
