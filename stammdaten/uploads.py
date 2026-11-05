"""Hochgeladene Dateien prüfen (N-02, F-67, F-122).

Der Dateityp wird am Inhalt erkannt, nie an der Endung oder am Content-Type
des Browsers. Nur PNG, JPG, SVG und PDF bis 10 MB.
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET

GROESSE_MAX = 10 * 1024 * 1024

ENDUNGEN = {
    "png": (".png",),
    "jpg": (".jpg", ".jpeg"),
    "svg": (".svg",),
    "pdf": (".pdf",),
}

# Nur als Bild gedacht: Skripte aus, sonst nichts laden (N-02).
CSP_SVG = "script-src 'none'; default-src 'none'; style-src 'unsafe-inline'; img-src data:"


class UploadFehler(ValueError):
    """Datei abgelehnt; die Meldung darf in die Oberfläche."""


def _ist_svg(daten: bytes) -> bool:
    kopf = daten[:4096].lower()
    # Kein DOCTYPE und keine Entitäten: schützt vor Entitäten-Bomben.
    if b"<!doctype" in daten.lower() or b"<!entity" in daten.lower():
        return False
    if b"<svg" not in kopf and b":svg" not in kopf:
        return False
    try:
        wurzel = ET.fromstring(daten)
    except ET.ParseError:
        return False
    return wurzel.tag == "svg" or wurzel.tag.endswith("}svg")


def _ist_rasterbild(daten: bytes, format_name: str) -> bool:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(daten)) as bild:
            bild.verify()
            return bild.format == format_name
    except Exception:
        return False


def dateityp_erkennen(daten: bytes) -> str:
    """Art der Datei am Inhalt: ``png``, ``jpg``, ``svg``, ``pdf`` oder leer."""
    if daten.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png" if _ist_rasterbild(daten, "PNG") else ""
    if daten.startswith(b"\xff\xd8\xff"):
        return "jpg" if _ist_rasterbild(daten, "JPEG") else ""
    if daten.startswith(b"%PDF-"):
        return "pdf"
    if _ist_svg(daten):
        return "svg"
    return ""


def datei_pruefen(datei, erlaubt: tuple[str, ...], meldung_typ: str) -> tuple[str, bytes]:
    """Datei lesen und prüfen. Rückgabe: erkannte Art und Inhalt.

    ``meldung_typ`` steht in der Meldung, wenn der Typ nicht passt. Eine
    abgelehnte Datei ändert nichts: Die Prüfung läuft vor dem Speichern.
    """
    if datei.size > GROESSE_MAX:
        raise UploadFehler("Die Datei ist größer als 10 MB.")
    name = (datei.name or "").lower()
    endungen = tuple(e for art in erlaubt for e in ENDUNGEN[art])
    if not name.endswith(endungen):
        raise UploadFehler(meldung_typ)
    daten = datei.read()
    art = dateityp_erkennen(daten)
    if art not in erlaubt:
        raise UploadFehler(f"{meldung_typ} Der Inhalt der Datei passt nicht dazu.")
    return art, daten


def bild_aus_pdf(daten: bytes) -> bytes:
    """Erste Seite eines PDFs als PNG (F-67, pypdfium2)."""
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(daten)
    except Exception as fehler:
        raise UploadFehler("Das PDF lässt sich nicht lesen.") from fehler
    try:
        if len(doc) == 0:
            raise UploadFehler("Das PDF hat keine Seiten.")
        bild = doc[0].render(scale=2).to_pil()
        puffer = io.BytesIO()
        bild.save(puffer, format="PNG")
        return puffer.getvalue()
    finally:
        doc.close()
