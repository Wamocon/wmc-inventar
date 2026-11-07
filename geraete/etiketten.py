"""QR-Code und Etiketten (F-12, F-70 bis F-73, F-89).

QR-Code je Gerät mit segno, Inhalt BASIS_URL + /g/<Inventarnummer>.
Etikett: QR-Code, Inventarnummer in Klarschrift, Kategorie und Modell,
„Eigentum der WAMOCON GmbH". Gedruckt als PDF mit weasyprint.

Das Format steht in den Einstellungen (F-72), Standard: A4-Bogen mit
24 Etiketten zu 70 × 37 mm. Startposition wählbar (F-73). Was nicht auf
einen Bogen passt, kommt auf den nächsten.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Sequence

import segno
from django.conf import settings
from django.utils.safestring import mark_safe

from .models import Gerat
from stammdaten.models import Einstellungen, Ort


# --- Format-Konstanten (F-72) -------------------------------------------------

ETIKETT_BREITE_MM = 70
ETIKETT_HOEHE_MM = 37
BOGEN_ANZAHL = 24          # Etiketten pro A4-Bogen
BOGEN_BREITE_MM = 210      # A4
BOGEN_HOEHE_MM = 297


@dataclass(frozen=True)
class EtikettenFormat:
    """Ein Druckformat; der Schlüssel ist der Wert aus den Einstellungen."""

    schluessel: str = "a4"
    text: str = "A4-Bogen, 24 Etiketten, 70 × 37 mm"
    seite: str = "A4"
    spalten: int = 3
    zeilen: int = 8
    breite_mm: int = ETIKETT_BREITE_MM
    hoehe_mm: int = ETIKETT_HOEHE_MM

    @property
    def pro_bogen(self) -> int:
        return self.spalten * self.zeilen


STANDARD_FORMAT = EtikettenFormat()
FORMATE = {
    "a4": STANDARD_FORMAT,
    "a5": EtikettenFormat(
        schluessel="a5", text="A5-Bogen, 10 Etiketten, 74 × 42 mm", seite="A5",
        spalten=2, zeilen=5, breite_mm=74, hoehe_mm=42,
    ),
}


def format_aus_einstellungen() -> EtikettenFormat:
    """Das Format aus den Einstellungen (F-72, F-122)."""
    return FORMATE.get(Einstellungen.aktuelles().etikettenformat, STANDARD_FORMAT)


def startposition_lesen(wert, fmt: EtikettenFormat) -> int:
    """Startposition auf dem Bogen (F-73). Falsche Werte werden nicht still umgebogen."""
    if wert in (None, ""):
        return 1
    meldung = f"Die Startposition muss zwischen 1 und {fmt.pro_bogen} liegen."
    try:
        start = int(wert)
    except (TypeError, ValueError) as e:
        raise ValueError(meldung) from e
    if not 1 <= start <= fmt.pro_bogen:
        raise ValueError(meldung)
    return start


def qr_inhalt(gerat: Gerat) -> str:
    """Inhalt des QR-Codes: BASIS_URL + /g/<Inventarnummer> (F-70)."""
    return f"{settings.BASIS_URL}/g/{gerat.inventarnummer}"


def qr_svg(gerat: Gerat, breite_px: int = 180) -> str:
    """QR-Code als SVG (F-70). Kein Inline-Skript, nur statisches Markup."""
    code = segno.make(qr_inhalt(gerat))
    # omitsize: Mit viewBox statt fester Größe; sonst schneidet der Browser den Code
    # ab, sobald die Seite ihn kleiner zeigt, und er lässt sich nicht mehr scannen.
    svg = code.svg_inline(
        scale=max(1, breite_px // 36),
        border=2,
        omitsize=True,
    )
    return svg


def _kuerzen(text: str, zeichen: int) -> str:
    """Passt der Text nicht aufs Etikett, zeigt ein Auslassungszeichen das (F-71)."""
    text = " ".join((text or "").split())
    return text if len(text) <= zeichen else text[: zeichen - 1].rstrip() + "…"


def _modell_zeichen(fmt: EtikettenFormat) -> int:
    # Platz neben dem QR-Code bei 2,8 mm Schrift, rund 1,7 mm je Zeichen.
    return int((fmt.breite_mm - 26) / 1.7)


def etikett_html(gerat: Gerat, fmt: EtikettenFormat = STANDARD_FORMAT) -> str:
    """Ein Etikett als HTML-Blöcke für weasyprint (F-71).

    QR-Code, Inventarnummer in Klarschrift, Kategorie und Modell,
    „Eigentum der WAMOCON GmbH". Die Texte kommen aus der Datenbank und
    werden hier von Hand gesetzt, deshalb maskiert.
    """
    kategorie = html.escape(_kuerzen(gerat.kategorie.name, _modell_zeichen(fmt)))
    modell = html.escape(_kuerzen(gerat.modell, _modell_zeichen(fmt)) or "–")
    return (
        '<div class="etikett">'
        f'<div class="etikett-qr">{qr_svg(gerat)}</div>'
        '<div class="etikett-text">'
        f'<span class="etikett-nr">{gerat.inventarnummer}</span>'
        f'<span class="etikett-kategorie">{kategorie}</span>'
        f'<span class="etikett-modell">{modell}</span>'
        '<span class="etikett-eigentum">Eigentum der WAMOCON GmbH</span>'
        "</div>"
        "</div>"
    )


def _css(fmt: EtikettenFormat = STANDARD_FORMAT) -> str:
    """CSS für den Etikettenbogen (F-72, F-73).

    A4 hoch: 3 × 70 mm = 210 mm und 8 × 37 mm = 296 mm, das sind 24 Etiketten.
    Der Bogen ist vorgestanzt: Leere Felder bleiben ohne Rahmen und Druck.
    """
    return f"""
@page {{
  size: {fmt.seite} portrait;
  margin: 0;
}}
body {{
  margin: 0;
  padding: 0;
  font-family: Archivo, sans-serif;
  font-stretch: condensed;
}}
.etiketten-grid {{
  display: grid;
  grid-template-columns: repeat({fmt.spalten}, {fmt.breite_mm}mm);
  grid-template-rows: repeat({fmt.zeilen}, {fmt.hoehe_mm}mm);
  gap: 0;
  width: {fmt.spalten * fmt.breite_mm}mm;
  height: {fmt.zeilen * fmt.hoehe_mm}mm;
  overflow: hidden;
}}
.etiketten-grid.weiter {{
  break-after: page;
  page-break-after: always;
}}
.etikett {{
  width: {fmt.breite_mm}mm;
  height: {fmt.hoehe_mm}mm;
  box-sizing: border-box;
  border-top: 1.2mm solid #F40E0E;
  padding: 1.5mm 2mm;
  display: flex;
  align-items: center;
  gap: 2mm;
  overflow: hidden;
  page-break-inside: avoid;
  break-inside: avoid;
}}
.etikett-leer {{
  width: {fmt.breite_mm}mm;
  height: {fmt.hoehe_mm}mm;
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
  white-space: nowrap;
}}
.etikett-eigentum {{
  font-size: 2.2mm;
  color: #333;
  margin-top: auto;
  line-height: 1.2;
}}
"""


def bogen_seiten(geraete: Sequence[Gerat], startposition: int = 1,
                 fmt: EtikettenFormat = STANDARD_FORMAT) -> list[list[Gerat | None]]:
    """Die Felder je Bogen; None ist ein leeres Feld (F-72, F-73).

    Die Felder vor ``startposition`` (1-basiert) bleiben auf dem ersten Bogen
    frei (angebrochene Bögen). Jedes Gerät bekommt ein Feld, der letzte Bogen
    wird mit leeren Feldern aufgefüllt.
    """
    start = max(1, min(fmt.pro_bogen, startposition))
    felder: list[Gerat | None] = [None] * (start - 1) + list(geraete)
    felder += [None] * (-len(felder) % fmt.pro_bogen)
    return [felder[i:i + fmt.pro_bogen] for i in range(0, len(felder), fmt.pro_bogen)]


def bogen_pdf(geraete: Sequence[Gerat], startposition: int = 1,
              fmt: EtikettenFormat | None = None) -> bytes:
    """Etikettenbogen als PDF (F-72, F-73): so viele Bögen, wie die Geräte brauchen."""
    if not geraete:
        return b""
    fmt = fmt or format_aus_einstellungen()

    from weasyprint import HTML

    seiten = bogen_seiten(geraete, startposition, fmt)
    bloecke = []
    for nr, seite in enumerate(seiten, start=1):
        zellen = "".join(
            etikett_html(g, fmt) if g is not None else '<div class="etikett-leer"></div>'
            for g in seite
        )
        klasse = "etiketten-grid weiter" if nr < len(seiten) else "etiketten-grid"
        bloecke.append(f'<div class="{klasse}">{zellen}</div>')
    dokument = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<style>{_css(fmt)}</style></head><body>{''.join(bloecke)}</body></html>"
    )
    from .pdf import _STATIC_FONTS, _schrift_css
    schrift = f"<style>{_schrift_css()}</style>"
    return HTML(string=schrift + dokument, base_url=_STATIC_FONTS.as_uri() + "/").write_pdf()


def etikett_pdf(gerat: Gerat) -> bytes:
    """Einzelnes Etikett als PDF (F-72)."""
    return bogen_pdf([gerat])


def vorschau_seiten(geraete: Sequence[Gerat], startposition: int,
                    fmt: EtikettenFormat) -> list[list[dict | None]]:
    """Dieselben Felder wie im PDF, für die Druckvorschau (Kapitel 6)."""
    seiten = []
    for seite in bogen_seiten(geraete, startposition, fmt):
        seiten.append([
            None if g is None else {
                "nr": g.inventarnummer,
                "text": ", ".join(t for t in (g.kategorie.name, g.modell) if t),
                "qr": mark_safe(qr_svg(g)),
            }
            for g in seite
        ])
    return seiten


def etiketten_fuer_ort(ort: Ort) -> list[Gerat]:
    """Alle erfassten Geräte an einem Ort, sortiert nach bisheriger Kennung (F-89).

    Die bisherige Kennung steht im Gerätenamen; Geräte ohne sie kommen danach,
    nach Inventarnummer.
    """
    from .models import Gerat

    _ERFASST = (
        Gerat.STATUS_IN_BENUTZUNG,
        Gerat.STATUS_VERLIEHEN,
        Gerat.STATUS_AUF_LAGER,
    )
    return sorted(
        Gerat.objects.filter(ort=ort, status__in=_ERFASST).select_related("kategorie"),
        key=lambda g: (not g.geraetename, g.geraetename.lower(), g.inventarnummer),
    )
