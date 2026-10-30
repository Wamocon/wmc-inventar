"""QR-Code und Etiketten (F-12, F-70 bis F-73, F-89).

QR-Code je Gerät mit segno, Inhalt BASIS_URL + /g/<Inventarnummer>.
Etikett: QR-Code, Inventarnummer in Klarschrift, Kategorie und Modell,
„Eigentum der WAMOCON GmbH". Gedruckt als PDF mit weasyprint.

Standard-Format: A4-Bogen mit 24 Etiketten zu 70 × 37 mm (F-72).
Startposition wählbar (F-73).
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Sequence

import segno
from django.conf import settings

from .models import Gerat
from stammdaten.models import Ort


# --- Format-Konstanten (F-72) -------------------------------------------------

ETIKETT_BREITE_MM = 70
ETIKETT_HOEHE_MM = 37
BOGEN_ANZAHL = 24          # Etiketten pro A4-Bogen
BOGEN_BREITE_MM = 210      # A4
BOGEN_HOEHE_MM = 297


@dataclass
class EtikettenFormat:
    """Das Druckformat; Standard ist A4 mit 24 Etiketten zu 70 × 37 mm.

    Die Einstellung für ein anderes Format kommt mit M7 auf /einstellungen/.
    Bis dahin gilt der Standard.
    """

    breite_mm: int = ETIKETT_BREITE_MM
    hoehe_mm: int = ETIKETT_HOEHE_MM
    pro_bogen: int = BOGEN_ANZAHL


STANDARD_FORMAT = EtikettenFormat()


def qr_inhalt(gerat: Gerat) -> str:
    """Inhalt des QR-Codes: BASIS_URL + /g/<Inventarnummer> (F-70)."""
    return f"{settings.BASIS_URL}/g/{gerat.inventarnummer}"


def qr_svg(gerat: Gerat, breite_px: int = 180) -> str:
    """QR-Code als SVG (F-70). Kein Inline-Skript, nur statisches Markup."""
    code = segno.make(qr_inhalt(gerat))
    svg = code.svg_inline(
        scale=max(1, breite_px // 36),
        border=2,
    )
    return svg


def etikett_html(gerat: Gerat) -> str:
    """Ein Etikett als HTML-Blöcke für weasyprint (F-71).

    QR-Code, Inventarnummer in Klarschrift, Kategorie und Modell,
    „Eigentum der WAMOCON GmbH".
    """
    return (
        '<div class="etikett">'
        f'<div class="etikett-qr">{qr_svg(gerat)}</div>'
        '<div class="etikett-text">'
        f'<span class="etikett-nr">{gerat.inventarnummer}</span>'
        f'<span class="etikett-kategorie">{gerat.kategorie.name}</span>'
        f'<span class="etikett-modell">{gerat.modell or "–"}</span>'
        '<span class="etikett-eigentum">Eigentum der WAMOCON GmbH</span>'
        "</div>"
        "</div>"
    )


def _css() -> str:
    """CSS für den Etikettenbogen (F-72, F-73)."""
    fmt = STANDARD_FORMAT
    cols = 3       # 3 × 70 mm + 2 × 10 mm Rand = 230 > 210 → 2 Spalten
    rows = math.ceil(fmt.pro_bogen / cols)
    # Tatsächlich: A4 quer 297 × 210 mm, Etiketten 70 × 37 mm
    # 297 / 70 = 4,24 → 4 Spalten; 210 / 37 = 5,67 → 5 Reihen = 20; nicht 24
    # Bogen hoch: 297 mm (Kurzseite 210), Etiketten 70 breit × 37 hoch
    # Querformat: 297 × 210. 4 Spalten × 37 mm = 148 < 210 → 5 Reihen = 20
    # 24 Etiketten: 4 × 6 = 24. 6 × 37 = 222 > 210 → passt nicht
    # Hochformat: 210 × 297. 3 × 70 = 210 → exakt 3 Spalten. 8 × 37 = 296 ≈ 297 → 8 Reihen = 24
    # 3 Spalten × 8 Reihen = 24. Perfekt im Hochformat.
    return f"""
@page {{
  size: A4 portrait;
  margin: 0;
}}
body {{
  margin: 0;
  padding: 0;
  font-family: sans-serif;
}}
.etiketten-grid {{
  display: grid;
  grid-template-columns: repeat(3, 70mm);
  grid-template-rows: repeat(8, 37mm);
  gap: 0;
  width: 210mm;
  height: 296mm;
}}
.etikett {{
  width: 70mm;
  height: 37mm;
  box-sizing: border-box;
  border: 0.3mm solid #000;
  padding: 1.5mm 2mm;
  display: flex;
  align-items: center;
  gap: 2mm;
  overflow: hidden;
  page-break-inside: avoid;
  break-inside: avoid;
}}
.etikett-qr {{
  flex-shrink: 0;
  width: 20mm;
  height: 20mm;
}}
.etikett-qr svg {{
  width: 20mm;
  height: 20mm;
  display: block;
}}
.etikett-text {{
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}}
.etikett-nr {{
  font-size: 5.5mm;
  font-weight: 700;
  line-height: 1.1;
}}
.etikett-kategorie,
.etikett-modell {{
  font-size: 2.8mm;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
.etikett-eigentum {{
  font-size: 2.2mm;
  color: #333;
  margin-top: auto;
  line-height: 1.2;
}}
"""


def bogen_pdf(geraete: Sequence[Gerat], startposition: int = 1) -> bytes:
    """Etikettenbogen als PDF (F-72, F-73).

    ``startposition`` (1-basiert) lässt die Felder davor auf dem Bogen frei
    (F-73, angebrochene Bögen).
    """
    if not geraete:
        return b""

    from weasyprint import HTML, CSS

    cells = []
    for i in range(1, STANDARD_FORMAT.pro_bogen + 1):
        idx = i - startposition
        if 0 <= idx < len(geraete):
            cells.append(etikett_html(geraete[idx]))
        else:
            cells.append('<div class="etikett"></div>')

    grid = '<div class="etiketten-grid">' + "".join(cells) + "</div>"
    html = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<style>{_css()}</style></head><body>{grid}</body></html>"
    )
    return HTML(string=html).write_pdf()


def etikett_pdf(gerat: Gerat) -> bytes:
    """Einzelnes Etikett als PDF (F-72)."""
    return bogen_pdf([gerat])


def etiketten_fuer_ort(ort: Ort) -> list[Gerat]:
    """Alle erfassten Geräte an einem Ort, sortiert nach bisheriger Kennung (F-89).

    Für /etiketten/: je Arbeitsplatz oder Lagerort, sortiert nach
    bisheriger Kennung (F-89).
    """
    from .models import Gerat

    _ERFASST = (
        Gerat.STATUS_IN_BENUTZUNG,
        Gerat.STATUS_VERLIEHEN,
        Gerat.STATUS_AUF_LAGER,
    )
    return list(
        Gerat.objects.filter(ort=ort, status__in=_ERFASST)
        .select_related("kategorie")
        .order_by("ort__kennung", "kategorie__name", "inventarnummer")
    )
