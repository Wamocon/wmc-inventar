"""Kennzahlen und Arbeitslisten für die Übersicht / und /api/kennzahlen.

F-100 Kennzahlen als IST/Gesamt, F-101 Delta zum Vortag, F-102 Arbeitslisten,
F-104 Inventarwert, F-105 Schnittstelle. M7 Teil 3 (A-0907).
TESTSCHNITTSTELLE Kapitel 3, 4 und 5.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from konten.zeit import jetzt_aware
from stammdaten.models import Ort, Zaehlerstand

from .models import Gerat, Leihe, Protokoll


def _aktive_geraete():
    """Alle Geräte außer Ausgemustert (F-100 „aktive Geräte“)."""
    return Gerat.objects.exclude(status=Gerat.STATUS_AUSGEMUSTERT)


def _heute() -> date:
    """Heute nach der Uhr der Anwendung (TESTSCHNITTSTELLE 1.2)."""
    return jetzt_aware().date()


def _ueberfaellige_leihen(heute: date):
    """Überfällig: Frist vorbei und das Gerät noch nicht zurück (F-36, F-100).

    Ein Gerät, das nicht mehr verliehen ist, ist auch nicht überfällig, selbst
    wenn die Leihe nach einer Rückgabe am Gerät noch „ausgegeben“ heißt.
    """
    return Leihe.objects.filter(
        rueckgabe_bis__lt=heute,
        status=Leihe.STATUS_AUSGEGEBEN,
        gerat__status=Gerat.STATUS_VERLIEHEN,
    )


def _arbeitsplaetze_unvollstaendig():
    """Arbeitsplätze mit Soll-Ist „unvollständig“ und was fehlt (F-62, F-100, F-102)."""
    from .services import soll_ist_abgleich

    ergebnis = []
    for ort in Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ).order_by("kennung"):
        abgleich = soll_ist_abgleich(ort)
        if abgleich["ergebnis"] == "unvollstaendig":
            ergebnis.append((ort, abgleich["fehlend"]))
    return ergebnis


def arbeitsplaetze_vollstaendig_zahl() -> int:
    """Plätze, deren Soll erfüllt ist; auch „mehr als Soll“ fehlt nichts (F-100)."""
    return Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ).count() - len(_arbeitsplaetze_unvollstaendig())


# --- Kennzahlen (F-100) ------------------------------------------------------

# data-id, Titel, ist(), gesamt(). Nur mit `ist`: ueberfaellig,
# anfragen-offen, garantie-30-tage, unterschriften-offen. Mit gesamt:
# in-benutzung, arbeitsplaetze-vollstaendig, verliehen, geprueft.
_KENNZAHLEN_DEF = (
    ("in-benutzung", "Geräte in Benutzung",
     lambda heute: _aktive_geraete().filter(status=Gerat.STATUS_IN_BENUTZUNG).count(),
     lambda heute: _aktive_geraete().count()),
    ("ueberfaellig", "Überfällige Leihen",
     lambda heute: _ueberfaellige_leihen(heute).count(),
     None),
    ("anfragen-offen", "Offene Leihanfragen",
     lambda heute: Leihe.objects.filter(status=Leihe.STATUS_ANGEFRAGT).count(),
     None),
    ("garantie-30-tage", "Garantie läuft ab",
     lambda heute: _aktive_geraete().filter(
         garantie_bis__gte=heute, garantie_bis__lte=heute + timedelta(days=30)
     ).count(),
     None),
    ("unterschriften-offen", "Unterschriften offen",
     lambda heute: Protokoll.objects.filter(
         stand__in=[
             Protokoll.STAND_SCAN_OFFEN,
             Protokoll.STAND_BEARBEITER_OFFEN,
             Protokoll.STAND_GEGENZEICHNUNG_OFFEN,
         ]
     ).count(),
     None),
    ("arbeitsplaetze-vollstaendig", "Arbeitsplätze vollständig",
     lambda heute: arbeitsplaetze_vollstaendig_zahl(),
     lambda heute: Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ).count()),
    ("verliehen", "Verliehene Geräte",
     lambda heute: _aktive_geraete().filter(status=Gerat.STATUS_VERLIEHEN).count(),
     lambda heute: _aktive_geraete().filter(leihpool=True).count()),
    ("geprueft", "Geprüfte Geräte",
     lambda heute: _aktive_geraete().filter(zuletzt_geprueft_am__isnull=False).count(),
     lambda heute: _aktive_geraete().count()),
)


def kennzahlen(heute: date | None = None) -> list[dict]:
    """Die acht Kennzahlen aus F-100 mit ihren data-id (Kapitel 4)."""
    if heute is None:
        heute = _heute()
    ergebnis = []
    for data_id, titel, ist_fn, gesamt_fn in _KENNZAHLEN_DEF:
        eintrag = {
            "data_id": data_id,
            "titel": titel,
            "ist": ist_fn(heute),
            "gesamt": gesamt_fn(heute) if gesamt_fn else None,
        }
        ergebnis.append(eintrag)
    return ergebnis


# --- Delta (F-101) -----------------------------------------------------------


def delta_zum_vortag(heute: date | None = None) -> dict | None:
    """F-101: Delta zum Vortag aus den Zählerständen.

    None, wenn für den Vortag oder den heutigen Tag kein Zählerstand steht.
    Sonst {data_id: Zahl} für jede Kennzahl, die in beiden Zählerständen
    eine ist trägt.

    Wenn heute None ist, wird das Datum des letzten Zählerstands verwendet.
    """
    if heute is None:
        letzter = Zaehlerstand.objects.order_by("-stichtag").first()
        if letzter is None:
            return None
        heute = letzter.stichtag
    vortag = heute - timedelta(days=1)
    alt = Zaehlerstand.objects.filter(stichtag=vortag).first()
    neu = Zaehlerstand.objects.filter(stichtag=heute).first()
    if alt is None or neu is None:
        return None
    delta = {}
    alt_wert = alt.kennzahlen or {}
    neu_wert = neu.kennzahlen or {}
    for data_id in {*alt_wert, *neu_wert}:
        ist_neu = (neu_wert.get(data_id) or {}).get("ist")
        ist_alt = (alt_wert.get(data_id) or {}).get("ist")
        if ist_neu is not None and ist_alt is not None:
            delta[data_id] = ist_neu - ist_alt
    return delta


# --- Arbeitslisten (F-102, F-36, F-88, F-133) --------------------------------
# Reihenfolge und data-id gemäß TESTSCHNITTSTELLE Kapitel 4.


def _leihen_select():
    return Leihe.objects.select_related("gerat", "person", "kat")


def ueberfaellig(heute: date | None = None) -> list[dict]:
    """Überfällige Leihen (F-36): Rückgabedatum überschritten, Status „ausgegeben“."""
    if heute is None:
        heute = _heute()
    leihen = _ueberfaellige_leihen(heute).select_related(
        "gerat", "person", "kat"
    ).order_by("rueckgabe_bis", "id")
    zeilen = []
    for leihe in leihen:
        gerat = leihe.gerat
        zeilen.append({
            "nr": leihe.nr,
            "gerat": gerat.inventarnummer if gerat else (leihe.kat.name if leihe.kat else ""),
            "person": f"{leihe.person.vorname} {leihe.person.nachname}".strip() if leihe.person else "",
            "frist": leihe.rueckgabe_bis,
            "link": f"/geraete/{gerat.inventarnummer}/" if gerat else "/verleih/",
        })
    return zeilen


def offene_anfragen(heute: date | None = None) -> list[dict]:
    """Offene Leihanfragen: Status „angefragt“."""
    leihen = _leihen_select().filter(
        status=Leihe.STATUS_ANGEFRAGT
    ).order_by("zeitpunkt", "id")
    zeilen = []
    for leihe in leihen:
        gerat = leihe.gerat
        zeilen.append({
            "nr": leihe.nr,
            "gerat": gerat.inventarnummer if gerat else (leihe.kat.name if leihe.kat else ""),
            "person": f"{leihe.person.vorname} {leihe.person.nachname}".strip() if leihe.person else "",
            "zweck": leihe.zweck or "",
            # F-102: Sprung ins Detail ist die Entscheidung über diese Anfrage (nur Admin,
            # die Übersicht nimmt für den Leser den Sprung aufs Gerät).
            "link": f"/geraete/verleih/{leihe.pk}/genehmigen/",
            "link_leser": f"/geraete/{gerat.inventarnummer}/" if gerat else "",
        })
    return zeilen


def arbeitsplaetze_unvollstaendig(heute: date | None = None) -> list[dict]:
    """Unvollständige Arbeitsplätze (F-102): Soll-Ist fehlt etwas (Testschnittstelle 5)."""
    return [
        {
            "kennung": ort.kennung,
            "standort": f"{ort.standort} · {ort.raum}".strip(" ·") if ort.standort else "",
            "mangel": "fehlt: " + ", ".join(f"{anzahl} × {kategorie.name}" for kategorie, anzahl in fehlend),
            "link": f"/arbeitsplaetze/{ort.kennung}/",
        }
        for ort, fehlend in _arbeitsplaetze_unvollstaendig()
    ]


def garantie_laeuft_ab(heute: date | None = None) -> list[dict]:
    """Garantie läuft ab: aktive Geräte mit Garantie bis heute + 30 Tage."""
    if heute is None:
        heute = _heute()
    grenze = heute + timedelta(days=30)
    geraete = (
        _aktive_geraete()
        .filter(garantie_bis__gte=heute, garantie_bis__lte=grenze)
        .order_by("garantie_bis", "id")
    )
    return [
        {
            "nr": gerat.inventarnummer,
            "modell": f"{gerat.hersteller} {gerat.modell}".strip(),
            "garantie_bis": gerat.garantie_bis,
            "link": f"/geraete/{gerat.inventarnummer}/",
        }
        for gerat in geraete
    ]


def unterschreibungen_offen(heute: date | None = None) -> list[dict]:
    """Unterschriften offen: Protokolle in einem der drei wartenden Stände (F-22, F-102).

    Liefert jedes nicht abgeschlossene Protokoll mit Sprung ins Protokoll.
    """
    protokolle = (
        Protokoll.objects.filter(stand__in=[
            Protokoll.STAND_SCAN_OFFEN,
            Protokoll.STAND_BEARBEITER_OFFEN,
            Protokoll.STAND_GEGENZEICHNUNG_OFFEN,
        ])
        .select_related("person", "geraet")
        .order_by("nr")
    )
    zeilen = []
    for protokoll in protokolle:
        zeilen.append({
            "nr": protokoll.nr,
            "stand": protokoll.stand_anzeige,
            "person": (
                f"{protokoll.person.vorname} {protokoll.person.nachname}".strip()
                if protokoll.person
                else ""
            ),
            "link": f"/protokolle/{protokoll.nr}/",
        })
    return zeilen


def daten_unvollstaendig(heute: date | None = None) -> list[dict]:
    """Daten unvollständig (F-88): aktive Geräte mit mindestens einer Lücke."""
    geraete = _aktive_geraete().order_by("inventarnummer", "id")
    zeilen = []
    for gerat in geraete:
        # F-88: Auch ein offener Importkonflikt setzt das Gerät auf die Liste.
        luecken = gerat.datenluecken_text()
        if not luecken:
            continue
        zeilen.append({
            "nr": gerat.inventarnummer,
            "modell": f"{gerat.hersteller} {gerat.modell}".strip(),
            "luecken": luecken,
            "link": f"/geraete/{gerat.inventarnummer}/",
        })
    return zeilen


def offene_punkte_in_klaerung(heute: date | None = None) -> list[dict]:
    """Offene Prüfpunkte IT-Offboarding (F-133, Prüfpunkte „in Klärung“).

    Die Offboarding-Werte sind Boolesche Werte (protokoll.py). Ein Punkt
    gilt als offen, solange er nicht abgehackt ist; die Punkte „in Klärung“
    sind die offenen, die noch nicht „erledigt“ sind.
    """
    zeilen = []
    for protokoll in Protokoll.objects.select_related("person", "geraet").order_by("nr"):
        offene = protokoll.offboarding_unbeantwortet()
        if not offene:
            continue
        person = protokoll.person
        zeilen.append({
            "name": (
                f"{person.nachname} {person.vorname}".strip()
                if person
                else (protokoll.geraet.inventarnummer if protokoll.geraet else "")
            ),
            "punkte": offene,
            "link": f"/protokolle/{protokoll.nr}/",
        })
    return zeilen


def austritte(heute: date | None = None) -> list[dict]:
    """Austritte (F-133): Personen mit Austritt, denen Geräte noch zugeordnet sind."""
    person_ids = sorted({
        gerat.person_id
        for gerat in _aktive_geraete()
        if gerat.person_id is not None
    })
    if not person_ids:
        return []
    from stammdaten.models import Person
    personen = (
        Person.objects.filter(austritt__isnull=False, pk__in=person_ids)
        .order_by("austritt", "nachname", "vorname")
    )
    zeilen = []
    for person in personen:
        anzahl_geraete = (
            _aktive_geraete().filter(person_id=person.pk).count()
        )
        if anzahl_geraete == 0:
            continue
        zeilen.append({
            "name": f"{person.nachname} {person.vorname}".strip(),
            "austritt": person.austritt,
            "geraete": anzahl_geraete,
            "link": f"/personen/{person.pk}/",
        })
    return zeilen


# --- Inventarwert (F-104) ----------------------------------------------------


def inventarwert() -> Decimal:
    """Summe der Kaufpreise aller nicht ausgemusterten Geräte."""
    summe = (
        _aktive_geraete()
        .filter(kaufpreis_netto__isnull=False)
        .aggregate(summe=Sum("kaufpreis_netto"))["summe"]
    )
    return Decimal(summe or 0)


# --- Übersicht (Kapitel 4) ---------------------------------------------------

_ARBEITSLISTEN_DEF = (
    ("ueberfaellig", "Überfällige Leihen", ueberfaellig,
     "Keine überfälligen Leihen."),
    ("anfragen", "Offene Leihanfragen", offene_anfragen,
     "Keine offenen Leihanfragen."),
    ("arbeitsplaetze-unvollstaendig", "Unvollständige Arbeitsplätze",
     arbeitsplaetze_unvollstaendig,
     "Alle Arbeitsplätze vollständig."),
    ("garantie", "Garantie läuft ab", garantie_laeuft_ab,
     "Keine ablaufenden Garantien."),
    ("unterschriften-offen", "Unterschriften offen", unterschreibungen_offen,
     "Keine offenen Unterschriften."),
    ("daten-unvollstaendig", "Daten unvollständig", daten_unvollstaendig,
     "Alle Daten vollständig."),
    ("offene-punkte", "Prüfpunkte in Klärung", offene_punkte_in_klaerung,
     "Keine Prüfpunkte in Klärung."),
    ("austritte", "Austritte mit offenen Geräten", austritte,
     "Keine Austritte mit offenen Geräten."),
)


def arbeitslisten(heute: date | None = None) -> list[dict]:
    """Die acht Arbeitslisten (F-102) mit ihren data-id (Kapitel 4)."""
    if heute is None:
        heute = _heute()
    ergebnis = []
    for data_id, titel, quelle, leer_text in _ARBEITSLISTEN_DEF:
        ergebnis.append({
            "data_id": data_id,
            "titel": titel,
            "zeilen": quelle(heute),
            "leer_text": leer_text,
        })
    return ergebnis


def uebersicht(heute: date | None = None) -> dict:
    """Zusammengefasste Werte für /api/kennzahlen (Kapitel 4).

    ``stand`` als ISO-Datum, ``kennzahlen`` als dict keyed by data-id mit
    ist, gesamt (nur wo vorhanden) und delta (Zahl oder null).
    """
    if heute is None:
        heute = _heute()
    delta = delta_zum_vortag(heute) or {}
    kennzahlen_json = {}
    for kz in kennzahlen(heute):
        eintrag = {"ist": kz["ist"]}
        if kz["gesamt"] is not None:
            eintrag["gesamt"] = kz["gesamt"]
        eintrag["delta"] = delta.get(kz["data_id"])
        kennzahlen_json[kz["data_id"]] = eintrag
    return {
        "stand": jetzt_aware().strftime("%Y-%m-%dT%H:%M"),
        "kennzahlen": kennzahlen_json,
    }
