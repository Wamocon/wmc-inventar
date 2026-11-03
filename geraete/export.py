"""Export der Listen als .xlsx und .csv (F-103, M7 Teil 3, A-0907).

Jede Liste der Übersicht wird mit ihrem aktuellen Filter exportiert:
.xlsx mit openpyxl, .csv mit der Standardbibliothek.

TESTSCHNITTSTELLE.md Kapitel 3: format=xlsx liefert eine Datei, die
openpyxl öffnen kann; format=csv enthält nur die gefilterten Zeilen.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse


def _wert_zelle(wert) -> object:
    """Normiert einen Wert für eine Tabellenzelle (XLSX und CSV)."""
    if isinstance(wert, (date, datetime)):
        return wert.strftime("%d.%m.%Y")
    if isinstance(wert, Decimal):
        return f"{wert:,.2f}".replace(",", "")
    if isinstance(wert, (list, tuple)):
        return " · ".join(str(w) for w in wert if w)
    if isinstance(wert, str):
        return wert
    if wert is None:
        return ""
    return str(wert)


def _spaltenwerte(kopfzeile: list[str], daten: list[dict]) -> list[list]:
    """Alle Zellen als Text, für CSV und für den XLSX-Abgleich."""
    zeilen = [list(kopfzeile)]
    for zeile in daten:
        zeilen.append([
            str(_wert_zelle(zeile.get(spalte))) for spalte in kopfzeile
        ])
    return zeilen


def antwort_csv(kopfzeile: list[str], daten: list[dict], dateiname: str) -> HttpResponse:
    """CSV-Antwort (F-103): Kopfzeile plus die Zeilen mit aktuellem Filter."""
    puffer = io.StringIO()
    puffer.write("\ufeff")
    schriftsteller = csv.writer(puffer, delimiter=";")
    for zeile in _spaltenwerte(kopfzeile, daten):
        schriftsteller.writerow(zeile)
    antwort = HttpResponse(puffer.getvalue(), content_type="text/csv; charset=utf-8")
    antwort["Content-Disposition"] = f'attachment; filename="{dateiname}.csv"'
    return antwort


def antwort_xlsx(kopfzeile: list[str], daten: list[dict], dateiname: str) -> HttpResponse:
    """XLSX-Antwort (F-103): Datei, die openpyxl öffnen kann."""
    from openpyxl import Workbook

    werkmappe = Workbook()
    blatt = werkmappe.active
    blatt.title = "Liste"
    blatt.append(list(kopfzeile))
    for zeile in daten:
        blatt.append([_wert_zelle(zeile.get(spalte)) for spalte in kopfzeile])
    puffer = io.BytesIO()
    werkmappe.save(puffer)
    inhalt = puffer.getvalue()
    antwort = HttpResponse(inhalt, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    antwort["Content-Disposition"] = f'attachment; filename="{dateiname}.xlsx"'
    return antwort
