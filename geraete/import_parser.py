"""Parser und Vorschau für den Import (A-0113, F-80 bis F-84, F-86).

Dieser Teil ist reines Rechnen über den Bestand: Datei einlesen,
Spalten und Werte zuordnen, für jede Zeile das Ergebnis (neu,
ergänzt, konflikt, übersprungen) mit Grund bestimmen. Gespeichert
wird hier nichts; das Speichern kommt in Teil 3.

Dateiformate (F-80): .xlsx mit Auswahl von Blatt und Kopfzeile oder
.csv in UTF-8 mit Semikolon oder Komma.
Leer gelten „-“, „?“ und „N.A.“ (F-82).
Zusammenführen (F-84): gleiche Seriennummer oder gleicher Gerätenamen
aus einem anderen Blatt oder einem früheren Import, die Seriennummer
geht vor; innerhalb eines Blatts wird nicht zusammengeführt.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

from openpyxl import load_workbook

from stammdaten.models import Kategorie, Ort, Person

from .models import Gerat

# F-82: gelten als leer
LEER_WERTE = {"-", "?", "N.A.", "n.a.", "NA", "na", ""}

# Zielfelder, denen eine Quellspalte zugeordnet werden kann (F-81).
# Der Wert IGNORIEREN bedeutet „nicht übernehmen“.
IGNORIEREN = "ignorieren"
ZIELFELDER = [
    "Kategorie",
    "Hersteller",
    "Modell",
    "Gerätename",
    "Seriennummer",
    "Person",
    "Arbeitsplatz",
    "Kaufdatum",
    "Kaufpreis netto",
    "Lieferant",
    "Rechnungsnummer",
    "Garantie bis",
    "Notiz",
    IGNORIEREN,
]

# Zielfeld, das je Wert in der Datei einmal zugeordnet wird (F-82).
WERTFELDER = ["Kategorie", "Person", "Arbeitsplatz"]

# Vorschläge über gleichnamige Spalten (F-81), normalisierte Namen.
NAMEN_ZU_ZIEL = {
    "typ": "Kategorie",
    "kategorie": "Kategorie",
    "geraet": "Modell",
    "gerät": "Modell",
    "modell": "Modell",
    "hersteller": "Hersteller",
    "seriennummer": "Seriennummer",
    "sn": "Seriennummer",
    "geraetename": "Gerätename",
    "gerätename": "Gerätename",
    "kennung": "Gerätename",
    "verliehen an ma": "Person",
    "verliehen an": "Person",
    "nutzer": "Person",
    "person": "Person",
    "arbeitsplatz": "Arbeitsplatz",
    "arbeitsplatz (kennung)": "Arbeitsplatz",
    "datum erhalt": "Kaufdatum",
    "datum erhalt.": "Kaufdatum",
    "kaufdatum": "Kaufdatum",
    "kaufpreis netto": "Kaufpreis netto",
    "preis": "Kaufpreis netto",
    "lieferant": "Lieferant",
    "rechnungsnummer": "Rechnungsnummer",
    "rechnung": "Rechnungsnummer",
    "garantie ende": "Garantie bis",
    "garantie": "Garantie bis",
    "garantie bis": "Garantie bis",
    "kommentar": "Notiz",
    "notiz": "Notiz",
}


class ImportFehler(Exception):
    """Fehler beim Einlesen einer Datei (F-80)."""


@dataclass
class Quellspalte:
    """Eine Spalte der hochgeladenen Datei (F-80, F-81)."""

    nr: int                     # 0-basierte Spaltennummer
    name: str                   # Text der Kopfzeile
    beispiel: str = ""          # erster nicht leerer Wert darunter
    ziel: str = IGNORIEREN      # zugeordnetes Zielfeld

    @staticmethod
    def vorschlag(name: str) -> str:
        """Zielfeld über den Spaltennamen (F-81), sonst ignorieren."""
        return NAMEN_ZU_ZIEL.get(" ".join(name.lower().split()), IGNORIEREN)


@dataclass
class Vorlage:
    """Der eingelesene, noch nicht interpretierte Bestand (F-80).

    ``zeilen`` trägt je Datensatz eine Zeile: die Excel-Zeile und ein
    Wörterbuch Spaltenname → Text. Leere Datensätze (außer laufender
    Nummer nichts) fehlen von vornherein (vorlagen/README).
    """

    dateiname: str
    format_art: str             # "xlsx" oder "csv"
    blatt: str                  # xlsx: Blattname, csv: ""
    kopfzeile: int = 1          # Excel-Zeile der Kopfzeile
    spalten: list[Quellspalte] = field(default_factory=list)
    zeilen: list[dict] = field(default_factory=list)
    # F-84: Seriennummern, die in diesem Blatt schon von einer anderen
    # Zeile belegt sind. Die eigene Zeile wird ohne sie angelegt, die
    # Notiz nennt die Nummer, Hinweis seriennummer-doppelt.
    doppelte_seriennummern: set[str] = field(default_factory=set)
    # F-84: Geräte, die aus einer früheren Zeile (Blatt oder Import) stammen
    # und im Bestand stehen, aber in diesem Blatt keine Rolle spielen.
    vorhandene_blatt_zeilen: set[int] = field(default_factory=set)

    def werte_von(self, ziel: str) -> list[str]:
        """Alle unterschiedlichen Werte einer Zielfeld-Spalte, in Reihenfolge."""
        spalten = [s for s in self.spalten if s.ziel == ziel]
        if not spalten:
            return []
        name = spalten[0].name
        gesehene: dict[str, None] = {}
        for zeile in self.zeilen:
            wert = (zeile["werte"].get(name) or "").strip()
            if not wert or wert in LEER_WERTE:
                continue
            gesehene.setdefault(wert, None)
        return list(gesehene)

    def anzahl_zeilen(self) -> int:
        return len(self.zeilen)


def _text_wert(wert) -> str:
    """Ein Zellwert als Text; None wird leer, ganze Zahlen ohne Nachkommakomma."""
    if wert is None:
        return ""
    if isinstance(wert, bool):
        return "Ja" if wert else "Nein"
    if isinstance(wert, float) and wert.is_integer():
        return str(int(wert))
    if isinstance(wert, datetime):
        return wert.strftime("%d.%m.%Y")
    if isinstance(wert, int):
        return str(wert)
    return " ".join(str(wert).split())


def _leer(wert: str) -> bool:
    return wert.strip() in LEER_WERTE or not wert.strip()


def lade_xlsx(dateiname: str, byte: bytes, blatt: str, kopfzeile: int) -> Vorlage:
    """.xlsx einlesen (F-80). Kopfzeile ist eine Excel-Zeilennummer ab 1.

    A-0127: Das Blatt wird einmal mit iter_rows gelesen und auf der Liste
    gearbeitet, weil ws.cell in read_only-Modus das Blatt jedes Mal von
    vorn liest.
    """
    wb = load_workbook(io.BytesIO(byte), read_only=True, data_only=True)
    namen = [ws.title for ws in wb.worksheets]
    if blatt not in namen:
        raise ImportFehler(f"Blatt nicht gefunden: {blatt}. Vorhanden: {', '.join(namen)}")
    ws = wb[blatt]

    # A-0127: Alle Zeilen einmal einlesen (read_only-Modus).
    alle_zeilen = list(ws.iter_rows(values_only=True))
    wb.close()

    kopfzeile = int(kopfzeile)
    if kopfzeile < 1 or kopfzeile > len(alle_zeilen):
        raise ImportFehler(f"Kopfzeile außerhalb des Blatts: Zeile {kopfzeile}")

    kopf = alle_zeilen[kopfzeile - 1]
    spalten: list[Quellspalte] = []
    max_spalten = max((len(z) for z in alle_zeilen), default=0)
    for spalte_nr in range(1, max_spalten + 1):
        name = _text_wert(kopf[spalte_nr - 1] if spalte_nr - 1 < len(kopf) else None)
        if not name:
            continue
        beispiel = ""
        for zeile in alle_zeilen[kopfzeile:]:
            if spalte_nr - 1 < len(zeile):
                beispiel = _text_wert(zeile[spalte_nr - 1])
                if beispiel:
                    break
        spalten.append(Quellspalte(nr=spalte_nr - 1, name=name, beispiel=beispiel,
                                   ziel=Quellspalte.vorschlag(name)))
    zeilen: list[dict] = []
    for i, zeile in enumerate(alle_zeilen[kopfzeile:], start=kopfzeile + 1):
        werte = {
            s.name: _text_wert(zeile[s.nr] if s.nr < len(zeile) else None)
            for s in spalten
        }
        if _datensatz_wertig(werte):
            zeilen.append({"zeile": i, "werte": werte})
    return Vorlage(
        dateiname=dateiname,
        format_art="xlsx",
        blatt=blatt,
        kopfzeile=kopfzeile,
        spalten=spalten,
        zeilen=zeilen,
    )


def _datensatz_wertig(werte: dict) -> bool:
    """Ein Datensatz ist wertig, wenn eine Spalte einen Wert hat, der nicht
    nur eine laufende Nummer ist (vorlagen/README, Notebooks Zeilen 34–36)."""
    for wert in werte.values():
        if _leer(wert):
            continue
        if wert.isdigit() and len(wert) <= 3:
            continue
        return True
    return False


def lade_csv(dateiname: str, byte: bytes) -> Vorlage:
    """.csv in UTF-8 mit Semikolon oder Komma (F-80)."""
    try:
        text = byte.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ImportFehler(f"Die Datei ist nicht UTF-8 kodiert: {e}") from e
    probe = text.splitlines()
    if not probe or not probe[0]:
        raise ImportFehler("Die CSV-Datei hat keine Kopfzeile.")
    trenner = ";" if probe[0].count(";") > probe[0].count(",") else ","
    leser = csv.DictReader(io.StringIO(text), delimiter=trenner)
    if not leser.fieldnames:
        raise ImportFehler("Die CSV-Datei hat keine Kopfzeile.")
    spalten = []
    for nr, name in enumerate(leser.fieldnames):
        name = (name or "").strip()
        if not name:
            continue
        spalten.append(Quellspalte(nr=nr, name=name, ziel=Quellspalte.vorschlag(name)))
    zeilen = []
    for idx, row in enumerate(leser, start=2):
        werte = {s.name: (row.get(s.name) or "").strip() for s in spalten}
        # F-83: Leere Zeilen erscheinen in der Vorschau als „übersprungen“
        # (eine Zeile je Excel-Zeile), sie werden hier nicht weggelassen.
        zeilen.append({"zeile": idx, "werte": werte})
    return Vorlage(
        dateiname=dateiname, format_art="csv", blatt="",
        kopfzeile=1, spalten=spalten, zeilen=zeilen,
    )


def lade_datei(dateiname: str, byte: bytes, blatt: str = "", kopfzeile: int = 1) -> Vorlage:
    """Datei nach dem Namen einlesen (F-80)."""
    if dateiname.lower().endswith(".csv"):
        return lade_csv(dateiname, byte)
    if dateiname.lower().endswith(".xlsx"):
        return lade_xlsx(dateiname, byte, blatt or "", int(kopfzeile))
    raise ImportFehler(f"Unbekanntes Format: {dateiname} (.xlsx oder .csv)")


# --- Vorschau (F-83, F-84, F-86) ----------------------------------------------

@dataclass
class VorschauZeile:
    """Eine Zeile der Vorschau (F-86): Excel-Zeile, Ergebnis, Grund."""

    zeile: int
    ergebnis: str               # neu | ergaenzt | konflikt | uebersprungen
    grund: str
    gerat: Gerat | None = None  # bei ergaenzt/konflikt das vorhandene Gerät
    hinweise: list[str] = field(default_factory=list)


def _spalten_fuer(vorlage: Vorlage, ziel: str) -> list[Quellspalte]:
    return [s for s in vorlage.spalten if s.ziel == ziel]


def _wert_feld(vorlage: Vorlage, ziel: str, werte: dict) -> str:
    """Den Wert eines Zielfelds aus der Zeile holen, wenn es zugeordnet ist."""
    for spalte in _spalten_fuer(vorlage, ziel):
        roh = (werte.get(spalte.name) or "").strip()
        if roh and not _leer(roh):
            return roh
    return ""


def _person_finden(nachweis: str) -> Person | None:
    """Person über Namen oder E-Mail (F-81, F-82)."""
    token = nachweis.strip()
    if "@" in token:
        return Person.objects.filter(email__iexact=token).first()
    klein = token.lower()
    for p in Person.objects.all():
        if p.vorname.lower() == klein:
            return p
        if p.nachname.lower() == klein:
            return p
        if p.voller_name().lower() == klein:
            return p
    return None


def _ort_finden(nachweis: str) -> Ort | None:
    """Ort über Kennung oder Namen (F-82)."""
    token = nachweis.strip()
    return Ort.objects.filter(kennung__iexact=token).first() \
        or Ort.objects.filter(name__iexact=token).first()


def _kategorie_finden(nachweis: str) -> Kategorie | None:
    """Kategorie über den Namen (F-82)."""
    token = nachweis.strip()
    return Kategorie.objects.filter(name__iexact=token).first() \
        or Kategorie.objects.filter(name__icontains=token).first()


def _lagerort_finden() -> Ort | None:
    return Ort.objects.filter(kennung__iexact="LAGER-EG").first()


# Garantiezeile (F-84, vorlagen/README): Typ „Garantie" ergänzt das Gerät
# mit derselben Seriennummer um Garantieende und Notiz.
GARANZIE_TYPOBER = "garantie"


def _kategorie_name_aus_wert(vorlage: Vorlage, eintrag: dict, spalten_ziel: dict[str, str]) -> str:
    """Den Kategorie-Namen der Zeile aus der Werte-Zuordnung holen (F-82)."""
    for spalte in vorlage.spalten:
        if spalten_ziel.get(spalte.name, IGNORIEREN) != "Kategorie":
            continue
        roh = (eintrag["werte"].get(spalte.name) or "").strip()
        if _leer(roh):
            return ""
        return roh
    return ""


def vorschau_berechnen(
    vorlage: Vorlage,
    spalten_ziel: dict[str, str],
    wert_zu_kategorie: dict[str, str],
    wert_zu_person: dict[str, str],
    wert_zu_arbeitsplatz: dict[str, str],
) -> list[VorschauZeile]:
    """Die Vorschau je Zeile (F-83, F-84, F-86).

    ``spalten_ziel``: Spaltenname → Zielfeld (F-81). ``wert_zu_*``: jeder
    Wert einmal zugeordnet, leerer Wert = nicht übernehmen (F-82).

    Die Reihenfolge ist wichtig (F-84): Seriennummer geht vor dem
    Gerätenamen, innerhalb eines Blatts wird nicht zusammengeführt,
    die Zeilen kommen in Blatreihenfolge und jede angelegte Zeile zählt
    für die folgenden (Garantiezeile, doppelte Seriennummer).
    """
    # F-84: Welche Seriennummern kommen in diesem Blatt mehr als einmal vor?
    zähler: dict[str, int] = {}
    for eintrag in vorlage.zeilen:
        sn = _wert_von(vorlage, eintrag, "Seriennummer", spalten_ziel)
        if sn and sn.lower() not in zähler:
            zähler[sn.lower()] = 0
        if sn:
            zähler[sn.lower()] += 1
    doppelt_sn = {k for k, v in zähler.items() if v > 1}

    # F-84: Seriennummern, die im Bestand schon eine andere Zeile belegen
    # (aus einem anderen Blatt oder einem früheren Import).
    bestands_sn: dict[str, int] = {}
    for gerat in Gerat.objects.filter(seriennummer__isnull=False):
        bestands_sn[gerat.seriennummer.lower()] = gerat.id

    zeilen: list[VorschauZeile] = []
    for eintrag in vorlage.zeilen:
        zeilen.append(_zeile_berechnen(vorlage, eintrag, spalten_ziel,
                                       wert_zu_kategorie, wert_zu_person,
                                       wert_zu_arbeitsplatz,
                                       doppelt_sn, bestands_sn))
    return zeilen


def _wert_von(vorlage: Vorlage, eintrag: dict, ziel: str, spalten_ziel: dict[str, str]) -> str:
    """Den Wert für ein Zielfeld aus den Zeilenwerten holen (F-81)."""
    for spalte in vorlage.spalten:
        if spalten_ziel.get(spalte.name, IGNORIEREN) != ziel:
            continue
        roh = (eintrag["werte"].get(spalte.name) or "").strip()
        if not _leer(roh):
            return roh
    return ""


def _zeile_berechnen(vorlage, eintrag, spalten_ziel, kat_map, pers_map, arbp_map,
                     doppelt_sn, bestands_sn) -> VorschauZeile:
    werte = eintrag["werte"]
    zeile_nr = eintrag["zeile"]
    grund_teile: list[str] = []
    hinweise: list[str] = []
    ergebnis = "neu"
    gerat: Gerat | None = None

    def ziel_von(spaltename: str) -> str:
        return spalten_ziel.get(spaltename, IGNORIEREN)

    seriennummer = _wert_von(vorlage, eintrag, "Seriennummer", spalten_ziel)
    geraetename = _wert_von(vorlage, eintrag, "Gerätename", spalten_ziel)
    kategorie_name = ""
    for spalte in vorlage.spalten:
        if spalten_ziel.get(spalte.name, IGNORIEREN) != "Kategorie":
            continue
        roh = (werte.get(spalte.name) or "").strip()
        if not _leer(roh):
            kategorie_name = roh
        break
    kategorie = None
    if kategorie_name and kategorie_name in kat_map:
        kategorie = _kategorie_finden(kat_map[kategorie_name])
    modell = _wert_von(vorlage, eintrag, "Modell", spalten_ziel)

    # F-83: ohne Kategorie/Modell/Gerätename wird übersprungen.
    if not kategorie and not modell and not geraetename:
        return VorschauZeile(zeile_nr, "uebersprungen",
                             "weder Kategorie noch Modell oder Gerätename bekannt",
                             None, hinweise)

    # F-84: Seriennummer geht vor, dann Gerätenamen (gleiche Kategorie).
    if seriennummer:
        sn_klein = seriennummer.lower()
        # 1) Bestandstreffer über die Seriennummer (F-84).
        if sn_klein in bestands_sn:
            gerat = Gerat.objects.get(id=bestands_sn[sn_klein])
            # F-84: verschiedene Seriennummern = anderes Gerät, Konflikt.
            # (Hier kann das nicht vorkommen, wir suchen über die SN.)
            ergebnis = _ergaenzt_oder_konflikt(gerat, seriennummer, geraetename,
                                                kat_map, pers_map, arbp_map,
                                                vorlage, eintrag, spalten_ziel)
            grund_teile = [f"besteht bereits: {gerat.inventarnummer}"]
            if ergebnis == "konflikt":
                grund_teile.append("abweichende Seriennummer")
            _ergaenzt_hinweise(gerat, hinweise)
            return VorschauZeile(zeile_nr, ergebnis, "; ".join(grund_teile), gerat, hinweise)
        # 2) Doppelte Seriennummer im Blatt (F-84, vorlagen/README Zeile 18):
        #    das Gerät wird ohne sie angelegt, die Notiz nennt sie, Hinweis.
        if sn_klein in doppelt_sn:
            ergebnis = "neu"
            grund_teile.append("Seriennummer doppelt im Blatt, ohne sie angelegt")
            hinweise.append("seriennummer-doppelt")
            return _neu_abschließen(zeile_nr, vorlage, eintrag, spalten_ziel,
                                    kat_map, pers_map, arbp_map, grund_teile, hinweise)

    elif geraetename:
        # F-84: Gerätenamen allein nur bei gleicher Kategorie, keine Blatts.
        kategorie_name_zeile = kategorie.name if kategorie else ""
        for gerat in Gerat.objects.filter(geraetename__iexact=geraetename):
            if kategorie_name_zeile and gerat.kategorie \
                    and gerat.kategorie.name.lower() != kategorie_name_zeile.lower():
                continue
            if gerat.seriennummer or gerat.ort is not None or gerat.person is not None:
                # Gerät stammt aus einer anderen Quelle: ergänzen.
                ergebnis = _ergaenzt_oder_konflikt(gerat, seriennummer, geraetename,
                                                    kat_map, pers_map, arbp_map,
                                                    vorlage, eintrag, spalten_ziel)
                grund_teile = [f"besteht bereits: {gerat.inventarnummer}"]
                if ergebnis == "konflikt":
                    grund_teile.append("abweichende Seriennummer")
                _ergaenzt_hinweise(gerat, hinweise)
                return VorschauZeile(zeile_nr, ergebnis, "; ".join(grund_teile), gerat, hinweise)
        # Im selben Blatt: kein Zusammenführen (F-84).

    # F-82: Person und Arbeitsplatz.
    person_wert = _wert_von(vorlage, eintrag, "Person", spalten_ziel)
    arbp_wert = _wert_von(vorlage, eintrag, "Arbeitsplatz", spalten_ziel)
    person = None
    if person_wert and person_wert in pers_map and pers_map[person_wert]:
        person = _person_finden(pers_map[person_wert])
    arbeitsplatz = None
    if arbp_wert and arbp_wert in arbp_map and arbp_map[arbp_wert]:
        arbeitsplatz = _ort_finden(arbp_map[arbp_wert])

    # F-83: neu — Person oder Arbeitsplatz, sonst Lagerort.
    if person is None and arbeitsplatz is None:
        lagerort = _lagerort_finden()
        grund_teile.append("ohne Person und Arbeitsplatz an LAGER-EG"
                           if lagerort else "ohne Person und Arbeitsplatz")
    else:
        grund_teile.append("In Benutzung")
    return VorschauZeile(zeile_nr, ergebnis, "; ".join(grund_teile), None, hinweise)


def _ergaenzt_oder_konflikt(gerat: Gerat, seriennummer: str, geraetename: str,
                            kat_map: dict[str, str], pers_map: dict[str, str],
                            arbp_map: dict[str, str], vorlage: Vorlage,
                            eintrag: dict, spalten_ziel: dict[str, str]) -> str:
    """Ob eine vorhandene Zeile „ergänzt“ oder „Konflikt“ ist (F-84).

    „Konflikt“ bei abweichender Seriennummer oder abweichenden Werten.
    „ergänzt“, wenn das Gerät Lücken hat, die die Datei füllt.
    """
    if seriennummer and gerat.seriennummer \
            and gerat.seriennummer.lower() != seriennummer.lower():
        return "konflikt"
    if geraetename and gerat.geraetename \
            and gerat.geraetename.lower() != geraetename.lower():
        return "konflikt"
    # F-84: Lücken im Bestand, die die Datei füllt = „ergänzt“.
    person_wert = _wert_von(vorlage, eintrag, "Person", spalten_ziel)
    arbp_wert = _wert_von(vorlage, eintrag, "Arbeitsplatz", spalten_ziel)
    modell = _wert_von(vorlage, eintrag, "Modell", spalten_ziel)
    hersteller = _wert_von(vorlage, eintrag, "Hersteller", spalten_ziel)
    luecken = 0
    if gerat.person is None and person_wert:
        luecken += 1
    if gerat.ort is None and arbp_wert:
        luecken += 1
    if not gerat.modell and modell:
        luecken += 1
    if not gerat.hersteller and hersteller:
        luecken += 1
    if luecken > 0:
        return "ergaenzt"
    # Keine Lücken, aber Gerät stammt aus anderer Quelle: trotzdem „ergänzt“
    # (die Zeile zählt, sie wird nicht neu angelegt).
    if gerat.seriennummer or gerat.ort is not None or gerat.person is not None:
        return "ergaenzt"
    return "ergaenzt"


def _neu_abschließen(zeile_nr, vorlage, eintrag, spalten_ziel, kat_map, pers_map,
                     arbp_map, grund_teile, hinweise) -> VorschauZeile:
    """Neu anlegen (F-83, F-85): Person oder Arbeitsplatz, sonst Lagerort."""
    person = None
    arbeitsplatz = None
    person_wert = _wert_von(vorlage, eintrag, "Person", spalten_ziel)
    arbp_wert = _wert_von(vorlage, eintrag, "Arbeitsplatz", spalten_ziel)
    if person_wert and person_wert in pers_map and pers_map[person_wert]:
        person = _person_finden(pers_map[person_wert])
    if arbp_wert and arbp_wert in arbp_map and arbp_map[arbp_wert]:
        arbeitsplatz = _ort_finden(arbp_map[arbp_wert])
    if person is None and arbeitsplatz is None:
        lagerort = _lagerort_finden()
        grund_teile.append("ohne Person und Arbeitsplatz an LAGER-EG"
                           if lagerort else "ohne Person und Arbeitsplatz")
    else:
        grund_teile.append("In Benutzung")
    return VorschauZeile(zeile_nr, "neu", "; ".join(grund_teile), None, hinweise)


def _ergaenzt_hinweise(gerat: Gerat, hinweise: list[str]) -> None:
    """Hinweise auf doppelten Gerätenamen oder Seriennummer (F-84)."""
    if gerat.geraetename:
        if list(Gerat.objects.filter(geraetename__iexact=gerat.geraetename)
                .exclude(pk=gerat.pk)):
            hinweise.append("geraetename-doppelt")
    if gerat.seriennummer:
        if list(Gerat.objects.filter(seriennummer__iexact=gerat.seriennummer)
                .exclude(pk=gerat.pk)):
            hinweise.append("seriennummer-doppelt")


def zusammenfassung(zeilen: list[VorschauZeile]) -> dict[str, int]:
    """Anzahl je Ergebnis (F-86)."""
    zahl = {"neu": 0, "ergaenzt": 0, "konflikt": 0, "uebersprungen": 0}
    for z in zeilen:
        if z.ergebnis in zahl:
            zahl[z.ergebnis] += 1
    return zahl


def csv_vorschau(zeilen: list[VorschauZeile]) -> str:
    """Die Vorschau als CSV: eine Zeile je Excel-Zeile (F-83, F-86)."""
    ausgabe = io.StringIO()
    schreiber = csv.writer(ausgabe, delimiter=";")
    schreiber.writerow(["Excel-Zeile", "Ergebnis", "Grund", "Hinweis"])
    for z in zeilen:
        schreiber.writerow([z.zeile, z.ergebnis, z.grund, ",".join(z.hinweise)])
    return ausgabe.getvalue()
