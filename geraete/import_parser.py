"""Parser und Vorschau für den Import (A-0113, F-80 bis F-86).

Dieser Teil ist reines Rechnen über den Bestand: Datei einlesen,
Spalten und Werte zuordnen, für jede Zeile das Ergebnis (neu,
ergänzt, Konflikt, übersprungen) mit Grund bestimmen. Gespeichert
wird hier nichts; das Speichern steht in ``services.import_speichern``
und nimmt dieselben Werte (``zeile_lesen``, ``ergaenzungen``,
``verbleib_plan``), damit Vorschau und Ergebnis nicht auseinanderlaufen.

Dateiformate (F-80): .xlsx mit Auswahl von Blatt und Kopfzeile oder
.csv in UTF-8 mit Semikolon oder Komma.
Leer gelten „-“, „?“ und „N.A.“ (F-82).
Zusammenführen (F-84): gleiche Seriennummer oder gleicher Gerätenamen
aus einem anderen Blatt oder einem früheren Import, die Seriennummer
geht vor; innerhalb eines Blatts wird nicht zusammengeführt. Eine Zeile,
die schon einmal importiert wurde, findet ihr Gerät über den Vorgang
„Import“ wieder, auch ohne Seriennummer und Gerätenamen.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook

from stammdaten.models import Kategorie, Ort, Person

from .models import Gerat, GeratKonflikt, Vorgang

# F-82: gelten als leer
LEER_WERTE = {"-", "?", "N.A.", "n.a.", "NA", "na", ""}

# Zielfelder, denen eine Quellspalte zugeordnet werden kann (F-81).
# Der Wert IGNORIEREN bedeutet „nicht übernehmen“.
IGNORIEREN = "ignorieren"
# F-81: Die Spalte wird Notiz; steht darin „Nutzer: …“, ist das zugleich die Person.
ZIEL_NOTIZ_PERSON = "Notiz/Person aus Kommentar"
# F-85: Die Spalte sagt, ob das Gerät defekt ist (Ja, Nein).
ZIEL_DEFEKT = "Defekt"
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
    ZIEL_NOTIZ_PERSON,
    ZIEL_DEFEKT,
    IGNORIEREN,
]

# A-0912 Nr. 2: Blatt Notebooks: „Gerät wird Modell und über die Werte
# Kategorie“ (vorlagen/README); der Prototyp sagt dazu: „Die Kategorie kommt
# aus der Spalte Gerät und wird im nächsten Schritt je Wert zugeordnet.“
# Deshalb bietet das Zielfeld für eine solche Spalte die Wahl
# „Kategorie/Modell“ an: der Wert wird Modell, die Spalte steht in
# Schritt 3 unter Kategorie.
# Spaltennamen, die in Normalform (klein, zusammengefasst) dazugehören.
ZIEL_WAHL_KAT_MOD = "Kategorie/Modell"
WAHL_KAT_MOD_SPALTEN = {"gerät", "geraet", "typ", "modell", "kategorie"}

# Zielfeld, das je Wert in der Datei einmal zugeordnet wird (F-82).
WERTFELDER = ["Kategorie", "Person", "Arbeitsplatz"]

# Vorschläge über gleichnamige Spalten (F-81), normalisierte Namen.
# „Rechnung“ und „Garantie“ sind in der Bestandsliste nur Ja/Nein-Spalten und
# werden nicht übernommen (vorlagen/README); sie stehen deshalb nicht hier.
NAMEN_ZU_ZIEL = {
    "typ": "Kategorie",
    "kategorie": "Kategorie",
    "geraet": ZIEL_WAHL_KAT_MOD,
    "gerät": ZIEL_WAHL_KAT_MOD,
    "modell": "Modell",
    "model": "Modell",
    "modellbezeichnung": "Modell",
    "hersteller": "Hersteller",
    "seriennummer": "Seriennummer",
    "sn": "Seriennummer",
    "geraetename": "Gerätename",
    "gerätename": "Gerätename",
    "kennung": "Gerätename",
    "wmc-id": "Gerätename",
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
    "garantie ende": "Garantie bis",
    "garantie bis": "Garantie bis",
    "kommentar": "Notiz",
    "notiz": "Notiz",
    "defekt": ZIEL_DEFEKT,
}

# F-82: Vorschläge für die Kategorie, soweit der Name es nicht von selbst sagt
# (Zuordnungen aus vorlagen/README). Alles andere bleibt „nicht übernehmen“.
KATEGORIE_WERTE = {
    "rechner": "Desktop-PC",
    "maus+tastatur": "Tastatur",
    "mikrofon": "Kamera und Video",
    "djimic2(einzelmikrofonfürosmopocket3)": "Kamera und Video",
    "gimbel": "Kamera und Video",
    "gimbelbüro": "Kamera und Video",
    "gimbelmobile": "Kamera und Video",
}
KATEGORIE_MUSTER = (
    (re.compile(r"macbook|thinkpad|matebook|huawei notebook", re.I), "Notebook"),
    (re.compile(r"\bimac\b|mac studio", re.I), "Desktop-PC"),
    (re.compile(r"\bipad\b", re.I), "Tablet"),
    (re.compile(r"\biphone\b", re.I), "Smartphone"),
    (re.compile(r"huawei monitor", re.I), "Monitor"),
    (re.compile(r"huawei maus", re.I), "Maus"),
    (re.compile(r"\bnas\b|buffalo", re.I), "NAS"),
)

# F-81: „aktueller Nutzer: Simon“ nennt die Person, „ursprünglicher Nutzer: Simon“ nicht.
_NUTZER = re.compile(r"(?P<vor>[\wÄÖÜäöüß]+\s+)?nutzer\s*:\s*(?P<name>[^;,\n]+)", re.I)
_NUTZER_FRUEHER = ("urspr", "früher", "frueher", "ehemal", "alt", "vorig", "letzt")

# Fest in der Oberfläche (TESTSCHNITTSTELLE 5), Schlüssel wie data-ergebnis.
ERGEBNIS_TEXTE = {
    "neu": "neu",
    "ergaenzt": "ergänzt",
    "konflikt": "Konflikt",
    "uebersprungen": "übersprungen",
}
FELD_TEXTE = {
    "seriennummer": "Seriennummer",
    "geraetename": "Gerätename",
    "hersteller": "Hersteller",
    "modell": "Modell",
    "kaufdatum": "Kaufdatum",
    "kaufpreis_netto": "Kaufpreis netto",
    "lieferant": "Lieferant",
    "rechnungsnummer": "Rechnungsnummer",
    "garantie_bis": "Garantie bis",
    "notiz": "Notiz",
    "zustand": "Zustand 4 (Defekt-Vermerk)",
    "person": "Person",
    "ort": "Arbeitsplatz",
}
HINWEIS_DEFEKT = "laut Altliste defekt: reparieren oder ausmustern"


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

    def werte_von(self, ziel: str, spalten_ziel: dict[str, str] | None = None) -> list[str]:
        """Alle unterschiedlichen Werte eines Zielfelds, in Reihenfolge.

        Wenn ``spalten_ziel`` mitgegeben ist (die in Schritt 2 gewählte
        Zuordnung), wird daraus die Spalte bestimmt; sonst aus
        ``Quellspalte.ziel`` (automatischer Vorschlag, F-81) (A-0912, Nr. 1).
        Zählt auch die Wahl ``Kategorie/Modell`` (A-0912, Nr. 2) und bei der
        Person die Namen aus „Nutzer: …“ im Kommentar (F-81).
        """
        return list(self.werte_mit_anzahl(ziel, spalten_ziel))

    def werte_mit_anzahl(self, ziel: str, spalten_ziel: dict[str, str] | None = None) -> dict[str, int]:
        """Jeder Wert eines Zielfelds einmal, mit der Zahl seiner Zeilen (F-82)."""
        if spalten_ziel is None:
            spalten_ziel = {s.name: s.ziel for s in self.spalten}
        if ziel == "Kategorie":
            auswahl = {"Kategorie", ZIEL_WAHL_KAT_MOD}
        elif ziel == "Modell":
            auswahl = {"Modell", ZIEL_WAHL_KAT_MOD}
        else:
            auswahl = {ziel}
        spalten = [s for s in self.spalten
                   if spalten_ziel.get(s.name, IGNORIEREN) in auswahl]
        gesehene: dict[str, int] = {}
        for zeile in self.zeilen:
            if ziel == "Person":
                werte = [_person_wert(self, zeile, spalten_ziel)]
            else:
                werte = [(zeile["werte"].get(s.name) or "").strip() for s in spalten]
            for wert in werte:
                if not wert or wert in LEER_WERTE:
                    continue
                gesehene[wert] = gesehene.get(wert, 0) + 1
        return gesehene

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


def _mappe_oeffnen(byte: bytes):
    """Die .xlsx öffnen; eine kaputte Datei ist ein Fehler des Einlesens (F-80)."""
    try:
        return load_workbook(io.BytesIO(byte), data_only=True)
    except Exception as e:
        raise ImportFehler(
            "Die Datei lässt sich nicht als .xlsx lesen. Bitte eine gültige Datei wählen."
        ) from e


def _zeilen_des_blatts(ws) -> tuple[list[tuple], list[tuple]]:
    """Die Zeilen eines Blatts: wie sie sind und mit gefüllten verbundenen Zellen.

    F-85: In der Raumliste ist die Spalte Arbeitsplatz über alle Zeilen eines
    Platzes verbunden; der Wert steht nur in der ersten. Gefüllt werden nur
    senkrecht verbundene Zellen; waagerechte sind Zwischenzeilen und Titel.
    """
    roh = [tuple(z) for z in ws.iter_rows(values_only=True)]
    gefuellt = [list(z) for z in roh]
    for bereich in ws.merged_cells.ranges:
        if bereich.min_col != bereich.max_col or bereich.min_row > len(gefuellt):
            continue
        spalte = bereich.min_col - 1
        wert = gefuellt[bereich.min_row - 1][spalte]
        for nr in range(bereich.min_row, min(bereich.max_row, len(gefuellt)) + 1):
            gefuellt[nr - 1][spalte] = wert
    return roh, [tuple(z) for z in gefuellt]


def kopfzeile_erkennen(zeilen: list[tuple]) -> int:
    """Die erste Zeile mit mindestens drei Spaltennamen als Text (F-80)."""
    for nr, zeile in enumerate(zeilen[:30], start=1):
        texte = [w for w in zeile if isinstance(w, str) and w.strip()]
        if len(texte) >= 3:
            return nr
    return 1


def blatt_gesperrt(name: str) -> bool:
    """F-80, Vorlagen-README: Die Blätter „Bedarfsanalyse“ sind keine Bestandsliste."""
    return name.strip().lower().startswith("bedarfsanalyse")


def blaetter_lesen(byte: bytes) -> list[dict]:
    """Die Blätter der Datei mit Zeilenzahl und erkannter Kopfzeile (F-80)."""
    wb = _mappe_oeffnen(byte)
    blaetter = []
    for ws in wb.worksheets:
        roh, gefuellt = _zeilen_des_blatts(ws)
        kopf = kopfzeile_erkennen(roh)
        spalten = _spalten_lesen(gefuellt, kopf) if gefuellt else []
        blaetter.append({
            "gesperrt": blatt_gesperrt(ws.title),
            "name": ws.title,
            "kopfzeile": kopf,
            "zeilen": len(_datensaetze(roh, gefuellt, kopf, spalten)) if spalten else 0,
        })
    wb.close()
    return blaetter


def _spalten_lesen(zeilen: list[tuple], kopfzeile: int) -> list[Quellspalte]:
    kopf = zeilen[kopfzeile - 1]
    spalten: list[Quellspalte] = []
    max_spalten = max((len(z) for z in zeilen), default=0)
    for spalte_nr in range(1, max_spalten + 1):
        name = _text_wert(kopf[spalte_nr - 1] if spalte_nr - 1 < len(kopf) else None)
        if not name:
            continue
        beispiel = ""
        for zeile in zeilen[kopfzeile:]:
            if spalte_nr - 1 < len(zeile):
                beispiel = _text_wert(zeile[spalte_nr - 1])
                if beispiel:
                    break
        spalten.append(Quellspalte(nr=spalte_nr - 1, name=name, beispiel=beispiel,
                                   ziel=Quellspalte.vorschlag(name)))
    return spalten


def _datensaetze(roh: list[tuple], gefuellt: list[tuple], kopfzeile: int,
                 spalten: list[Quellspalte]) -> list[dict]:
    """Die Datensätze unter der Kopfzeile. Ob eine Zeile zählt, sagt ihr eigener
    Inhalt, nicht ein Wert aus einer verbundenen Zelle (vorlagen/README)."""
    ergebnis: list[dict] = []
    for i in range(kopfzeile, len(gefuellt)):
        eigene = {
            s.name: _text_wert(roh[i][s.nr] if s.nr < len(roh[i]) else None)
            for s in spalten
        }
        if not _datensatz_wertig(eigene):
            continue
        werte = {
            s.name: _text_wert(gefuellt[i][s.nr] if s.nr < len(gefuellt[i]) else None)
            for s in spalten
        }
        ergebnis.append({"zeile": i + 1, "werte": werte})
    return ergebnis


def lade_xlsx(dateiname: str, byte: bytes, blatt: str, kopfzeile: int | None = None) -> Vorlage:
    """.xlsx einlesen (F-80). Kopfzeile ist eine Excel-Zeilennummer ab 1;
    ohne Angabe gilt die erkannte (``kopfzeile_erkennen``).

    A-0127 las das Blatt im read_only-Modus; verbundene Zellen (F-85) gibt es
    nur im normalen Modus, und die Datei ist klein genug dafür.
    """
    wb = _mappe_oeffnen(byte)
    namen = [ws.title for ws in wb.worksheets]
    if blatt not in namen:
        raise ImportFehler(f"Blatt nicht gefunden: {blatt}. Vorhanden: {', '.join(namen)}")
    roh, gefuellt = _zeilen_des_blatts(wb[blatt])
    wb.close()

    kopfzeile = int(kopfzeile) if kopfzeile else kopfzeile_erkennen(roh)
    if kopfzeile < 1 or kopfzeile > len(roh):
        raise ImportFehler(f"Kopfzeile außerhalb des Blatts: Zeile {kopfzeile}")

    spalten = _spalten_lesen(gefuellt, kopfzeile)
    if not spalten:
        raise ImportFehler(
            f"In Zeile {kopfzeile} des Blatts {blatt} stehen keine Spaltennamen. "
            "Bitte eine andere Kopfzeile wählen."
        )
    vorlage = Vorlage(
        dateiname=dateiname,
        format_art="xlsx",
        blatt=blatt,
        kopfzeile=kopfzeile,
        spalten=spalten,
        zeilen=_datensaetze(roh, gefuellt, kopfzeile, spalten),
    )
    _vorschlaege_nachziehen(vorlage)
    return vorlage


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
        raise ImportFehler("Die Datei ist nicht UTF-8 kodiert. Bitte als „CSV UTF-8“ speichern.") from e
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
    for s in spalten:
        for zeile in zeilen:
            if zeile["werte"].get(s.name):
                s.beispiel = zeile["werte"][s.name]
                break
    vorlage = Vorlage(
        dateiname=dateiname, format_art="csv", blatt="",
        kopfzeile=1, spalten=spalten, zeilen=zeilen,
    )
    _vorschlaege_nachziehen(vorlage)
    return vorlage


def lade_datei(dateiname: str, byte: bytes, blatt: str = "", kopfzeile: int | None = 1) -> Vorlage:
    """Datei nach dem Namen einlesen (F-80)."""
    if dateiname.lower().endswith(".csv"):
        return lade_csv(dateiname, byte)
    if dateiname.lower().endswith(".xlsx"):
        return lade_xlsx(dateiname, byte, blatt or "", kopfzeile)
    raise ImportFehler(f"Unbekanntes Format: {dateiname} (.xlsx oder .csv)")


def _vorschlaege_nachziehen(vorlage: Vorlage) -> None:
    """Vorschläge, für die der Spaltenname allein nicht reicht (F-81).

    Je Zielfeld schlägt nur die erste Spalte vor, sonst würden zwei Spalten
    dasselbe Feld füllen. Kommentare mit „Nutzer: …“ werden auch Person.
    Eine Spalte „Name“ ist der Hersteller, wenn es keine Spalte dafür gibt
    (Blatt Smartphones). Gibt es eine Spalte Kategorie, ist „Gerät“ nur Modell.
    """
    gesehen: set[str] = set()
    for spalte in vorlage.spalten:
        if spalte.ziel == IGNORIEREN:
            continue
        if spalte.ziel in gesehen:
            spalte.ziel = IGNORIEREN
        else:
            gesehen.add(spalte.ziel)
    for spalte in vorlage.spalten:
        name = " ".join(spalte.name.lower().split())
        if spalte.ziel == ZIEL_WAHL_KAT_MOD and "Kategorie" in gesehen:
            spalte.ziel = "Modell" if "Modell" not in gesehen else IGNORIEREN
        elif spalte.ziel == IGNORIEREN and name == "name" and "Hersteller" not in gesehen:
            spalte.ziel = "Hersteller"
        elif spalte.ziel == "Notiz" and any(
            nutzer_aus_kommentar(z["werte"].get(spalte.name) or "") for z in vorlage.zeilen
        ):
            spalte.ziel = ZIEL_NOTIZ_PERSON


def nutzer_aus_kommentar(text: str) -> str:
    """Der Name aus „Nutzer: …“ oder „aktueller Nutzer: …“ (F-81)."""
    treffer = _NUTZER.search(text or "")
    if treffer is None:
        return ""
    vor = (treffer.group("vor") or "").strip().lower()
    if vor.startswith(_NUTZER_FRUEHER):
        return ""
    return " ".join(treffer.group("name").split()).strip(" .")


# --- Vorschläge für die Werte (F-82) -------------------------------------------

def _kat_norm(text: str) -> str:
    return re.sub(r"[\s\-_]+", "", text.lower())


def kategorie_vorschlag(wert: str, namen: list[str]) -> str:
    """Vorschlag für einen Wert der Kategorie-Spalte; leer heißt „nicht übernehmen“."""
    norm = _kat_norm(wert)
    for name in namen:
        if _kat_norm(name) == norm:
            return name
    vorschlag = KATEGORIE_WERTE.get(norm, "")
    if not vorschlag:
        for muster, kategorie in KATEGORIE_MUSTER:
            if muster.search(wert):
                vorschlag = kategorie
                break
    return vorschlag if vorschlag in namen else ""


def kategorie_standard_vorschlag(blatt: str, namen: list[str]) -> str:
    """Blatt ohne Kategorie-Spalte: die Kategorie, die das Blatt im Namen trägt."""
    norm = _kat_norm(blatt)
    for name in namen:
        if norm in (_kat_norm(name), _kat_norm(name) + "s"):
            return name
    return ""


def person_vorschlag(wert: str) -> str:
    """Vorhandene Person, oder der volle Name für eine neue; sonst keine Person."""
    person = _person_finden(wert)
    if person is not None:
        return person.voller_name()
    return wert if len(wert.split()) >= 2 else ""


def person_mehrdeutig(wert: str) -> str:
    """Passt ein Vor- oder Nachname auf mehrere Personen, entscheidet der Mensch (F-82)."""
    klein = wert.strip().lower()
    treffer = sorted(p.voller_name() for p in Person.objects.all()
                     if klein in (p.vorname.lower(), p.nachname.lower()))
    return "Passt auf: " + ", ".join(treffer) if len(treffer) > 1 else ""


def ort_vorschlag(wert: str) -> str:
    """Nur ein vorhandener Ort wird vorgeschlagen; anlegen ist eine Entscheidung."""
    ort = _ort_finden(wert)
    return ort.kennung if ort is not None else ""


# --- Vorschau (F-83, F-84, F-86) ----------------------------------------------

@dataclass
class VorschauZeile:
    """Eine Zeile der Vorschau (F-86): Excel-Zeile, Ergebnis, Grund."""

    zeile: int
    ergebnis: str               # neu | ergaenzt | konflikt | uebersprungen
    grund: str
    gerat: Gerat | None = None  # bei ergaenzt/konflikt das vorhandene Gerät
    hinweise: list[str] = field(default_factory=list)
    hinweis_texte: dict[str, str] = field(default_factory=dict)
    kennung: str = ""           # bisherige Kennung (Gerätename) aus der Datei
    bezeichnung: str = ""       # Kategorie, Hersteller und Modell aus der Datei
    kategorie: Kategorie | None = None  # bei neu die Kategorie, die das Gerät bekommt

    @property
    def ergebnis_text(self) -> str:
        return ERGEBNIS_TEXTE.get(self.ergebnis, self.ergebnis)

    @property
    def hinweis_liste(self) -> list[dict]:
        return [{"art": h, "text": self.hinweis_texte.get(h, h)} for h in self.hinweise]


@dataclass
class Zeilenwerte:
    """Was eine Zeile nach den Zuordnungen aus Schritt 2 und 3 sagt."""

    seriennummer: str = ""
    geraetename: str = ""
    hersteller: str = ""
    modell: str = ""
    notiz: str = ""
    lieferant: str = ""
    rechnungsnummer: str = ""
    kaufdatum: date | None = None
    garantie_bis: date | None = None
    kaufpreis: Decimal | None = None
    kategorie_wert: str = ""            # Wert in der Datei
    kategorie: Kategorie | None = None  # Ergebnis der Zuordnung oder Blatt-Kategorie
    kategorie_abgewaehlt: bool = False  # Wert steht auf „nicht übernehmen“
    nicht_vorhanden: bool = False       # Kennung „Nicht vorhanden“: kein Gerät (Erwin 06.11.)
    person_ziel: str = ""               # Zuordnung: Name, leer = keine Person
    person: Person | None = None        # vorhandene Person
    person_neu: str = ""                # Name einer anzulegenden Person
    ort_ziel: str = ""
    ort: Ort | None = None              # vorhandener Ort
    ort_neu: str = ""                   # Kennung eines anzulegenden Arbeitsplatzes
    defekt: bool = False

    @property
    def ist_garantiezeile(self) -> bool:
        return self.kategorie_wert.strip().lower() == GARANZIE_TYPOBER

    @property
    def arbeitsplatz_genannt(self) -> bool:
        """Lagerorte zählen nicht: Dort ist das Gerät Auf Lager (Kapitel 4)."""
        if self.ort_neu:
            return True
        return self.ort is not None and self.ort.typ != Ort.TYP_LAGER

    @property
    def person_genannt(self) -> bool:
        return self.person is not None or bool(self.person_neu)

    @property
    def person_name(self) -> str:
        return self.person.voller_name() if self.person else self.person_neu

    @property
    def ort_name(self) -> str:
        return self.ort.kennung if self.ort else self.ort_neu


def _person_finden(nachweis: str) -> Person | None:
    """Person über Namen oder E-Mail (F-81, F-82).

    Der volle Name geht vor; ein Vor- oder Nachname allein nur, wenn er genau
    eine Person trifft. Bei „Jonas“ mit zwei Personen entscheidet der Mensch.
    """
    token = nachweis.strip()
    if "@" in token:
        return Person.objects.filter(email__iexact=token).first()
    klein = token.lower()
    personen = list(Person.objects.all())
    for p in personen:
        if p.voller_name().lower() == klein:
            return p
    treffer = [p for p in personen if klein in (p.vorname.lower(), p.nachname.lower())]
    return treffer[0] if len(treffer) == 1 else None


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
    """F-85: „Auf Lager“ heißt Lagerort (Kapitel 4), egal wie er heißt."""
    return Ort.objects.filter(typ=Ort.TYP_LAGER).order_by("kennung").first()


def neue_kennung(text: str) -> str:
    """Kennung für einen neuen Arbeitsplatz; die Adresse /arbeitsplaetze/<Kennung>/ verträgt nur diese Zeichen."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text.strip()).strip("-")


# Garantiezeile (F-84, vorlagen/README): Typ „Garantie" ergänzt das Gerät
# mit derselben Seriennummer um Garantieende und Notiz.
GARANZIE_TYPOBER = "garantie"


def _wert_von(vorlage: Vorlage, eintrag: dict, ziel: str, spalten_ziel: dict[str, str]) -> str:
    """Den Wert für ein Zielfeld aus den Zeilenwerten holen (F-81).

    A-0912 Nr. 2: Zählt auch die Wahl ``Kategorie/Modell``, deren Wert
    Modell ist (die Spalte steht in Schritt 3 unter Kategorie).
    """
    if ziel == "Modell":
        auswahl = {"Modell", ZIEL_WAHL_KAT_MOD}
    elif ziel == "Notiz":
        auswahl = {"Notiz", ZIEL_NOTIZ_PERSON}
    else:
        auswahl = {ziel}
    for spalte in vorlage.spalten:
        if spalten_ziel.get(spalte.name, IGNORIEREN) not in auswahl:
            continue
        roh = (eintrag["werte"].get(spalte.name) or "").strip()
        if not _leer(roh):
            return roh
    return ""


def _person_wert(vorlage: Vorlage, eintrag: dict, spalten_ziel: dict[str, str]) -> str:
    """Der Personenwert der Zeile: Spalte Person, sonst „Nutzer: …“ im Kommentar (F-81)."""
    wert = _wert_von(vorlage, eintrag, "Person", spalten_ziel)
    if wert:
        return wert
    for spalte in vorlage.spalten:
        if spalten_ziel.get(spalte.name, IGNORIEREN) != ZIEL_NOTIZ_PERSON:
            continue
        name = nutzer_aus_kommentar(eintrag["werte"].get(spalte.name) or "")
        if name:
            return name
    return ""


def datum_aus_text(text: str) -> date | None:
    """Datumswert der Datei; ungültige Werte bleiben leer (F-83)."""
    # _text_wert schreibt Datumswerte als TT.MM.JJJJ.
    for muster in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), muster).date()
        except ValueError:
            pass
    return None


def _preis_aus_text(text: str) -> Decimal | None:
    wert = text.replace("€", "").strip()
    if "," in wert:
        wert = wert.replace(".", "").replace(",", ".")
    try:
        return Decimal(wert)
    except InvalidOperation:
        return None


def _ist_defekt(werte_defekt: str, notiz: str) -> bool:
    """Defekte Geräte stehen im Kommentar oder in der Spalte „Defekt“ (5.10)."""
    if werte_defekt.strip().lower() in ("ja", "x", "true", "1", "defekt"):
        return True
    klein = notiz.lower()
    if "nicht defekt" in klein:
        return False
    return "defekt" in klein or "defect" in klein


def zeile_lesen(vorlage: Vorlage, eintrag: dict, spalten_ziel: dict[str, str],
                kat_map: dict[str, str], pers_map: dict[str, str], arbp_map: dict[str, str],
                standard: Kategorie | None = None) -> Zeilenwerte:
    """Die Werte einer Zeile nach den Zuordnungen, für Vorschau und Speichern."""
    def wert(ziel: str) -> str:
        return _wert_von(vorlage, eintrag, ziel, spalten_ziel)

    w = Zeilenwerte(
        seriennummer=wert("Seriennummer"),
        geraetename=wert("Gerätename"),
        hersteller=wert("Hersteller"),
        modell=wert("Modell"),
        notiz=wert("Notiz"),
        lieferant=wert("Lieferant"),
        rechnungsnummer=wert("Rechnungsnummer"),
        kaufdatum=datum_aus_text(wert("Kaufdatum")),
        garantie_bis=datum_aus_text(wert("Garantie bis")),
        kaufpreis=_preis_aus_text(wert("Kaufpreis netto")) if wert("Kaufpreis netto") else None,
    )
    # „Nicht vorhanden“ in der Raumliste ist kein Gerät, sondern eine Lücke am Platz (F-62, F-83),
    # auch wenn Hersteller, Typ und Modell daneben stehen (Entscheidung 7, Erwin 06.11.2026).
    if w.geraetename.strip().lower() == "nicht vorhanden":
        w.geraetename = ""
        w.nicht_vorhanden = True
    w.defekt = _ist_defekt(wert(ZIEL_DEFEKT), w.notiz)

    for spalte in vorlage.spalten:
        if spalten_ziel.get(spalte.name, IGNORIEREN) not in ("Kategorie", ZIEL_WAHL_KAT_MOD):
            continue
        roh = (eintrag["werte"].get(spalte.name) or "").strip()
        if not _leer(roh):
            w.kategorie_wert = roh
        break
    if w.kategorie_wert:
        ziel = (kat_map.get(w.kategorie_wert) or "").strip()
        if ziel:
            w.kategorie = _kategorie_finden(ziel)
        if w.kategorie is None:
            w.kategorie_abgewaehlt = True
    else:
        w.kategorie = standard

    person_wert = _person_wert(vorlage, eintrag, spalten_ziel)
    w.person_ziel = (pers_map.get(person_wert) or "").strip() if person_wert else ""
    if w.person_ziel:
        w.person = _person_finden(w.person_ziel)
        if w.person is None and "@" not in w.person_ziel:
            w.person_neu = w.person_ziel

    ort_wert = wert("Arbeitsplatz")
    w.ort_ziel = (arbp_map.get(ort_wert) or "").strip() if ort_wert else ""
    if w.ort_ziel:
        w.ort = _ort_finden(w.ort_ziel)
        if w.ort is None:
            w.ort_neu = neue_kennung(w.ort_ziel)
    return w


def ist_importiert_unbewegt(gerat: Gerat) -> bool:
    """Kam das Gerät aus dem Import und wurde seither nicht bewegt (F-85)?"""
    typen = set(Vorgang.objects.filter(gerat=gerat).values_list("typ", flat=True))
    if Vorgang.TYP_IMPORT not in typen or Vorgang.TYP_AUFNAHME in typen:
        return False
    return not typen.intersection(Vorgang.BEWEGUNGEN)


def _seriennummer_anderswo(gerat: Gerat, seriennummer: str) -> Gerat | None:
    """Trägt ein anderes Gerät desselben Herstellers diese Nummer schon (F-10, F-84)?"""
    andere = Gerat.objects.filter(seriennummer__iexact=seriennummer)
    if gerat is not None:
        andere = andere.exclude(pk=gerat.pk)
        if gerat.hersteller:
            for g in andere:
                if not g.hersteller or g.hersteller.lower() == gerat.hersteller.lower():
                    return g
            return None
    return andere.first()


def ergaenzungen(gerat: Gerat, w: Zeilenwerte) -> dict:
    """Die leeren Felder, die die Zeile füllt (F-84), Feld → neuer Wert.

    Dazu Garantiezeile (F-84) und Defekt-Vermerk (F-85). Person und Ort stehen
    in ``verbleib_plan``, weil sie vom Status des Geräts abhängen.
    """
    plan: dict = {}
    if not gerat.seriennummer and w.seriennummer \
            and _seriennummer_anderswo(gerat, w.seriennummer) is None:
        plan["seriennummer"] = w.seriennummer
    for feld, neu in (("geraetename", w.geraetename), ("hersteller", w.hersteller),
                      ("modell", w.modell), ("lieferant", w.lieferant),
                      ("rechnungsnummer", w.rechnungsnummer)):
        if neu and not getattr(gerat, feld):
            plan[feld] = neu
    for feld, neu in (("kaufdatum", w.kaufdatum), ("garantie_bis", w.garantie_bis),
                      ("kaufpreis_netto", w.kaufpreis)):
        if neu is not None and getattr(gerat, feld) is None:
            plan[feld] = neu

    notiz = gerat.notiz or ""
    # F-87: Der Kommentar jeder Zeile wird Notiz; Vorhandenes bleibt stehen (F-84).
    if w.notiz and not notiz:
        notiz = w.notiz
    elif w.notiz and w.notiz not in notiz:
        notiz = f"{notiz}; {w.notiz}"
    if w.defekt and gerat.zustand_ungeprueft and ist_importiert_unbewegt(gerat):
        plan["zustand"] = Gerat.ZUSTAND_EINGESCHRAENKT
        plan["zustand_ungeprueft"] = False
        if HINWEIS_DEFEKT not in notiz:
            notiz = f"{notiz}; {HINWEIS_DEFEKT}" if notiz else HINWEIS_DEFEKT
    if notiz != (gerat.notiz or ""):
        plan["notiz"] = notiz
    return plan


def verbleib_plan(gerat: Gerat, w: Zeilenwerte) -> dict:
    """Was die Zeile an Person und Ort eines vorhandenen Geräts ändert (F-85).

    Nur bei einem importierten, noch nicht bewegten Gerät. „Auf Lager“ wird
    mit Person oder Arbeitsplatz zu „In Benutzung“ als Altbestand, und das
    Gerät verlässt den Lagerort (Kapitel 4). Ein Gerät, das bewegt oder von
    Hand erfasst wurde, bleibt, wie es ist.
    """
    plan = {"person": False, "ort": False, "in_benutzung": False, "lager_raeumen": False}
    if not (w.person_genannt or w.arbeitsplatz_genannt) or not ist_importiert_unbewegt(gerat):
        return plan
    if gerat.status == Gerat.STATUS_AUF_LAGER:
        plan.update(person=w.person_genannt, ort=w.arbeitsplatz_genannt, in_benutzung=True,
                    lager_raeumen=not w.arbeitsplatz_genannt)
    elif gerat.status == Gerat.STATUS_IN_BENUTZUNG:
        plan["person"] = w.person_genannt and gerat.person_id is None
        plan["ort"] = w.arbeitsplatz_genannt and gerat.ort_id is None
    return plan


def _anzeige(wert) -> str:
    if wert is None:
        return ""
    if isinstance(wert, date):
        return wert.strftime("%d.%m.%Y")
    if isinstance(wert, Decimal):
        return f"{wert:.2f}"
    return str(wert)


def abweichungen(gerat: Gerat, w: Zeilenwerte) -> list[tuple[str, str, str]]:
    """Werte der Zeile, die dem Gerät widersprechen (F-84): Feld, alt, neu.

    Andere Schreibweisen bei Hersteller und Modell sind kein Konflikt. Ein
    schon entschiedener Konflikt mit demselben Wert kommt nicht wieder.
    """
    liste: list[tuple[str, str, str]] = []
    # Gleiche Seriennummer, andere Kategorie: Das sagt die Liste anders als das Gerät (F-84).
    if w.kategorie is not None and gerat.kategorie_id != w.kategorie.pk:
        liste.append(("kategorie", gerat.kategorie.name, w.kategorie.name))
    for feld, neu in (("geraetename", w.geraetename), ("rechnungsnummer", w.rechnungsnummer),
                      ("lieferant", w.lieferant)):
        alt = getattr(gerat, feld) or ""
        if neu and alt and neu.lower() != alt.lower():
            liste.append((feld, alt, neu))
    for feld, neu in (("kaufdatum", w.kaufdatum), ("garantie_bis", w.garantie_bis)):
        alt = getattr(gerat, feld)
        if neu is not None and alt is not None and neu != alt:
            liste.append((feld, _anzeige(alt), _anzeige(neu)))
    if w.kaufpreis is not None and gerat.kaufpreis_netto is not None \
            and w.kaufpreis != Decimal(str(gerat.kaufpreis_netto)):
        liste.append(("kaufpreis_netto", _anzeige(Decimal(str(gerat.kaufpreis_netto))), _anzeige(w.kaufpreis)))
    if w.person_genannt and gerat.person_id is not None \
            and (w.person is None or w.person.pk != gerat.person_id):
        liste.append(("person", gerat.person.voller_name(), w.person_name))
    if w.arbeitsplatz_genannt and gerat.ort_id is not None and gerat.ort.typ != Ort.TYP_LAGER \
            and (w.ort is None or w.ort.pk != gerat.ort_id):
        liste.append(("ort", gerat.ort.kennung, w.ort_name))
    if not liste:
        return liste
    entschieden = set(
        GeratKonflikt.objects.filter(gerat=gerat, offen=False)
        .values_list("feld", "neuer_wert")
    )
    return [(feld, alt, neu) for feld, alt, neu in liste if (feld, neu) not in entschieden]


class _Lauf:
    """Was für alle Zeilen eines Blatts gleich ist."""

    def __init__(self, vorlage, spalten_ziel, kat_map, pers_map, arbp_map, kategorie_standard=""):
        self.vorlage = vorlage
        self.spalten_ziel = spalten_ziel
        self.kat_map = kat_map
        self.pers_map = pers_map
        self.arbp_map = arbp_map
        self.standard = _kategorie_finden(kategorie_standard) if kategorie_standard else None
        self.sonstiges = Kategorie.objects.filter(name__iexact="Sonstiges").first()
        self.lager = _lagerort_finden()

        # F-84: Seriennummern im Bestand (aus anderem Blatt oder früherem Import).
        self.bestand_sn: dict[str, list[Gerat]] = {}
        for gerat in Gerat.objects.exclude(seriennummer="").select_related("kategorie", "person", "ort"):
            self.bestand_sn.setdefault(gerat.seriennummer.lower(), []).append(gerat)

        # F-84: Zeilen, die schon importiert wurden (Vorgang „Import“, F-87).
        self.herkunft: dict[tuple[str, int], list[tuple[str, int]]] = {}
        for notiz, gerat_id in Vorgang.objects.filter(typ=Vorgang.TYP_IMPORT).values_list("notiz", "gerat_id"):
            treffer = _HERKUNFT.match(notiz or "")
            if treffer:
                schluessel = (treffer.group("blatt"), int(treffer.group("zeile")))
                self.herkunft.setdefault(schluessel, []).append((treffer.group("datei"), gerat_id))

        # F-84: Gerätenamen und Zeilen in diesem Blatt, für den Hinweis.
        self.namen_im_blatt: dict[str, list[int]] = {}
        for eintrag in vorlage.zeilen:
            name = _wert_von(vorlage, eintrag, "Gerätename", spalten_ziel)
            if name:
                self.namen_im_blatt.setdefault(name.lower(), []).append(eintrag["zeile"])

        # Seriennummern, die dieser Lauf schon neu anlegt: Nummer → Hersteller und Zeile.
        self.neu_sn: dict[str, list[tuple[str, int]]] = {}

    def lesen(self, eintrag: dict) -> Zeilenwerte:
        return zeile_lesen(self.vorlage, eintrag, self.spalten_ziel, self.kat_map,
                           self.pers_map, self.arbp_map, self.standard)


_HERKUNFT = re.compile(r"^(?P<datei>.*) / (?P<blatt>.*) / Zeile (?P<zeile>\d+)$")


def herkunft_text(dateiname: str, blatt: str, zeile: int) -> str:
    """Text des Vorgangs „Import“: Dateiname, Blatt und Zeile (F-87)."""
    return f"{dateiname} / {blatt or '-'} / Zeile {zeile}"


def _bezeichnung(w: Zeilenwerte) -> str:
    teile = [w.kategorie.name if w.kategorie else w.kategorie_wert,
             " ".join(t for t in (w.hersteller, w.modell) if t)]
    return ", ".join(t for t in teile if t)


def vorschau_berechnen(
    vorlage: Vorlage,
    spalten_ziel: dict[str, str],
    wert_zu_kategorie: dict[str, str],
    wert_zu_person: dict[str, str],
    wert_zu_arbeitsplatz: dict[str, str],
    kategorie_standard: str = "",
) -> list[VorschauZeile]:
    """Die Vorschau je Zeile (F-83, F-84, F-86).

    ``spalten_ziel``: Spaltenname → Zielfeld (F-81). ``wert_zu_*``: jeder
    Wert einmal zugeordnet, leerer Wert = nicht übernehmen (F-82).
    ``kategorie_standard``: Kategorie für Zeilen ohne eigene (Blatt Smartphones).

    Die Reihenfolge ist wichtig (F-84): Eine schon importierte Zeile findet
    ihr Gerät, dann geht die Seriennummer vor dem Gerätenamen, innerhalb
    eines Blatts wird nicht zusammengeführt, die Zeilen kommen in
    Blattreihenfolge und jede angelegte Zeile zählt für die folgenden
    (Garantiezeile, doppelte Seriennummer).
    """
    lauf = _Lauf(vorlage, spalten_ziel, wert_zu_kategorie, wert_zu_person,
                 wert_zu_arbeitsplatz, kategorie_standard)
    zeilen: list[VorschauZeile] = []
    for eintrag in vorlage.zeilen:
        w = lauf.lesen(eintrag)
        zeile = _zeile_berechnen(lauf, eintrag, w)
        zeile.kennung = w.geraetename
        zeile.bezeichnung = _bezeichnung(w)
        zeilen.append(zeile)
        if zeile.ergebnis == "neu" and w.seriennummer \
                and "seriennummer-doppelt" not in zeile.hinweise:
            lauf.neu_sn.setdefault(w.seriennummer.lower(), []).append(
                (w.hersteller.lower(), eintrag["zeile"]))
    return zeilen


def _aus_herkunft(lauf: _Lauf, eintrag: dict, w: Zeilenwerte) -> Gerat | None:
    """Das Gerät, das aus genau dieser Zeile entstand oder sie schon aufnahm (F-84)."""
    vorlage = lauf.vorlage
    for datei, gerat_id in lauf.herkunft.get((vorlage.blatt or "-", eintrag["zeile"]), []):
        gerat = Gerat.objects.select_related("kategorie", "person", "ort").get(pk=gerat_id)
        if w.kategorie is not None and gerat.kategorie_id != w.kategorie.pk:
            continue
        if w.seriennummer and gerat.seriennummer \
                and w.seriennummer.lower() != gerat.seriennummer.lower():
            continue
        if datei != vorlage.dateiname and (
            w.modell.lower() != (gerat.modell or "").lower()
            or w.hersteller.lower() != (gerat.hersteller or "").lower()
        ):
            continue
        return gerat
    return None


def _aus_seriennummer(lauf: _Lauf, w: Zeilenwerte) -> Gerat | None:
    if not w.seriennummer:
        return None
    treffer = lauf.bestand_sn.get(w.seriennummer.lower(), [])
    for gerat in treffer:
        if w.hersteller and (gerat.hersteller or "").lower() == w.hersteller.lower():
            return gerat
    return treffer[0] if treffer else None


def _name_hinweis(lauf: _Lauf, zeile_nr: int, name: str, gerat: Gerat | None,
                  hinweise: list[str], texte: dict[str, str]) -> None:
    """Hinweis geraetename-doppelt: Name auch in einer anderen Zeile oder am Gerät (F-84)."""
    if not name:
        return
    andere = Gerat.objects.filter(geraetename__iexact=name)
    if gerat is not None:
        andere = andere.exclude(pk=gerat.pk)
    nummern = list(andere.values_list("inventarnummer", flat=True)[:3])
    zeilen = [z for z in lauf.namen_im_blatt.get(name.lower(), []) if z != zeile_nr]
    if not nummern and not zeilen:
        return
    hinweise.append("geraetename-doppelt")
    if nummern:
        texte["geraetename-doppelt"] = "Gerätename auch bei " + ", ".join(nummern)
    else:
        texte["geraetename-doppelt"] = "Gerätename auch in Zeile " + ", ".join(str(z) for z in zeilen)


def _zeile_berechnen(lauf: _Lauf, eintrag: dict, w: Zeilenwerte) -> VorschauZeile:
    zeile_nr = eintrag["zeile"]

    # Entscheidung 7: Eine Zeile mit der Kennung „Nicht vorhanden“ beschreibt eine Lücke am Platz.
    if w.nicht_vorhanden:
        return VorschauZeile(zeile_nr, "uebersprungen", "„Nicht vorhanden“: kein Gerät am Platz")

    # F-84: Schon importierte Zeile, dann Seriennummer.
    gerat = _aus_herkunft(lauf, eintrag, w) or _aus_seriennummer(lauf, w)
    if gerat is not None:
        return _gegen_geraet(lauf, zeile_nr, w, gerat)

    # F-84 (vorlagen/README Zeile 5): Die Garantiezeile hat die Kategorie
    # „nicht übernehmen“, ergänzt aber das Gerät aus demselben Blatt.
    if w.ist_garantiezeile and w.seriennummer and w.seriennummer.lower() in lauf.neu_sn:
        herkunft_zeile = lauf.neu_sn[w.seriennummer.lower()][0][1]
        return VorschauZeile(zeile_nr, "ergaenzt", f"ergänzt Gerät aus Zeile {herkunft_zeile}")

    # F-82: Kategorie auf „nicht übernehmen“ → übersprungen.
    if w.kategorie_abgewaehlt:
        return VorschauZeile(zeile_nr, "uebersprungen", "Kategorie nicht übernehmen")

    # F-83: Kategorie und Modell oder ein Gerätename. Das Gerät braucht eine
    # Kategorie; bei einem Gerätenamen allein ist das „Sonstiges“.
    kategorie = w.kategorie
    ersatz = False
    if kategorie is None and w.geraetename and lauf.sonstiges is not None:
        kategorie = lauf.sonstiges
        ersatz = True
    if kategorie is None:
        grund = "keine Kategorie bekannt" if (w.modell or w.geraetename) \
            else "weder Kategorie noch Modell oder Gerätename bekannt"
        return VorschauZeile(zeile_nr, "uebersprungen", grund)
    if not w.modell and not w.geraetename:
        return VorschauZeile(zeile_nr, "uebersprungen",
                             "nur die Kategorie bekannt, weder Modell noch Gerätename")

    # F-84: Über den Gerätenamen nur bei gleicher Kategorie, und bei
    # verschiedenen Seriennummern ist es ein anderes Gerät.
    if w.geraetename:
        passende = []
        for kandidat in Gerat.objects.filter(geraetename__iexact=w.geraetename) \
                .select_related("kategorie", "person", "ort").order_by("inventarnummer"):
            if not ersatz and kandidat.kategorie_id != kategorie.pk:
                continue
            if w.seriennummer and kandidat.seriennummer \
                    and w.seriennummer.lower() != kandidat.seriennummer.lower():
                continue
            passende.append(kandidat)
        if len(passende) > 1:
            nummern = ", ".join(g.inventarnummer for g in passende)
            return VorschauZeile(zeile_nr, "uebersprungen",
                                 f"Gerätename passt auf mehrere Geräte ({nummern}); bitte von Hand zuordnen")
        if passende:
            return _gegen_geraet(lauf, zeile_nr, w, passende[0])
        # Manche Listen tragen die Seriennummer in der Spalte für die Kennung (Raumliste).
        if not w.seriennummer:
            kandidat = Gerat.objects.filter(seriennummer__iexact=w.geraetename) \
                .select_related("kategorie", "person", "ort").first()
            if kandidat is not None and (ersatz or kandidat.kategorie_id == kategorie.pk):
                w.seriennummer, w.geraetename = w.geraetename, ""
                return _gegen_geraet(lauf, zeile_nr, w, kandidat)

    teile: list[str] = []
    hinweise: list[str] = []
    texte: dict[str, str] = {}
    if ersatz:
        teile.append("ohne Kategorie, als Sonstiges angelegt")

    # F-84: Dieselbe Nummer beim selben Hersteller im Blatt: Das Gerät entsteht
    # ohne sie, die Notiz nennt sie. Bei einem anderen Hersteller behält es sie.
    if w.seriennummer:
        for hersteller, zeile in lauf.neu_sn.get(w.seriennummer.lower(), []):
            if not hersteller or not w.hersteller or hersteller == w.hersteller.lower():
                teile.append("Seriennummer doppelt im Blatt, ohne sie angelegt")
                hinweise.append("seriennummer-doppelt")
                texte["seriennummer-doppelt"] = f"Seriennummer auch in Zeile {zeile}"
                break

    _name_hinweis(lauf, zeile_nr, w.geraetename, None, hinweise, texte)

    # F-85: Status und Verbleib.
    if w.person_genannt or w.arbeitsplatz_genannt:
        teile.append(_verbleib_text(w))
        hinweise.append("altbestand")
        texte["altbestand"] = "Altbestand ohne Protokoll"
    else:
        teile.append(f"ohne Person und Arbeitsplatz an {lauf.lager.kennung}"
                     if lauf.lager else "ohne Person und Arbeitsplatz")
    if w.defekt:
        teile.append("Defekt-Vermerk: Zustand 4")
    else:
        hinweise.append("ungeprueft")
        texte["ungeprueft"] = "Zustand ungeprüft"
    return VorschauZeile(zeile_nr, "neu", "; ".join(teile), None, hinweise, texte,
                         kategorie=kategorie)


def _verbleib_text(w: Zeilenwerte) -> str:
    teile = ["In Benutzung"]
    if w.person_genannt:
        teile.append(f"bei {w.person_name}" + (" (neue Person)" if w.person_neu else ""))
    if w.arbeitsplatz_genannt:
        teile.append(f"an {w.ort_name}" + (" (neuer Arbeitsplatz)" if w.ort_neu else ""))
    return " ".join(teile)


def _gegen_geraet(lauf: _Lauf, zeile_nr: int, w: Zeilenwerte, gerat: Gerat) -> VorschauZeile:
    """Eine Zeile gegen ein vorhandenes Gerät: ergänzt oder Konflikt (F-84)."""
    nr = gerat.inventarnummer
    # Manche Listen tragen die Seriennummer in der Spalte für die Kennung (Raumliste).
    if not w.seriennummer and w.geraetename and w.geraetename.lower() == (gerat.seriennummer or "").lower():
        w.seriennummer, w.geraetename = w.geraetename, ""
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        return VorschauZeile(zeile_nr, "uebersprungen",
                             f"{nr} ist ausgemustert und nur noch lesbar", gerat)

    hinweise: list[str] = []
    texte: dict[str, str] = {}
    _name_hinweis(lauf, zeile_nr, w.geraetename or gerat.geraetename, gerat, hinweise, texte)
    if w.seriennummer and not gerat.seriennummer:
        anderes = _seriennummer_anderswo(gerat, w.seriennummer)
        if anderes is not None:
            hinweise.append("seriennummer-doppelt")
            texte["seriennummer-doppelt"] = f"Seriennummer auch bei {anderes.inventarnummer}"

    grund = [f"besteht bereits: {nr}"]
    abweichend = abweichungen(gerat, w)
    plan = ergaenzungen(gerat, w)
    verbleib = verbleib_plan(gerat, w)
    gefuellt = [FELD_TEXTE[f] for f in plan if f in FELD_TEXTE]
    if verbleib["person"]:
        gefuellt.append(f"Person {w.person_name}" + (" (neue Person)" if w.person_neu else ""))
    if verbleib["ort"]:
        gefuellt.append(f"Arbeitsplatz {w.ort_name}" + (" (neuer Arbeitsplatz)" if w.ort_neu else ""))
    if gefuellt:
        grund.append("ergänzt: " + ", ".join(gefuellt))
    if verbleib["in_benutzung"]:
        grund.append("In Benutzung")
        hinweise.append("altbestand")
        texte["altbestand"] = "Altbestand ohne Protokoll"
    elif (w.person_genannt or w.arbeitsplatz_genannt) and not verbleib["person"] and not verbleib["ort"] \
            and not ist_importiert_unbewegt(gerat) and gerat.person_id is None:
        grund.append("Person und Arbeitsplatz nicht übernommen, das Gerät wurde bewegt oder von Hand erfasst")
    if abweichend:
        grund.append("abweichend: " + ", ".join(
            f"{FELD_TEXTE.get(f, f)} {alt} → {neu}" for f, alt, neu in abweichend))
        return VorschauZeile(zeile_nr, "konflikt", "; ".join(grund), gerat, hinweise, texte)
    if not gefuellt and not verbleib["in_benutzung"]:
        grund.append("nichts zu ergänzen")
    return VorschauZeile(zeile_nr, "ergaenzt", "; ".join(grund), gerat, hinweise, texte)


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
    schreiber.writerow(["Excel-Zeile", "Ergebnis", "Grund", "Hinweis", "Kennung", "Gerät"])
    for z in zeilen:
        schreiber.writerow([z.zeile, z.ergebnis_text, z.grund, ",".join(z.hinweise),
                            z.kennung, z.bezeichnung])
    return ausgabe.getvalue()
