"""/import/ als Folge von Schritten (A-0113, F-80 bis F-84, F-86).

Schritt 1: Datei hochladen, Blatt und Kopfzeile wählen oder .csv
Schritt 2: Quellspalten einem Zielfeld zuordnen (Vorschläge F-81)
Schritt 3: Werte von Kategorie, Person, Arbeitsplatz zuordnen (F-82)
Schritt 4: Vorschau je Zeile mit Ergebnis und Grund, als CSV (F-83, F-86)

Gespeichert wird in diesem Teil noch nichts; das Speichern kommt in
Teil 3. Der Stand bleibt zwischen den Schritten in der Sitzung, damit
die Schritte im Browser in Ruhe durchgegangen werden können
(TESTSCHNITTSTELLE 3). Nur it-admin kann den Import sehen; für die
beiden anderen Rollen gibt es 403 (TESTSCHNITTSTELLE 3).
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import import_parser
from .import_parser import (IGNORIEREN, ImportFehler, VorschauZeile,
                            csv_vorschau, zusammenfassung)

# Schlüssel der Sitzung für den Import-Stand (TESTSCHNITTSTELLE 3).
SCHLUESSEL = "import_stand"


def _nutzer_konto(nutzer: User):
    """Das Konto (die Benutzerklasse) des Nutzers; None, wenn kein Konto."""
    return nutzer


def _darf_import(nutzer: User) -> bool:
    """IT-Admin darf den Import sehen (TESTSCHNITTSTELLE 3)."""
    rolle = getattr(nutzer, "rolle", None)
    return rolle == "admin"


def _stand_aus_sitzung(request: HttpRequest) -> dict | None:
    return request.session.get(SCHLUESSEL)


def _stand_in_sitzung(request: HttpRequest, stand: dict) -> None:
    request.session[SCHLUESSEL] = stand


def _vorlage_bauen(stand: dict) -> import_parser.Vorlage:
    """Die Vorlage aus dem gespeicherten Stand neu einlesen."""
    byte = bytes.fromhex(stand["datei_hex"])
    return import_parser.lade_datei(stand["dateiname"], byte,
                                    stand.get("blatt", ""), stand.get("kopfzeile", 1))


def _vorschau_aufladen(stand: dict) -> list[VorschauZeile]:
    vorlage = _vorlage_bauen(stand)
    return import_parser.vorschau_berechnen(
        vorlage,
        stand.get("spalten_ziel", {}),
        stand.get("wert_zu_kategorie", {}),
        stand.get("wert_zu_person", {}),
        stand.get("wert_zu_arbeitsplatz", {}),
    )


def import_seite(request: HttpRequest):
    """/import/: die Folge der Schritte (F-80 bis F-86)."""
    if not _darf_import(request.user):
        raise PermissionDenied("Zugriff verweigert: Der Import ist nur für IT-Admin erlaubt.")
    stand = _stand_aus_sitzung(request)
    if stand is None:
        return render(request, "geraete/import.html", {
            "schritt": 1,
            "fehler": request.GET.get("fehler", ""),
        })
    vorlage = _vorlage_bauen(stand)
    schritt = stand.get("schritt", 1)
    if schritt >= 4:
        vorschau = _vorschau_aufladen(stand)
        hinweis_flag = any(z.hinweise for z in vorschau)
        return render(request, "geraete/import.html", {
            "schritt": 4,
            "vorlage": vorlage,
            "vorschau": vorschau,
            "zusammenfassung": zusammenfassung(vorschau),
            "hinweis_flag": hinweis_flag,
        })
    if schritt == 3:
        return render(request, "geraete/import.html", {
            "schritt": 3,
            "vorlage": vorlage,
            "werte_kategorie": vorlage.werte_von("Kategorie"),
            "werte_person": vorlage.werte_von("Person"),
            "werte_arbeitsplatz": vorlage.werte_von("Arbeitsplatz"),
            "neuer_person_name": stand.get("neuer_person_name", ""),
        })
    # schritt == 2
    return render(request, "geraete/import.html", {
        "schritt": 2,
        "vorlage": vorlage,
        "ziele": import_parser.ZIELFELDER,
    })


@require_POST
def import_datei(request: HttpRequest):
    """Schritt 1: Datei hochladen, Blatt und Kopfzeile wählen (F-80)."""
    if not _darf_import(request.user):
        raise PermissionDenied("Zugriff verweigert: Der Import ist nur für IT-Admin erlaubt.")
    up = request.FILES.get("datei")
    if up is None:
        return render(request, "geraete/import.html",
                      {"fehler": "Keine Datei hochgeladen.", "schritt": 1},
                      status=400)
    dateiname = up.name
    byte = up.read()
    blatt = request.POST.get("blatt", "")
    kopfzeile = request.POST.get("kopfzeile", "1")
    try:
        vorlage = import_parser.lade_datei(dateiname, byte, blatt, int(kopfzeile))
    except ImportFehler as e:
        return render(request, "geraete/import.html",
                      {"fehler": str(e), "schritt": 1}, status=400)
    blatter: list[tuple[str, int]] = []
    if vorlage.format_art == "xlsx":
        try:
            import io
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(byte), read_only=True, data_only=True)
            blatter = [(ws.title, ws.max_row) for ws in wb.worksheets]
            wb.close()
        except Exception:
            blatter = []
    stand = {
        "dateiname": dateiname,
        "datei_hex": byte.hex(),
        "blatt": vorlage.blatt,
        "kopfzeile": vorlage.kopfzeile,
        "blatter": blatter,
        "spalten_ziel": {s.name: s.ziel for s in vorlage.spalten},
        "wert_zu_kategorie": {w: "" for w in vorlage.werte_von("Kategorie")},
        "wert_zu_person": {w: "" for w in vorlage.werte_von("Person")},
        "wert_zu_arbeitsplatz": {w: "" for w in vorlage.werte_von("Arbeitsplatz")},
        "neuer_person_name": "",
        "schritt": 2,
    }
    _stand_in_sitzung(request, stand)
    return redirect("/import/")


@require_POST
def import_spalten(request: HttpRequest):
    """Schritt 2: Quellspalten einem Zielfeld zuordnen (F-81)."""
    if not _darf_import(request.user):
        raise PermissionDenied("Zugriff verweigert: Der Import ist nur für IT-Admin erlaubt.")
    stand = _stand_aus_sitzung(request)
    if stand is None:
        return redirect("/import/")
    vorlage = _vorlage_bauen(stand)
    spalten_ziel = dict(stand.get("spalten_ziel", {}))
    for spalte in vorlage.spalten:
        wert = request.POST.get(f"ziel_{spalte.name}", IGNORIEREN)
        spalten_ziel[spalte.name] = wert if wert else IGNORIEREN
    stand["spalten_ziel"] = spalten_ziel
    for key, feld in (("wert_zu_kategorie", "Kategorie"),
                      ("wert_zu_person", "Person"),
                      ("wert_zu_arbeitsplatz", "Arbeitsplatz")):
        alt = stand.get(key, {})
        stand[key] = {w: alt.get(w, "") for w in vorlage.werte_von(feld)}
    stand["schritt"] = 3
    _stand_in_sitzung(request, stand)
    return redirect("/import/")


@require_POST
def import_werte(request: HttpRequest):
    """Schritt 3: Werte zuordnen (F-82).

    Jeder Wert einmal, auch auf nicht übernehmen (leer). Leere Werte der
    Datei zählen mit (F-82).
    """
    if not _darf_import(request.user):
        raise PermissionDenied("Zugriff verweigert: Der Import ist nur für IT-Admin erlaubt.")
    stand = _stand_aus_sitzung(request)
    if stand is None:
        return redirect("/import/")
    vorlage = _vorlage_bauen(stand)
    for key, feld in (("wert_zu_kategorie", "Kategorie"),
                      ("wert_zu_person", "Person"),
                      ("wert_zu_arbeitsplatz", "Arbeitsplatz")):
        mappe: dict[str, str] = {}
        for wert in vorlage.werte_von(feld):
            mappe[wert] = request.POST.get(f"{key}_{wert}", "").strip()
        stand[key] = mappe
    stand["neuer_person_name"] = request.POST.get("neuer_person_name", "").strip()
    stand["schritt"] = 4
    _stand_in_sitzung(request, stand)
    return redirect("/import/")


def import_vorschau_csv(request: HttpRequest):
    """Die Vorschau als CSV: eine Zeile je Excel-Zeile (F-83, F-86)."""
    if not _darf_import(request.user):
        raise PermissionDenied("Zugriff verweigert: Der Import ist nur für IT-Admin erlaubt.")
    stand = _stand_aus_sitzung(request)
    if stand is None:
        return HttpResponse(status=404)
    vorschau = _vorschau_aufladen(stand)
    antwort = HttpResponse(csv_vorschau(vorschau), content_type="text/csv; charset=utf-8")
    antwort["Content-Disposition"] = 'attachment; filename="import-vorschau.csv"'
    return antwort


@require_POST
def import_speichern_view(request: HttpRequest):
    """Speichern nach Bestätigung (F-86 bis F-87, A-0114 Teil 3).

    POST: ruft die Service-Funktion ``import_speichern`` auf und zeigt
    eine Erfolgsmeldung mit den Zahlen neu, ergänzt, Konflikt, übersprungen.
    """
    if not _darf_import(request.user):
        raise PermissionDenied("Zugriff verweigert: Der Import ist nur für IT-Admin erlaubt.")
    stand = _stand_aus_sitzung(request)
    if stand is None:
        return redirect("/import/")

    vorlage = _vorlage_bauen(stand)
    vorschau = _vorschau_aufladen(stand)
    from . import services
    ergebnis = services.import_speichern(
        vorlage=vorlage,
        vorschau=vorschau,
        spalten_ziel=stand.get("spalten_ziel", {}),
        wert_zu_kategorie=stand.get("wert_zu_kategorie", {}),
        wert_zu_person=stand.get("wert_zu_person", {}),
        wert_zu_arbeitsplatz=stand.get("wert_zu_arbeitsplatz", {}),
        dateiname=stand.get("dateiname", ""),
        blatt=stand.get("blatt", ""),
        konto=request.user,
    )
    # Sitzung bereinigen
    request.session.pop(SCHLUESSEL, None)
    meldung = (
        f"Import gespeichert: {ergebnis['neu']} neu, {ergebnis['ergaenzt']} ergänzt, "
        f"{ergebnis['konflikt']} Konflikt, {ergebnis['uebersprungen']} übersprungen."
    )
    return redirect("/geraete/?meldung=import-speichern")
