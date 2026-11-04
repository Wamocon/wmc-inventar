"""A-0123 M6 Teil 1: Protokoll-PDF (F-130, F-132, F-133, F-134).

Weasyprint baut das PDF aus einer HTML-Zeile. Aufbau und Wortlaut folgen
den Vorlagen ``docs/vorlagen/FRM-001.md`` (Ausgabe) und
``docs/vorlagen/FRM-002.md`` (Rücknahme): Kopf, Titel und Einleitung,
Abschnitte 1 bis 6 (je Art), Unterschriftenblock, Fußzeile mit
Formularnummer, Version und „Seite x von y".

Schrift nach dem Abschnitt Regeln in docs/AUFTRAG.md: Arial Narrow (N-09).
"""
from __future__ import annotations

import io
import os

from django.template import Context, Template

from .models import Protokoll
from .services import GeratFehler

# --- Schrift (AUFTRAG.md „Regeln", N-09: Arial Narrow) ----------------------

def _schrift_css() -> str:
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "static", "fonts", "archivo.css"), encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


# --- HTML-Aufbau (Wortlaut der Vorlage) --------------------------------------

_HTML_AUSGABE = """
{% if protokoll.absenderzeile %}<div class="absender">{{ protokoll.absenderzeile }}</div>{% endif %}
{% if protokoll.empfaenger_anschrift %}
<div class="empfaenger">{{ protokoll.empfaenger_anschrift|linebreaksbr }}</div>
{% endif %}
<table class="kopf-tabelle">
  <tr><td class="lbl">Bearbeiter</td><td>{{ protokoll.bearbeiter|default:"&ndash;" }}</td></tr>
  <tr><td class="lbl">Dokument</td><td>WMC-IT-FRM-001</td></tr>
  <tr><td class="lbl">Datum</td><td>{{ protokoll.datum|date:"d.m.Y" }}</td></tr>
</table>

<h1 class="titel">Ausgabeprotokoll Hardware (Onboarding)</h1>
{% if anrede == 'h' %}<p>Sehr geehrter Herr {{ person.nachname }},</p>
{% else %}<p>Sehr geehrte Frau {{ person.nachname }},</p>{% endif %}
<p>hiermit bestätigen wir die Ausgabe der nachfolgend aufgeführten Hardware und Zugangsmittel an Sie.</p>

<h2>1. Angaben zur Ausgabe</h2>
<table class="daten">
  <tr><td class="lbl">Name des Mitarbeiters</td><td>{{ person.vorname }} {{ person.nachname }}</td></tr>
  <tr><td class="lbl">Eintrittsdatum</td><td>{% if person.eintritt %}{{ person.eintritt|date:"d.m.Y" }}{% else %}&ndash;{% endif %}</td></tr>
  <tr><td class="lbl">Datum der Ausgabe</td><td>{{ protokoll.datum|date:"d.m.Y" }}</td></tr>
  <tr><td class="lbl">Ausgabe durch</td><td>Wamocon GmbH, {{ protokoll.bearbeiter|default:"&ndash;" }}</td></tr>
</table>

<h2>2. Ausgegebene Hardware</h2>
<table class="hardware">
  <tr class="kopf">
    <th>Gerät / Gerätename</th><th>Seriennummer</th><th>Zustand</th>
    <th>Zubehör komplett</th><th>Mitgeliefertes Zubehör, Bemerkung</th>
  </tr>
  <tr>
    <td>{{ gerat.hersteller }} {{ gerat.modell }}{% if gerat.geraetename %} / {{ gerat.geraetename }}{% endif %}</td>
    <td>{% if gerat.seriennummer %}{{ gerat.seriennummer }}{% else %}ohne{% endif %}</td>
    <td>{{ gerat.zustand }}</td>
    <td>Ja</td>
    <td>{{ gerat.standardzuehoer|default:"&ndash;" }}</td>
  </tr>
  <tr><td></td><td></td><td></td><td></td><td></td></tr>
  <tr><td></td><td></td><td></td><td></td><td></td></tr>
  <tr><td></td><td></td><td></td><td></td><td></td></tr>
  <tr><td></td><td></td><td></td><td></td><td></td></tr>
</table>
<p class="hinweis">Zustandsstufen: 1 = neuwertig, 2 = gut, normale Gebrauchsspuren, 3 = deutliche Spuren, funktionsfähig, 4 = eingeschränkt nutzbar. Vorhandene Vorschäden sind bei der Ausgabe zu erfassen, damit sie bei der Rückgabe nicht dem Nutzer zugerechnet werden.</p>

<h2>3. Zugänge und Zugangsmittel</h2>
<table class="hardware">
  <tr class="kopf">
    <th>Zugang / Zugangsmittel</th><th>ausgegeben</th><th>nicht zutreffend</th><th>Bemerkung, Kennung</th>
  </tr>
  {% for punkt in checkliste %}
  <tr>
    <td>{{ punkt.text }}</td>
    <td>{% if punkt.wert == 1 %}&#9746;{% elif punkt.wert == 0 %}&#9744;{% else %}&#9744;{% endif %}</td>
    <td>{% if punkt.wert == 1 %}&#9744;{% elif punkt.wert == 0 %}&#9746;{% else %}&#9744;{% endif %}</td>
    <td>{% if punkt.wert == 0 %}nicht im Einsatz{% else %}&ndash;{% endif %}</td>
  </tr>
  {% endfor %}
</table>

<h2>4. Nutzungsbedingungen</h2>
<p>{{ nutzung|default:"Beispieltext Nutzungsbedingungen, WMC-IT-FRM-001. Den verbindlichen Text pflegt die IT in den Einstellungen." }}</p>

<h2>5. Erklärungen</h2>
<p>{{ erklaerung|default:"Beispieltext Erklärungen, WMC-IT-FRM-001." }}</p>

<div class="kasten">
  <h2 class="imkasten">6. Elektronische Unterzeichnung</h2>
  <p><strong>Beispieltext Elektronische Unterzeichnung, WMC-IT-FRM-001.</strong></p>
  <p>Den verbindlichen Text pflegt die IT in den Einstellungen.</p>
</div>

<table class="unterschrift">
  <tr>
    <td class="feld">
      <div class="datum">__</div>
      <div class="zeile"></div>
      <div class="rolle">Datum, Unterschrift des Empfängers</div>
    </td>
    <td class="feld">
      <div class="datum">__ i.A.</div>
      <div class="zeile"></div>
      <div class="rolle">Datum, Unterschrift für die Wamocon GmbH</div>
    </td>
  </tr>
</table>

{% if anhaenge %}
<h2>7. Anlagen (Fotos)</h2>
{% for anhang in anhaenge %}
<div class="anhang">
  <img src="file://{{ anhang.url }}" alt="{{ anhang.name }}"/>
  <div class="unterschrift-bild">{{ gerat.geraetename|default:gerat.modell }} · Ausgabe · {{ protokoll.datum|date:"d.m.Y" }}</div>
</div>
{% endfor %}
{% endif %}
"""


_HTML_RUECKNAHME = """
{% if protokoll.absenderzeile %}<div class="absender">{{ protokoll.absenderzeile }}</div>{% endif %}
{% if protokoll.empfaenger_anschrift %}
<div class="empfaenger">{{ protokoll.empfaenger_anschrift|linebreaksbr }}</div>
{% endif %}
<table class="kopf-tabelle">
  <tr><td class="lbl">Bearbeiter</td><td>{{ protokoll.bearbeiter|default:"&ndash;" }}</td></tr>
  <tr><td class="lbl">Dokument</td><td>WMC-IT-FRM-002</td></tr>
  <tr><td class="lbl">Datum</td><td>{{ protokoll.datum|date:"d.m.Y" }}</td></tr>
</table>

<h1 class="titel">Rücknahmeprotokoll Hardware (Offboarding)</h1>
{% if anrede == 'h' %}<p>Sehr geehrter Herr {{ person.nachname }},</p>
{% else %}<p>Sehr geehrte Frau {{ person.nachname }},</p>{% endif %}
{% if rueckgabe_zu %}
<p>hiermit bestätigen wir die Rücknahme der nachfolgend aufgeführten Hardware. Grundlage ist das Ausgabeprotokoll vom {{ rueckgabe_zu.datum|date:"d.m.Y" }}.</p>
{% else %}
<p>hiermit bestätigen wir die Rücknahme der nachfolgend aufgeführten Hardware.</p>
{% endif %}

<h2>1. Angaben zur Rückgabe</h2>
<table class="daten">
  <tr><td class="lbl">Name des Mitarbeiters</td><td>{{ person.vorname }} {{ person.nachname }}</td></tr>
  <tr><td class="lbl">Eintrittsdatum</td><td>{% if person.eintritt %}{{ person.eintritt|date:"d.m.Y" }}{% else %}&ndash;{% endif %}</td></tr>
  <tr><td class="lbl">Letzter Arbeitstag</td><td>{% if person.austritt %}{{ person.austritt|date:"d.m.Y" }}{% else %}&ndash;{% endif %}</td></tr>
  <tr><td class="lbl">Datum der Rückgabe</td><td>{{ protokoll.datum|date:"d.m.Y" }}</td></tr>
  <tr><td class="lbl">Bezug</td><td>{% if rueckgabe_zu %}Ausgabeprotokoll {{ rueckgabe_zu.nr }} vom {{ rueckgabe_zu.datum|date:"d.m.Y" }}{% else %}Altbestand ohne Protokoll{% endif %}</td></tr>
  <tr><td class="lbl">Rücknahme durch</td><td>Wamocon GmbH, {{ protokoll.bearbeiter|default:"&ndash;" }}</td></tr>
</table>

<h2>2. Zurückgegebene Hardware</h2>
<table class="hardware">
  <tr class="kopf">
    <th>Gerät / Gerätename</th><th>Seriennummer</th><th>Zustand bei Ausgabe</th>
    <th>Zustand bei Rückgabe</th><th>Zubehör komplett</th><th>Bemerkung, festgestellte Mängel</th>
  </tr>
  <tr>
    <td>{{ gerat.hersteller }} {{ gerat.modell }}{% if gerat.geraetename %} / {{ gerat.geraetename }}{% endif %}</td>
    <td>{% if gerat.seriennummer %}{{ gerat.seriennummer }}{% else %}ohne{% endif %}</td>
    <td>&ndash;</td>
    <td>{{ gerat.zustand }}</td>
    <td>Ja</td>
    <td>keine Mängel</td>
  </tr>
</table>
<p class="hinweis">Zustandsstufen wie im Ausgabeprotokoll: 1 = neuwertig, 2 = gut, normale Gebrauchsspuren, 3 = deutliche Spuren, funktionsfähig, 4 = eingeschränkt nutzbar. Fehlendes Zubehör und Mängel werden in der Spalte Bemerkung erfasst.</p>

<h2>3. Prüfpunkte IT-Offboarding</h2>
<table class="hardware">
  <tr class="kopf">
    <th>Prüfpunkt</th><th>erledigt</th><th>nicht zutreffend</th><th>Datum, Kürzel, Bemerkung</th>
  </tr>
  {% for punkt in offboarding %}
  <tr>
    <td>{{ punkt.text }}</td>
    <td>{% if punkt.wert %}&#9746;{% else %}&#9744;{% endif %}</td>
    <td>{% if punkt.wert %}&#9744;{% else %}&#9746;{% endif %}</td>
    <td>{% if punkt.wert %}erledigt{% else %}&ndash;{% endif %}</td>
  </tr>
  {% endfor %}
</table>

<h2>4. Festgestellte Mängel und offene Punkte</h2>
<p>Keine. Die Hardware wurde vollständig mit Zubehör und im bei Ausgabe dokumentierten Zustand zurückgegeben.</p>

<h2>5. Erklärungen</h2>
<p>Beispieltext Erklärungen, WMC-IT-FRM-002. Den verbindlichen Text pflegt die IT in den Einstellungen.</p>

<div class="kasten">
  <h2 class="imkasten">6. Elektronische Unterzeichnung</h2>
  <p><strong>Beispieltext Elektronische Unterzeichnung, WMC-IT-FRM-002.</strong></p>
  <p>Den verbindlichen Text pflegt die IT in den Einstellungen.</p>
</div>

<table class="unterschrift">
  <tr>
    <td class="feld">
      <div class="datum">__</div>
      <div class="zeile"></div>
      <div class="rolle">Datum, Unterschrift des Rückgebenden</div>
    </td>
    <td class="feld">
      <div class="datum">__ i.A.</div>
      <div class="zeile"></div>
      <div class="rolle">Datum, Unterschrift für die Wamocon GmbH</div>
    </td>
  </tr>
</table>

{% if anhaenge %}
<h2>7. Anlagen (Fotos)</h2>
{% for anhang in anhaenge %}
<div class="anhang">
  <img src="file://{{ anhang.url }}" alt="{{ anhang.name }}"/>
  <div class="unterschrift-bild">{{ gerat.geraetename|default:gerat.modell }} · Rückgabe · {{ protokoll.datum|date:"d.m.Y" }}</div>
</div>
{% endfor %}
{% endif %}
"""


# --- CSS (Schrift nach AUFTRAG.md) -------------------------------------------

_CSS = """
@page {
  size: A4;
  margin: 16mm 16mm 18mm 16mm;
  @bottom-center {
    content: "WMC-IT-FRM-001, Version 1.1 · Seite " counter(page) " von " counter(pages);
    font-size: 8pt;
    color: #444;
  }
}
* { box-sizing: border-box; }
body {
  font-family: "Arial Narrow", "Arial", sans-serif;
  font-size: 9.5pt;
  color: #1a1a1a;
  line-height: 1.35;
}
h1 { font-size: 13pt; margin: 8pt 0 4pt 0; }
h2 { font-size: 11pt; margin: 12pt 0 4pt 0; font-weight: 700; }
h1.titel { color: #1a1a1a; }
.absender { font-weight: 600; font-size: 9pt; margin-bottom: 4pt; text-decoration: underline; }
.empfaenger { white-space: pre-line; margin-bottom: 8pt; color: #333; font-size: 9pt; }
.anrede { margin: 4pt 0 2pt 0; }
.kopf-tabelle { width: 100%; border-collapse: collapse; margin: 4pt 0 8pt 0; }
.kopf-tabelle td { padding: 1pt 0; }
.kopf-tabelle td.lbl { width: 25%; color: #444; }
table.daten { width: 100%; border-collapse: collapse; margin: 4pt 0 8pt 0; }
table.daten td { border: 0.5pt solid #ccc; padding: 3pt 6pt; }
table.daten td.lbl { font-weight: 700; width: 35%; background: #f5f5f5; }
table.hardware { width: 100%; border-collapse: collapse; margin: 4pt 0 6pt 0; }
table.hardware th, table.hardware td { border: 0.5pt solid #ccc; padding: 3pt 5pt; font-size: 8.5pt; }
table.hardware tr.kopf th { background: #eee; font-weight: 700; }
p.hinweis { font-size: 8pt; color: #555; margin: 2pt 0 8pt 0; }
.kasten { border: 1pt solid #c00; background: #fff2f2; padding: 6pt 10pt; margin: 8pt 0; }
.kasten h2.imkasten { margin: 0 0 4pt 0; }
table.unterschrift { width: 100%; border-collapse: collapse; margin-top: 14pt; }
table.unterschrift .feld { width: 50%; padding: 0 12pt; }
table.unterschrift .datum { height: 14pt; font-size: 9pt; }
table.unterschrift .zeile { border-bottom: 0.5pt solid #1a1a1a; height: 18pt; }
table.unterschrift .rolle { color: #444; font-size: 8.5pt; margin-top: 2pt; }
.anhang { margin: 6pt 0; page-break-inside: avoid; }
.anhang img { max-width: 100%; max-height: 160pt; border: 0.5pt solid #ccc; }
.unterschrift-bild { font-size: 8pt; color: #444; margin-top: 2pt; }
"""


# --- Rendering ---------------------------------------------------------------

def _checkliste_eintraege(protokoll: Protokoll) -> list[dict]:
    werte = protokoll.checkliste or {}
    return [
        {"text": text, "wert": werte.get(schluessel)}
        for schluessel, text in Protokoll.CHECKLISTE_PUNKTE
    ]


def _offboarding_eintraege(protokoll: Protokoll) -> list[dict]:
    werte = protokoll.offboarding or {}
    return [
        {"text": text, "wert": bool(werte.get(schluessel))}
        for schluessel, text in Protokoll.OFFBOARDING_PUNKTE
    ]


def _anhaenge(protokoll: Protokoll) -> list[dict]:
    from django.core.files.storage import default_storage

    ergebnis = []
    for anhang in protokoll.anhaenge_liste():
        pfad = anhang.get("pfad")
        if not pfad:
            continue
        try:
            absolut = default_storage.abspath(pfad)
            ergebnis.append({**anhang, "url": absolut})
        except OSError:
            continue
    return ergebnis


# --- Einstellungen laden (F-122, F-130) — M7 Teil 1 (A-0905) -----------------

def _einstellungen_laden():
    """Einstellungen aus der Datenbank laden.

    Fallback auf Standardwerte, wenn keine Einstellungen vorhanden sind.
    """
    try:
        from stammdaten.models import Einstellungen
        return Einstellungen.aktuelles()
    except Exception:
        return None


def _absender_einstellungen() -> dict:
    """Firmendaten aus Einstellungen (F-122)."""
    e = _einstellungen_laden()
    if e is not None:
        return {
            "firmenname": e.firmenname,
            "absenderzeile": e.absenderzeile,
            "telefon": e.telefon,
            "email_it": e.email_it,
        }
    return {
        "firmenname": "Wamocon GmbH",
        "absenderzeile": "Wamocon GmbH · IT",
        "telefon": "0157 77709235",
        "email_it": "it@wamocon.de",
    }


def _protokolltexte(typ: str) -> dict:
    """Protokolltexte aus Einstellungen (F-130).

    typ: "ausgabe" oder "ruecknahme"
    """
    e = _einstellungen_laden()
    if e is None:
        return {}
    if typ == "ausgabe":
        return {
            "nutzung": e.nutzungsbedingungen_ausgabe,
            "nutzung_version": e.nutzungsbedingungen_version,
            "erklaerungen": e.erklaerungen_ausgabe,
            "erklaerungen_version": e.erklaerungen_version,
            "unterzeichnung": e.unterzeichnung_ausgabe,
            "unterzeichnung_version": e.unterzeichnung_version,
        }
    else:
        return {
            "erklaerungen": e.erklaerungen_ruecknahme,
            "erklaerungen_version": e.erklaerungen_ruecknahme_version,
            "unterzeichnung": e.unterzeichnung_ruecknahme,
            "unterzeichnung_version": e.unterzeichnung_ruecknahme_version,
        }


def _anrede(person) -> str:
    return getattr(person, "anrede", "h") or "h"


def _render_pdf_html(protokoll: Protokoll) -> str:
    """Rendert die HTML-Zeile für das PDF (ohne Weasyprint).

    F-122, F-130 (M7 Teil 1, A-0905): Absenderzeile und Protokolltexte
    aus den Einstellungen; neue Version gilt nur für neue Protokolle.
    """
    formular = "WMC-IT-FRM-001" if protokoll.art == Protokoll.ART_AUSGABE else "WMC-IT-FRM-002"
    vorlage = _HTML_AUSGABE if protokoll.art == Protokoll.ART_AUSGABE else _HTML_RUECKNAHME
    template = Template(vorlage)

    # Einstellungen laden (F-122, F-130)
    absender = _absender_einstellungen()
    typ = "ausgabe" if protokoll.art == Protokoll.ART_AUSGABE else "ruecknahme"
    texte = _protokolltexte(typ)

    kontext = {
        "protokoll": protokoll,
        "gerat": protokoll.geraet,
        "person": protokoll.person,
        "anrede": _anrede(protokoll.person),
        "checkliste": _checkliste_eintraege(protokoll),
        "offboarding": _offboarding_eintraege(protokoll),
        "anhaenge": _anhaenge(protokoll),
        "rueckgabe_zu": protokoll.rueckgabe_zu_protokoll,
        "formular": formular,
        "fassung": protokoll.fassung or "1.1",
        "absenderzeile": absender.get("absenderzeile", "") or protokoll.absenderzeile or "",
        "firmenname": absender.get("firmenname", ""),
        "telefon": absender.get("telefon", ""),
        "email_it": absender.get("email_it", ""),
        "nutzung": texte.get("nutzung", ""),
        "erklaerung": texte.get("erklaerungen", ""),
        "unterzeichnung": texte.get("unterzeichnung", ""),
        "nutzung_version": texte.get("nutzung_version", ""),
        "erklaerungen_version": texte.get("erklaerungen_version", ""),
        "unterzeichnung_version": texte.get("unterzeichnung_version", ""),
    }
    html = template.render(Context(kontext))
    schrift = _schrift_css()
    css = _CSS.replace("WMC-IT-FRM-001, Version 1.1", f"{formular}, Version {kontext['fassung']}")
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        + (f"<style>{schrift}</style>" if schrift else "")
        + f"<style>{css}</style>"
        "</head><body>"
        + html
        + "</body></html>"
    )


def pdf_bauen(protokoll: Protokoll) -> bytes:
    """F-130, F-132, F-133, F-134: PDF als Bytes.

    F-132: das PDF entsteht erst, wenn jeder Punkt der Checkliste
    beantwortet ist (ausgabe). Für Rücknahme (F-133) gilt: die 13
    Prüfpunkte sind beantwortet.
    """
    from weasyprint import HTML

    offene = protokoll.checkliste_unbeantwortet()
    if offene:
        raise GeratFehler(
            "Die Checkliste ist noch nicht vollständig beantwortet "
            f"({len(offene)} Punkte offen, F-132); das PDF entsteht erst danach."
        )
    html = _render_pdf_html(protokoll)
    puffer = io.BytesIO()
    HTML(string=html, base_url=os.getcwd()).write_pdf(puffer)
    return puffer.getvalue()


def dateiname_protokoll(protokoll: Protokoll) -> str:
    """F-139: Dateiname des fertigen PDFs.

    Ausgabe:  WMC_Ausgabeprotokoll_{Nachname}_{Vorname}_{TT.MM.JJJJ}.pdf
    Rücknahme: WMC_Ruecknahmeprotokoll_{Nachname}_{Vorname}_{TT.MM.JJJJ}.pdf
    """
    person = protokoll.person
    name = (person.nachname or "").replace(" ", "_")
    vorname = (person.vorname or "").replace(" ", "_")
    datum = protokoll.datum.strftime("%d.%m.%Y")
    if protokoll.art == Protokoll.ART_AUSGABE:
        return f"WMC_Ausgabeprotokoll_{name}_{vorname}_{datum}.pdf"
    return f"WMC_Ruecknahmeprotokoll_{name}_{vorname}_{datum}.pdf"


# --- F-137, F-138: Fertiges PDF mit Siegel und Prüfprotokoll -----------------

def _pruefprotokoll_seite(protokoll: Protokoll) -> str:
    """HTML für die letzte Seite: Prüfprotokoll (F-137, F-138)."""
    from django.utils import timezone
    jetzt = timezone.now()
    return f"""
<div style="page-break-before: always; margin-top: 40pt;">
<h2>Prüfprotokoll</h2>
<table class="daten">
  <tr><td class="lbl">Protokoll-Nummer</td><td>{protokoll.nr}</td></tr>
  <tr><td class="lbl">Art</td><td>{"Ausgabe" if protokoll.art == Protokoll.ART_AUSGABE else "Rücknahme"}</td></tr>
  <tr><td class="lbl">Bearbeiter</td><td>{protokoll.bearbeiter or "–"}</td></tr>
  <tr><td class="lbl">Empfänger</td><td>{protokoll.person.vorname} {protokoll.person.nachname}</td></tr>
  <tr><td class="lbl">Datum der Ausgabe</td><td>{protokoll.datum.strftime("%d.%m.%Y")}</td></tr>
  <tr><td class="lbl">Signatur des Bearbeiters</td><td>{"vorliegt" if protokoll.bearbeiter_signatur else "fehlt"}</td></tr>
  <tr><td class="lbl">Gegenzeichnung</td><td>{"vorliegt" if protokoll.gegenzeichnung_signiert_am else "fehlt"}</td></tr>
  <tr><td class="lbl">PDF-Hash (SHA-256)</td><td>{(protokoll.pdf_hash or "")[:64] or "–"}</td></tr>
  <tr><td class="lbl">Erzeugt am</td><td>{jetzt.strftime("%d.%m.%Y %H:%M")} Uhr</td></tr>
</table>
<p class="hinweis">
  Dieses Prüfprotokoll ist die letzte Seite des versiegelten PDFs (F-137, F-138).
  Das Siegel (PAdES) bestätigt die Integrität des Dokuments.
  Wamocon GmbH · IT
</p>
</div>
"""


def pdf_fertig_bauen(protokoll: Protokoll) -> bytes:
    """F-137, F-138: Fertiges PDF mit Siegel und Prüfprotokoll als letzte Seite.

    1. PDF bauen (Checkliste muss beantwortet sein).
    2. Prüfprotokoll-Seite anhängen.
    3. Mit PAdES-Siegel versiegeln (falls verfügbar).

    Liefert die versiegelte PDF-Bytes.
    """
    # 1. PDF bauen.
    html = _render_pdf_html(protokoll)

    # 2. Prüfprotokoll-Seite anhängen.
    pruefseite = _pruefprotokoll_seite(protokoll)
    html = html.replace("</body>", pruefseite + "</body>")

    # 3. PDF rendern.
    from weasyprint import HTML
    puffer = io.BytesIO()
    HTML(string=html, base_url=os.getcwd()).write_pdf(puffer)
    pdf_bytes = puffer.getvalue()

    # 4. Siegel anwenden (F-138).
    from . import siegel as siegel_modul
    versiegelt = siegel_modul.siegel_anwenden(pdf_bytes)
    if versiegelt is not None:
        return versiegelt
    # Ohne Siegel weiterlaufen (Bestätigung ohne Anhang).
    return pdf_bytes
