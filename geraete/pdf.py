"""Protokoll-PDF nach WMC-IT-FRM-001 und FRM-002 (F-130 bis F-139, N-09).

Weasyprint baut das PDF aus HTML. Aufbau und Wortlaut folgen
``docs/vorlagen/FRM-001.md`` (Ausgabe, Leihe) und ``FRM-002.md`` (Rücknahme).

Der Inhalt wird mit der Signatur des Bearbeiters eingefroren (F-135): Das HTML
steht danach in ``Protokoll.html_eingefroren`` und ändert sich nicht mehr, auch
wenn sich Gerät, Person oder Einstellungen später ändern. Dazu kommen nur noch
die Signaturvermerke und das Prüfprotokoll als letzte Seite (F-137).
"""
from __future__ import annotations

import hashlib
import html as html_modul
import io
import os
from pathlib import Path

from django.template import Context, Template
from django.utils import timezone

from .models import Protokoll
from .services import GeratFehler

_STATIC_FONTS = Path(__file__).resolve().parent.parent / "static" / "fonts"
_VERMERK_EMPFAENGER = "<!--VERMERK-EMPFAENGER-->"
_VERMERK_BEARBEITER = "<!--VERMERK-BEARBEITER-->"


def _schrift_css() -> str:
    try:
        return (_STATIC_FONTS / "archivo.css").read_text(encoding="utf-8")
    except OSError:
        return ""


# --- Kopf und Rahmen, für beide Vorlagen gleich -------------------------------

_KOPF = """
<div class="falz f1"></div><div class="falz f2"></div><div class="falz f3"></div>
{% if logo %}<img class="logo" src="{{ logo }}" alt="">{% endif %}
<table class="briefkopf"><tr>
  <td class="links">
    {% if absenderzeile %}<div class="absender">{{ absenderzeile }}</div>{% endif %}
    <div class="empfaenger">{% if anrede_zeile %}{{ anrede_zeile }}<br>{% endif %}{{ person.vorname }} {{ person.nachname }}{% if anschrift %}<br>{{ anschrift|linebreaksbr }}{% endif %}</div>
  </td>
  <td class="rechts">
    <table class="kopf-tabelle">
      <tr><td class="lbl">Bearbeiter</td><td>{{ bearbeiter|default:"–" }}</td></tr>
      <tr><td class="lbl">Telefon</td><td>{{ telefon|default:"–" }}</td></tr>
      <tr><td class="lbl">E-Mail</td><td>{{ email_it|default:"–" }}</td></tr>
      <tr><td class="lbl">Dokument</td><td>{{ dokument }}</td></tr>
      <tr><td class="lbl">Datum</td><td>{{ protokoll.datum|date:"d.m.Y" }}</td></tr>
    </table>
  </td>
</tr></table>
"""

_UNTERSCHRIFT = """
<table class="unterschrift"><tr>
  <td class="feld">
    <div class="datum">""" + _VERMERK_EMPFAENGER + """</div>
    <div class="zeile"></div>
    <div class="rolle">Datum, Unterschrift des {{ rolle_links }}</div>
  </td>
  <td class="feld">
    <div class="datum">""" + _VERMERK_BEARBEITER + """</div>
    <div class="zeile"></div>
    <div class="rolle">Datum, Unterschrift für die {{ firmenname }}</div>
  </td>
</tr></table>
"""

_ANLAGEN = """
{% if anhaenge %}<div class="anlagen"><h2>Anlagen</h2>{% endif %}
{% for anhang in anhaenge %}
<div class="anhang">
  {% if anhang.url %}<img src="{{ anhang.url }}" alt="{{ anhang.name }}">{% else %}<p class="hinweis">{{ anhang.name }}: Für dieses Bildformat gibt es keine Vorschau.</p>{% endif %}
  <div class="unterschrift-bild">{{ anhang.geraet_name|default:geraetename_kurz }} · {{ anlass }} · {{ protokoll.datum|date:"d.m.Y" }}</div>
</div>
{% endfor %}
{% if anhaenge %}</div>{% endif %}
"""


_HTML_AUSGABE = _KOPF + """
<h1 class="titel">{{ titel }}</h1>
<p>{{ anrede_satz }},</p>
<p>hiermit bestätigen wir die Ausgabe der nachfolgend aufgeführten Hardware und Zugangsmittel an Sie.</p>

<h2>1. Angaben zur Ausgabe</h2>
<table class="daten">
  <tr><td class="lbl">Name des Mitarbeiters</td><td>{{ person.vorname }} {{ person.nachname }}</td></tr>
  <tr><td class="lbl">Eintrittsdatum</td><td>{% if person.eintritt %}{{ person.eintritt|date:"d.m.Y" }}{% else %}–{% endif %}</td></tr>
  <tr><td class="lbl">Datum der Ausgabe</td><td>{{ protokoll.datum|date:"d.m.Y" }}</td></tr>
  {% if leihe %}
  <tr><td class="lbl">Rückgabe bis</td><td>{{ leihe.rueckgabe_bis|date:"d.m.Y"|default:"–" }}</td></tr>
  <tr><td class="lbl">Zweck</td><td>{{ leihe.zweck|default:"–" }}</td></tr>
  <tr><td class="lbl">Leihnummer</td><td>{{ leihnummer|default:"–" }}</td></tr>
  {% endif %}
  <tr><td class="lbl">Ausgabe durch</td><td>{{ firmenname }}, {{ bearbeiter|default:"–" }}</td></tr>
</table>

<h2>2. Ausgegebene Hardware</h2>
<table class="hardware">
  <thead><tr class="kopf">
    <th>Gerät / Gerätename</th><th>Seriennummer</th><th>Zustand</th>
    <th>Zubehör komplett</th><th>Mitgeliefertes Zubehör, Bemerkung</th>
  </tr></thead>
  <tbody>
  {% for p in positionen %}
  <tr>
    <td>{{ p.bezeichnung }}{% if p.geraetename %} / {{ p.geraetename }}{% endif %}</td>
    <td>{{ p.seriennummer|default:"ohne" }}</td>
    <td>{{ p.zustand_ausgabe|default:"–" }}</td>
    <td>{{ p.zubehoer_text }}</td>
    <td>{{ p.ausgabe_text|default:"–" }}</td>
  </tr>
  {% endfor %}
  <tr class="leer"><td></td><td></td><td></td><td></td><td></td></tr>
  <tr class="leer"><td></td><td></td><td></td><td></td><td></td></tr>
  <tr class="leer"><td></td><td></td><td></td><td></td><td></td></tr>
  <tr class="leer"><td></td><td></td><td></td><td></td><td></td></tr>
  </tbody>
</table>
<p class="hinweis">Zustandsstufen: 1 = neuwertig, 2 = gut, normale Gebrauchsspuren, 3 = deutliche Spuren, funktionsfähig, 4 = eingeschränkt nutzbar. Vorhandene Vorschäden sind bei der Ausgabe zu erfassen, damit sie bei der Rückgabe nicht dem Nutzer zugerechnet werden.</p>

<h2>3. Zugänge und Zugangsmittel</h2>
{% if leihe %}
<p>Bei einer Leihe werden keine Zugänge ausgegeben.</p>
{% else %}
<table class="hardware">
  <thead><tr class="kopf">
    <th>Zugang / Zugangsmittel</th><th>ausgegeben</th><th>nicht zutreffend</th><th>Bemerkung, Kennung</th>
  </tr></thead>
  <tbody>
  {% for punkt in checkliste %}
  <tr>
    <td>{{ punkt.text }}</td>
    <td class="kreuz">{% if punkt.wert == 1 %}&#9746;{% else %}&#9744;{% endif %}</td>
    <td class="kreuz">{% if punkt.wert == 0 %}&#9746;{% else %}&#9744;{% endif %}</td>
    <td>{{ punkt.bemerkung }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}

<h2>4. Nutzungsbedingungen</h2>
{% for absatz in nutzung %}<p>{{ absatz }}</p>{% endfor %}

<h2>5. Erklärungen</h2>
{% for absatz in erklaerung %}<p>{{ absatz }}</p>{% endfor %}

<div class="kasten">
  <h2 class="imkasten">6. Elektronische Unterzeichnung</h2>
  {% for absatz in unterzeichnung %}<p{% if forloop.first %} class="fett"{% endif %}>{{ absatz }}</p>{% endfor %}
</div>
""" + _UNTERSCHRIFT + _ANLAGEN


_HTML_RUECKNAHME = _KOPF + """
<h1 class="titel">{{ titel }}</h1>
<p>{{ anrede_satz }},</p>
<p>hiermit bestätigen wir die Rücknahme der nachfolgend aufgeführten Hardware.{% if grundlage %} {{ grundlage }}{% endif %}</p>

<h2>1. Angaben zur Rückgabe</h2>
<table class="daten">
  <tr><td class="lbl">Name des Mitarbeiters</td><td>{{ person.vorname }} {{ person.nachname }}</td></tr>
  <tr><td class="lbl">Eintrittsdatum</td><td>{% if person.eintritt %}{{ person.eintritt|date:"d.m.Y" }}{% else %}–{% endif %}</td></tr>
  <tr><td class="lbl">Letzter Arbeitstag</td><td>{% if person.austritt %}{{ person.austritt|date:"d.m.Y" }}{% else %}–{% endif %}</td></tr>
  <tr><td class="lbl">Datum der Rückgabe</td><td>{{ protokoll.datum|date:"d.m.Y" }}</td></tr>
  <tr><td class="lbl">Bezug</td><td>{% for b in bezug %}{{ b }}{% if not forloop.last %}<br>{% endif %}{% endfor %}</td></tr>
  <tr><td class="lbl">Rücknahme durch</td><td>{{ firmenname }}, {{ bearbeiter|default:"–" }}</td></tr>
</table>

<h2>2. Zurückgegebene Hardware</h2>
<table class="hardware">
  <thead><tr class="kopf">
    <th>Gerät / Gerätename</th><th>Seriennummer</th><th>Zustand bei Ausgabe</th>
    <th>Zustand bei Rückgabe</th><th>Zubehör komplett</th><th>Bemerkung, festgestellte Mängel</th>
  </tr></thead>
  <tbody>
  {% for p in positionen %}
  <tr>
    <td>{{ p.bezeichnung }}{% if p.geraetename %} / {{ p.geraetename }}{% endif %}</td>
    <td>{{ p.seriennummer|default:"ohne" }}</td>
    <td>{{ p.zustand_ausgabe|default:"–" }}</td>
    <td>{{ p.zustand_rueckgabe|default:"–" }}</td>
    <td>{{ p.zubehoer_text }}</td>
    <td>{{ p.maengel_text|default:"keine Mängel" }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>
<p class="hinweis">Zustandsstufen wie im Ausgabeprotokoll: 1 = neuwertig, 2 = gut, normale Gebrauchsspuren, 3 = deutliche Spuren, funktionsfähig, 4 = eingeschränkt nutzbar. Fehlendes Zubehör und Mängel werden in der Spalte Bemerkung erfasst.</p>

<h2>3. Prüfpunkte IT-Offboarding</h2>
<table class="hardware">
  <thead><tr class="kopf">
    <th>Prüfpunkt</th><th>erledigt</th><th>nicht zutreffend</th><th>Datum, Kürzel, Bemerkung</th>
  </tr></thead>
  <tbody>
  {% for punkt in offboarding %}
  <tr>
    <td>{{ punkt.text }}</td>
    <td class="kreuz">{% if punkt.status == "erledigt" %}&#9746;{% else %}&#9744;{% endif %}</td>
    <td class="kreuz">{% if punkt.status == "nicht_zutreffend" %}&#9746;{% else %}&#9744;{% endif %}</td>
    <td>{{ punkt.zeile }}</td>
  </tr>
  {% endfor %}
  </tbody>
</table>

<h2>4. Festgestellte Mängel und offene Punkte</h2>
{% if maengel_liste %}
<ul>{% for m in maengel_liste %}<li>{{ m }}</li>{% endfor %}</ul>
{% else %}
<p>Keine. Die Hardware wurde vollständig mit Zubehör und im bei Ausgabe dokumentierten Zustand zurückgegeben.</p>
{% endif %}

<h2>5. Erklärungen</h2>
{% for absatz in erklaerung %}<p>{{ absatz }}</p>{% endfor %}

<div class="kasten">
  <h2 class="imkasten">6. Elektronische Unterzeichnung</h2>
  {% for absatz in unterzeichnung %}<p{% if forloop.first %} class="fett"{% endif %}>{{ absatz }}</p>{% endfor %}
</div>
""" + _UNTERSCHRIFT + _ANLAGEN


# --- Satzbild (FRM-001 „Satzbild“, N-09) --------------------------------------

_CSS = """
@page {
  size: A4;
  margin: 16mm 16mm 18mm 20mm;
  @bottom-left { content: "__FUSSZEILE__"; font-size: 8pt; color: #444; font-family: Archivo; font-stretch: condensed; }
  @bottom-right { content: "Seite " counter(page) " von " counter(pages); font-size: 8pt; color: #444; font-family: Archivo; font-stretch: condensed; }
}
* { box-sizing: border-box; }
body { font-family: Archivo, "DejaVu Sans", sans-serif; font-stretch: condensed; font-size: 9.5pt; color: #000; line-height: 1.35; }
p { margin: 3pt 0; }
p.fett { font-weight: 700; }
h1 { font-size: 13pt; margin: 10pt 0 4pt 0; font-weight: 700; }
h2 { font-size: 10.5pt; margin: 11pt 0 3pt 0; font-weight: 700; color: #B90808; }
.falz { position: fixed; left: -12mm; width: 5mm; border-top: 0.5pt solid #777; }
.falz.f1 { top: 87mm; } .falz.f2 { top: 132.5mm; } .falz.f3 { top: 192mm; }
.logo { position: absolute; top: -6mm; right: 0; max-height: 14mm; max-width: 45mm; }
.briefkopf { width: 100%; border-collapse: collapse; margin: 8mm 0 4mm 0; }
.briefkopf td { vertical-align: top; padding: 0; }
.briefkopf .links { width: 58%; padding-right: 8mm; }
.absender { font-size: 7.5pt; text-decoration: underline; margin-bottom: 4pt; }
.empfaenger { font-size: 9.5pt; }
.kopf-tabelle { border-collapse: collapse; font-size: 9pt; }
.kopf-tabelle td { padding: 0.5pt 6pt 0.5pt 0; }
.kopf-tabelle td.lbl { color: #444; }
table.daten { width: 100%; border-collapse: collapse; margin: 3pt 0 6pt 0; }
table.daten td { border: 0.5pt solid #bbb; padding: 2.5pt 5pt; }
table.daten td.lbl { font-weight: 700; width: 35%; }
table.hardware { width: 100%; border-collapse: collapse; margin: 3pt 0 4pt 0; }
table.hardware thead { display: table-header-group; }
table.hardware th, table.hardware td { border: 0.5pt solid #bbb; padding: 2.5pt 4pt; font-size: 8.5pt; text-align: left; vertical-align: top; }
table.hardware tr.kopf th { background: #e8e8e8; font-weight: 700; }
table.hardware tr.leer td { height: 12pt; }
td.kreuz { text-align: center; font-family: "DejaVu Sans", sans-serif; }
p.hinweis { font-size: 7.5pt; color: #333; margin: 2pt 0 6pt 0; }
.kasten { background: #FEEBEB; padding: 6pt 9pt; margin: 8pt 0; }
.kasten h2.imkasten { margin: 0 0 3pt 0; }
table.unterschrift { width: 100%; border-collapse: collapse; margin-top: 14pt; page-break-inside: avoid; }
table.unterschrift .feld { width: 50%; padding: 0 10pt 0 0; vertical-align: bottom; }
table.unterschrift .datum { min-height: 14pt; font-size: 8.5pt; }
table.unterschrift .zeile { border-bottom: 0.5pt solid #000; height: 4pt; }
table.unterschrift .rolle { color: #333; font-size: 8pt; margin-top: 2pt; }
.anlagen { page-break-before: always; }
.anhang { margin: 8pt 0; page-break-inside: avoid; }
.anhang img { max-width: 100%; max-height: 230mm; }
.unterschrift-bild { font-size: 8pt; color: #333; margin-top: 2pt; }
.pruefprotokoll { page-break-before: always; }
.pruefprotokoll table { table-layout: fixed; }
.pruefprotokoll td { overflow-wrap: anywhere; }
"""


# --- Daten für die Vorlage ----------------------------------------------------

def _firma() -> dict:
    """Firmendaten aus den Einstellungen (F-122)."""
    from stammdaten.models import Einstellungen
    e = Einstellungen.aktuelles()
    logo = ""
    if e.logo:
        try:
            logo = Path(e.logo.path).as_uri()
        except (ValueError, NotImplementedError):
            logo = ""
    return {
        "firmenname": e.firmenname, "absenderzeile": e.absenderzeile,
        "telefon": e.telefon, "email_it": e.email_it, "logo": logo, "einstellungen": e,
    }


def _absaetze(text: str, firmenname: str) -> list[str]:
    """Ein Text besteht aus Absätzen, getrennt durch eine Leerzeile (FRM-001 Abschnitt 4)."""
    text = (text or "").replace("{Firmenname}", firmenname).replace("\r\n", "\n")
    return [teil.strip() for teil in text.split("\n\n") if teil.strip()]


def _maengel_der_position(p: dict) -> list[str]:
    """Was an diesem Gerät festgestellt wurde (FRM-002, Abschnitte 2 und 4)."""
    teile = []
    if p.get("bemerkung"):
        teile.append(p["bemerkung"])
    if p.get("zustand_rueckgabe") is not None and p.get("zubehoer_komplett") is False:
        teile.append("Zubehör nicht komplett")
    ausgabe, rueckgabe = p.get("zustand_ausgabe"), p.get("zustand_rueckgabe")
    if ausgabe and rueckgabe and int(rueckgabe) > int(ausgabe):
        teile.append(f"Zustand schlechter als bei Ausgabe ({ausgabe} → {rueckgabe})")
    return teile


def _positionen(protokoll: Protokoll) -> list[dict]:
    """Die Geräte des Protokolls; alte Datensätze ohne Positionen zeigen ihr Gerät."""
    from .services import position_aus_gerat
    roh = protokoll.positionen or [position_aus_gerat(protokoll.geraet)]
    ergebnis = []
    for p in roh:
        zubehoer = p.get("zubehoer_komplett")
        teile = [t for t in (p.get("standardzubehoer", ""), p.get("bemerkung", "")) if t]
        ergebnis.append({
            **p,
            "zubehoer_text": "–" if zubehoer is None else ("Ja" if zubehoer else "Nein"),
            "ausgabe_text": ", ".join(teile),
            "maengel_text": ", ".join(_maengel_der_position(p)),
        })
    return ergebnis


def _checkliste_eintraege(protokoll: Protokoll) -> list[dict]:
    werte = protokoll.checkliste or {}
    bemerkungen = protokoll.checkliste_bemerkung or {}
    return [
        {"text": text, "wert": werte.get(schluessel), "bemerkung": bemerkungen.get(schluessel, "")}
        for schluessel, text in Protokoll.CHECKLISTE_PUNKTE
    ]


def _offboarding_eintraege(protokoll: Protokoll) -> list[dict]:
    werte = protokoll.offboarding or {}
    eintraege = []
    for schluessel, text in Protokoll.OFFBOARDING_PUNKTE:
        wert = werte.get(schluessel)
        if wert is True:
            wert = {"status": "erledigt"}
        elif wert is False:
            wert = {"status": "nicht_zutreffend"}
        wert = wert if isinstance(wert, dict) else {}
        status = wert.get("status", "")
        vorn = " ".join(t for t in (wert.get("datum", ""), wert.get("kuerzel", "")) if t)
        hinten = {"erledigt": "erledigt", "in_klaerung": "in Klärung"}.get(status, "")
        zeile = f"{vorn}: {hinten}" if vorn and hinten else (hinten or vorn)
        if wert.get("bemerkung") and wert.get("bemerkung") != hinten:
            zeile = f"{zeile}, {wert['bemerkung']}" if zeile else wert["bemerkung"]
        eintraege.append({"text": text, "status": status, "zeile": zeile, "bemerkung": wert.get("bemerkung", "")})
    return eintraege


def _anhaenge(protokoll: Protokoll) -> list[dict]:
    """Fotos als Anlage (F-134); der Pfad kommt aus der Dateiablage."""
    from django.core.files.storage import default_storage

    namen = {
        p.get("inventarnummer"): p.get("geraetename") or p.get("bezeichnung", "")
        for p in protokoll.positionen or []
    }
    ergebnis = []
    for anhang in protokoll.anhaenge_liste():
        pfad = anhang.get("pfad")
        if not pfad:
            continue
        eintrag = {**anhang, "url": "", "geraet_name": namen.get(anhang.get("inventarnummer"), "")}
        try:
            if default_storage.exists(pfad) and not pfad.lower().endswith(".heic"):
                eintrag["url"] = Path(default_storage.path(pfad)).as_uri()
        except (OSError, NotImplementedError, ValueError):
            pass
        ergebnis.append(eintrag)
    return ergebnis


def _anrede(person) -> str:
    """„h“, „f“ oder leer; ältere Daten können das ausgeschriebene Wort tragen."""
    return str(getattr(person, "anrede", "") or "").lower()[:1]


def _bezug_rueckgabe(protokoll: Protokoll) -> tuple[list[str], str]:
    """Bezug und Einleitung bei einer Rücknahme (FRM-002 Abschnitt 1)."""
    from .models import Protokoll as P
    nummern = []
    for p in protokoll.positionen or []:
        if p.get("ausgabe_protokoll"):
            nummern.append(p["ausgabe_protokoll"])
    if protokoll.rueckgabe_zu_protokoll_id and protokoll.rueckgabe_zu_protokoll.nr not in nummern:
        nummern.append(protokoll.rueckgabe_zu_protokoll.nr)
    grundlagen = list(P.objects.filter(nr__in=set(nummern)).order_by("datum", "id"))
    bezug = [f"Ausgabeprotokoll {g.nr} vom {g.datum.strftime('%d.%m.%Y')}" for g in grundlagen]
    daten = [g.datum.strftime("%d.%m.%Y") for g in grundlagen]
    ohne = any(not p.get("ausgabe_protokoll") for p in protokoll.positionen or [])
    if ohne or not bezug:
        bezug.append("Altbestand ohne Protokoll")
    if not daten:
        return bezug, ""
    if len(daten) == 1:
        return bezug, f"Grundlage ist das Ausgabeprotokoll vom {daten[0]}."
    return bezug, f"Grundlage sind die Ausgabeprotokolle vom {', '.join(daten[:-1])} und {daten[-1]}."


def _maengel_liste(positionen: list[dict], offboarding: list[dict]) -> list[str]:
    """FRM-002 Abschnitt 4: zuerst Mängel und fehlendes Zubehör je Gerät, dann „in Klärung“."""
    liste = []
    for p in positionen:
        name = p.get("geraetename") or p.get("bezeichnung", "")
        for mangel in _maengel_der_position(p):
            liste.append(f"{name}: {mangel}")
    for punkt in offboarding:
        if punkt["status"] == "in_klaerung":
            zusatz = punkt["bemerkung"] if punkt["bemerkung"] != "in Klärung" else ""
            liste.append(f"{punkt['text']}: in Klärung{', ' + zusatz if zusatz else ''}")
    return liste


def _titel(protokoll: Protokoll) -> str:
    if protokoll.art == Protokoll.ART_RUECKNAHME:
        art = "Offboarding" if getattr(protokoll.person, "austritt", None) else "Rückgabe"
        return f"Rücknahmeprotokoll Hardware ({art})"
    if protokoll.leihe_id:
        return "Ausgabeprotokoll Hardware (Leihe)"
    return "Ausgabeprotokoll Hardware (Onboarding)"


def _render_inhalt(protokoll: Protokoll) -> str:
    """Das HTML des Protokolls aus dem aktuellen Stand (noch nicht eingefroren)."""
    firma = _firma()
    e = firma["einstellungen"]
    texte = protokoll.texte or {}
    ausgabe = protokoll.art == Protokoll.ART_AUSGABE
    person = protokoll.person
    anrede = _anrede(person)
    positionen = _positionen(protokoll)
    offboarding = _offboarding_eintraege(protokoll)
    name = firma["firmenname"]
    bezug, grundlage = ([], "") if ausgabe else _bezug_rueckgabe(protokoll)
    leihnummer = ""
    if protokoll.leihe_id:
        leihnummer = protokoll.leihe.nr or f"L-{protokoll.leihe_id:04d}"
    erstes = positionen[0] if positionen else {}
    kontext = {
        "protokoll": protokoll,
        "person": person,
        "bearbeiter": protokoll.bearbeiter,
        "anrede_zeile": {"h": "Herrn", "f": "Frau"}.get(anrede, ""),
        "anrede_satz": {
            "h": f"Sehr geehrter Herr {person.nachname}",
            "f": f"Sehr geehrte Frau {person.nachname}",
        }.get(anrede, f"Guten Tag {person.vorname} {person.nachname}".strip()),
        "anschrift": protokoll.empfaenger_anschrift,
        "dokument": "WMC-IT-FRM-001" if ausgabe else "WMC-IT-FRM-002",
        "titel": _titel(protokoll),
        "leihe": protokoll.leihe if protokoll.leihe_id else None,
        "leihnummer": leihnummer,
        "positionen": positionen,
        "checkliste": _checkliste_eintraege(protokoll),
        "offboarding": offboarding,
        "maengel_liste": _maengel_liste(positionen, offboarding),
        "bezug": bezug,
        "grundlage": grundlage,
        "anhaenge": _anhaenge(protokoll),
        "geraetename_kurz": erstes.get("geraetename") or erstes.get("bezeichnung", ""),
        "anlass": "Ausgabe" if ausgabe else "Rückgabe",
        "rolle_links": "Empfängers" if ausgabe else "Rückgebenden",
        "nutzung": _absaetze(texte.get("nutzung", e.nutzungsbedingungen_ausgabe), name),
        "erklaerung": _absaetze(texte.get("erklaerung", e.erklaerungen_ausgabe if ausgabe else e.erklaerungen_ruecknahme), name),
        "unterzeichnung": _absaetze(texte.get("unterzeichnung", e.unterzeichnung_ausgabe if ausgabe else e.unterzeichnung_ruecknahme), name),
        **{k: firma[k] for k in ("firmenname", "absenderzeile", "telefon", "email_it", "logo")},
    }
    return Template(_HTML_AUSGABE if ausgabe else _HTML_RUECKNAHME).render(Context(kontext))


def inhalt_einfrieren(protokoll: Protokoll) -> tuple[str, str]:
    """F-135: Inhalt fest schreiben. Liefert HTML und Hash des PDF zu diesem Inhalt."""
    html = protokoll.html_eingefroren or _render_inhalt(protokoll)
    return html, hashlib.sha256(_html_zu_pdf(protokoll, html)).hexdigest()


def _fusszeile(protokoll: Protokoll) -> str:
    if protokoll.art == Protokoll.ART_AUSGABE:
        return f"WMC-IT-FRM-001 Ausgabeprotokoll, Version {protokoll.fassung or '1.1'}"
    return f"WMC-IT-FRM-002 Rücknahmeprotokoll, Version {protokoll.fassung or '1.1'}"


def _html_zu_pdf(protokoll: Protokoll, inhalt: str) -> bytes:
    from weasyprint import HTML

    css = _CSS.replace("__FUSSZEILE__", _fusszeile(protokoll))
    dokument = (
        "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
        f"<title>Protokoll {html_modul.escape(protokoll.nr)}</title>"
        f"<style>{_schrift_css()}</style><style>{css}</style></head><body>{inhalt}</body></html>"
    )
    puffer = io.BytesIO()
    # base_url: Die Schrift steht in archivo.css relativ zum eigenen Ordner.
    HTML(string=dokument, base_url=_STATIC_FONTS.as_uri() + "/").write_pdf(puffer)
    return puffer.getvalue()


def _zeit(wert) -> str:
    return timezone.localtime(wert).strftime("%d.%m.%Y %H:%M") if wert else ""


def _mit_vermerken(protokoll: Protokoll, inhalt: str) -> str:
    """Über der Linie steht das Datum oder der Signaturvermerk (FRM-001 Unterschriftenblock)."""
    vermerke = {a.art: a for a in protokoll.aufzeichnungen_liste()}
    bearbeiter = vermerke.get("bearbeiter")
    gegen = vermerke.get("gegenzeichnung")
    links, rechts = "", "i.A."
    if gegen is not None:
        links = html_modul.escape(f"Elektronisch signiert: {gegen.name}, {_zeit(gegen.zeitpunkt)}, {gegen.nachweisnummer}")
    if bearbeiter is not None:
        rechts = "i.A. " + html_modul.escape(f"Elektronisch signiert: {bearbeiter.name}, {_zeit(bearbeiter.zeitpunkt)}, {bearbeiter.nachweisnummer}")
    return inhalt.replace(_VERMERK_EMPFAENGER, links).replace(_VERMERK_BEARBEITER, rechts)


def _pruefprotokoll_seite(protokoll: Protokoll) -> str:
    """Letzte Seite: je Signatur alle Angaben aus F-137."""
    e = html_modul.escape
    zeilen = []
    for a in protokoll.aufzeichnungen_liste():
        art = "Signatur des Bearbeiters" if a.art == "bearbeiter" else "Gegenzeichnung"
        zeilen.append(
            f'<h2>{art}</h2><table class="daten">'
            f'<tr><td class="lbl">Name</td><td>{e(a.name)}</td></tr>'
            f'<tr><td class="lbl">E-Mail</td><td>{e(a.email)}</td></tr>'
            f'<tr><td class="lbl">Zeitpunkt</td><td>{_zeit(a.zeitpunkt)} Uhr</td></tr>'
            f'<tr><td class="lbl">Nachweisnummer</td><td>{e(a.nachweisnummer)}</td></tr>'
            f'<tr><td class="lbl">Identifizierungsmerkmal</td><td>{e(a.identifikationsmerkmal)}</td></tr>'
            f'<tr><td class="lbl">IP-Adresse</td><td>{e(a.ip_adresse)}</td></tr>'
            f'<tr><td class="lbl">Hashwert (SHA-256)</td><td>{e(a.hashwert)}</td></tr>'
            "</table>"
        )
    if not zeilen:
        zeilen.append("<p>Noch keine Signatur.</p>")
    return (
        '<div class="pruefprotokoll"><h1>Prüfprotokoll</h1>'
        f"<p>Protokoll {e(protokoll.nr)}, {e(_titel(protokoll))}.</p>"
        + "".join(zeilen)
        + '<p class="hinweis">Der Hashwert bezieht sich auf den Inhalt des Protokolls ohne diese Seite. '
        "Das Siegel (PAdES) macht jede spätere Änderung der Datei erkennbar.</p></div>"
    )


def _offene_punkte(protokoll: Protokoll) -> list[str]:
    offene = protokoll.checkliste_unbeantwortet()
    if protokoll.art == Protokoll.ART_RUECKNAHME:
        offene = offene + protokoll.offboarding_unbeantwortet()
    return offene


def pdf_bauen(protokoll: Protokoll) -> bytes:
    """Das Protokoll ohne Prüfprotokoll (F-130, F-132, F-133, F-134).

    F-132, F-133: Das PDF entsteht erst, wenn jeder Punkt beantwortet ist.
    """
    offene = _offene_punkte(protokoll)
    if offene:
        raise GeratFehler(
            "Die Checkliste ist noch nicht vollständig beantwortet "
            f"({len(offene)} Punkte offen); das PDF entsteht erst danach."
        )
    html = protokoll.html_eingefroren or _render_inhalt(protokoll)
    return _html_zu_pdf(protokoll, _mit_vermerken(protokoll, html))


def pdf_fertig_bauen(protokoll: Protokoll, *, versiegeln: bool | None = None) -> bytes:
    """Protokoll mit Prüfprotokoll als letzter Seite (F-137), versiegelt nach der letzten Signatur (F-138).

    Lässt sich das Siegel nicht anbringen, entsteht ein Fehler: Ein abgeschlossenes
    Protokoll ohne Siegel darf es nicht geben (F-138).
    """
    offene = _offene_punkte(protokoll)
    if offene:
        raise GeratFehler(
            "Die Prüfpunkte sind noch nicht vollständig beantwortet "
            f"({len(offene)} Punkte offen); das PDF entsteht erst danach."
        )
    html = protokoll.html_eingefroren or _render_inhalt(protokoll)
    html = _mit_vermerken(protokoll, html) + _pruefprotokoll_seite(protokoll)
    pdf_bytes = _html_zu_pdf(protokoll, html)
    if versiegeln is None:
        versiegeln = protokoll.gegenzeichnung_signiert_am is not None
    if not versiegeln:
        return pdf_bytes
    from . import siegel as siegel_modul
    versiegelt = siegel_modul.siegel_anwenden(pdf_bytes)
    if versiegelt is None:
        raise GeratFehler("Das Siegel konnte nicht angebracht werden. Bitte wenden Sie sich an die IT.")
    return versiegelt


def dateiname_protokoll(protokoll: Protokoll, typ: str = "application/pdf") -> str:
    """F-139: ``WMC_<Ausgabeprotokoll oder Ruecknahmeprotokoll>_<Nachname>_<Vorname>_<TT.MM.JJJJ>.pdf``."""
    person = protokoll.person
    name = (person.nachname or "").replace(" ", "_")
    vorname = (person.vorname or "").replace(" ", "_")
    datum = protokoll.datum.strftime("%d.%m.%Y")
    # Beim Papierweg kann der Scan auch ein Bild sein (F-22).
    endung = {"image/jpeg": ".jpg", "image/png": ".png", "image/heic": ".heic"}.get(typ, ".pdf")
    if protokoll.art == Protokoll.ART_AUSGABE:
        return f"WMC_Ausgabeprotokoll_{name}_{vorname}_{datum}{endung}"
    return f"WMC_Ruecknahmeprotokoll_{name}_{vorname}_{datum}{endung}"
