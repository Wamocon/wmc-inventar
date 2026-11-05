"""A-0123 M6 Teil 1: Protokoll (F-130 bis F-134, F-22).

Hier stehen die Service-Funktionen, die das Protokoll weiterführen:
  - ``checkliste_beantworten`` (F-132): die sechs Punkte ja/nein
  - ``offboarding_abhaken`` (F-133): die 13 Prüfpunkte
  - ``foto_hochladen`` (F-134): JPG/PNG/HEIC bis 10 MB, verkleinert
  - ``scan_hochladen`` (F-22): Stand scan-offen → abgeschlossen

AGENTS.md: „Ein Vorgang = eine Funktion, eine Transaktion. Statuswechsel
nur über die Service-Schicht, nicht in Views oder Templates."
"""
from __future__ import annotations

import io
from datetime import datetime

from django.core.files.base import ContentFile
from django.utils import timezone

from konten.zeit import jetzt_aware

from konten.models import Konto

from .models import Protokoll
from .services import GeratFehler

# --- F-134: zulässige Fotoformate und Größe ----------------------------------
# JPG, PNG und HEIC bis 10 MB (TESTSCHNITTSTELLE 3).
ERLAUBTE_FOTO_TYPEN = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/heic": ".heic",
    "image/heif": ".heic",
}
MAX_FOTO_GROESSE = 10 * 1024 * 1024  # 10 MB

# F-134: verkleinert gespeichert, längste Kante in Pixel.
PDF_KANTE_PUNKT = 1600


def _typ_am_inhalt(roh: bytes) -> str | None:
    """N-02: Der Dateityp wird am Inhalt erkannt, nicht an Endung oder Absenderangabe."""
    if roh[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if roh[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if roh[:5] == b"%PDF-":
        return "application/pdf"
    if roh[4:8] == b"ftyp" and roh[8:12] in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"):
        return "image/heic"
    return None

# --- F-132: Checkliste Zugänge ------------------------------------------------

def _stand_beantwortbar(protokoll: Protokoll) -> bool:
    """Checkliste und Prüfpunkte sind beantwortbar, solange das Protokoll
    noch nicht signiert ist: ``scan-offen`` und ``bearbeiter-offen`` (F-22).
    Nach der Signatur sind sie gesperrt.
    """
    return protokoll.bearbeiter_signiert_am is None and protokoll.stand in (
        Protokoll.STAND_SCAN_OFFEN,
        Protokoll.STAND_BEARBEITER_OFFEN,
    )


def _stand_anhaenge_erlaubt(protokoll: Protokoll) -> bool:
    """Anhänge (Fotos) sind erlaubt, solange das Protokoll nicht
    abgeschlossen ist: ``scan-offen`` und ``bearbeiter-offen`` (F-22, F-134).
    """
    return _stand_beantwortbar(protokoll)


def checkliste_beantworten(
    protokoll: Protokoll, werte: dict, ausgefuehrt_von: Konto | None = None,
    bemerkungen: dict | None = None,
) -> Protokoll:
    """F-132: Checkliste mit Ja (1) / Nein (0) beantworten.

    Erlaubt, solange das Protokoll im Stand „scan-offen" oder
    „bearbeiter-offen" ist (F-22). Nach der Signatur gesperrt.
    Das PDF entsteht danach; hier wird nur der Stand der Antworten
    nachgezogen, damit das PDF den befragten Stand trägt.
    """
    if not _stand_beantwortbar(protokoll):
        raise GeratFehler(
            "Die Checkliste ist für ein abgeschlossenes Protokoll gesperrt."
        )
    erlaubt = {schluessel for schluessel, _text in Protokoll.CHECKLISTE_PUNKTE}
    bereinigt: dict[str, int] = {}
    for schluessel, wert in (werte or {}).items():
        if schluessel not in erlaubt:
            continue
        if wert in (0, 1):
            bereinigt[schluessel] = int(wert)
    if not bereinigt:
        raise GeratFehler("Keine Antwort der Checkliste übergeben.")
    protokoll.checkliste = {**(protokoll.checkliste or {}), **bereinigt}
    protokoll.checkliste_bemerkung = {
        **(protokoll.checkliste_bemerkung or {}),
        **{k: str(v).strip() for k, v in (bemerkungen or {}).items() if k in erlaubt},
    }
    protokoll.save(update_fields=["checkliste", "checkliste_bemerkung"])
    return protokoll


# --- F-133: Prüfpunkte IT-Offboarding -----------------------------------------

def offboarding_abhaken(
    protokoll: Protokoll, werte: dict, ausgefuehrt_von: Konto | None = None
) -> Protokoll:
    """F-133: die 13 Prüfpunkte abhaken.

    Nur für Protokolle im Stand „scan-offen" oder „bearbeiter-offen" (F-22).
    """
    if not _stand_beantwortbar(protokoll):
        raise GeratFehler(
            "Die Prüfpunkte sind für ein abgeschlossenes Protokoll gesperrt."
        )
    erlaubt = {schluessel for schluessel, _text in Protokoll.OFFBOARDING_PUNKTE}
    bereinigt: dict[str, bool] = {}
    for schluessel, wert in (werte or {}).items():
        if schluessel not in erlaubt:
            continue
        bereinigt[schluessel] = bool(wert)
    if not bereinigt:
        raise GeratFehler("Kein Prüfpunkt übergeben.")
    protokoll.offboarding = {**(protokoll.offboarding or {}), **bereinigt}
    protokoll.save(update_fields=["offboarding"])
    return protokoll


# A-0911: offboarding_beantworten ersetzt offboarding_abhaken.
# Je Punkt: erledigt, in_klaerung oder nicht_zutreffend, dazu
# Datum, Kürzel und Bemerkung. Punkt 13 „Rückgabe im
# Hardware-Inventar dokumentiert" setzt das Tool selbst (F-133).

_OFFBOARDING_WERTE = ("erledigt", "in_klaerung", "nicht_zutreffend")


def offboarding_beantworten(
    protokoll: Protokoll, werte: dict, ausgefuehrt_von: Konto | None = None
) -> Protokoll:
    """F-133: die 13 Prüfpunkte IT-Offboarding beantworten (A-0911).

    Je Punkt: erledigt, in Klärung oder nicht zutreffend, dazu Datum,
    Kürzel und Bemerkung. Punkt 13 „Rückgabe im Hardware-Inventar
    dokumentiert" setzt das Tool selbst (F-133).

    Nur für Protokolle im Stand „scan-offen" oder „bearbeiter-offen" (F-22).
    """
    if not _stand_beantwortbar(protokoll):
        raise GeratFehler(
            "Die Prüfpunkte sind für ein abgeschlossenes Protokoll gesperrt."
        )
    if protokoll.art != Protokoll.ART_RUECKNAHME:
        raise GeratFehler(
            "Die Prüfpunkte IT-Offboarding gehören nur zu einem Rücknahmeprotokoll."
        )

    erlaubt = {schluessel for schluessel, _text in Protokoll.OFFBOARDING_PUNKTE}
    heute = jetzt_aware().date()
    bearbeiter_kuerzel = ""
    if ausgefuehrt_von is not None and getattr(ausgefuehrt_von, "person", None) is not None:
        bearbeiter_kuerzel = ausgefuehrt_von.person.kuerzel

    bereinigt: dict = {}
    for schluessel in erlaubt:
        status = (werte or {}).get(schluessel)
        if status not in _OFFBOARDING_WERTE:
            continue  # un beantwortete Punkte bleiben un beantwortet
        datum = (werte or {}).get(f"{schluessel}.datum") or (
            heute.strftime("%d.%m.%Y")
            if status in ("erledigt", "in_klaerung")
            else ""
        )
        kuerzel = (werte or {}).get(f"{schluessel}.kuerzel") or (
            bearbeiter_kuerzel if status in ("erledigt", "in_klaerung") else ""
        )
        bemerkung = (werte or {}).get(f"{schluessel}.bemerkung") or ""
        bereinigt[schluessel] = {
            "status": status,
            "datum": datum,
            "kuerzel": kuerzel,
            "bemerkung": bemerkung,
        }
    if not bereinigt:
        raise GeratFehler("Kein Prüfpunkt übergeben.")

    # Punkt 13 „Rückgabe im Hardware-Inventar dokumentiert" setzt das Tool
    # selbst (F-133): immer erledigt, unabhängig von der Eingabe.
    from stammdaten.checklisten import PUNKT_INVENTAR as p13_schluessel
    bereinigt[p13_schluessel] = {
        "status": "erledigt",
        "datum": heute.strftime("%d.%m.%Y"),
        "kuerzel": bearbeiter_kuerzel,
        "bemerkung": "",
    }

    protokoll.offboarding = {**(protokoll.offboarding or {}), **bereinigt}
    protokoll.save(update_fields=["offboarding"])
    return protokoll


# --- F-134: Fotos als Anlage ---------------------------------------------------

def _foto_erweitern(dateiname: str, content_type: str) -> str | None:
    """Dateinamen-Erweiterung für ein zulässiges Fotoformat."""
    return ERLAUBTE_FOTO_TYPEN.get((content_type or "").lower())


def _heic_als_jpeg(roh: bytes) -> bytes | None:
    """HEIC in JPEG wandeln, damit das Foto im PDF erscheint; ohne Bibliothek ``None``."""
    try:
        import pillow_heif
        from PIL import Image
        pillow_heif.register_heif_opener()
        bild = Image.open(io.BytesIO(roh)).convert("RGB")
        puffer = io.BytesIO()
        bild.save(puffer, format="JPEG", quality=88)
        return puffer.getvalue()
    except Exception:  # pragma: no cover - je nach Installation
        return None


def _kleiner_bild_punkt(content: bytes, content_type: str) -> bytes:
    """Verkleinert ein JPG oder PNG auf die PDF-Kante (Punkt).

    HEIC kann Pillow nicht zuverlässig umwandeln (Pillow < 9.2 ohne
    libheif): dann bleibt das Original, die Anlage im PDF bleibt
    trotzdem lesbar (F-134: verkleinert gespeichert, so gut es geht).
    """
    ct = (content_type or "").lower()
    if ct not in ("image/jpeg", "image/png"):
        return content
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow ist installiert
        return content
    bild = Image.open(io.BytesIO(content))
    breite, hoehe = bild.size
    if breite == 0 or hoehe == 0:
        return content
    faktor = PDF_KANTE_PUNKT / max(breite, hoehe)
    if faktor >= 1:
        return content  # schon klein genug
    neue_breite = max(1, int(breite * faktor))
    neue_hoehe = max(1, int(hoehe * faktor))
    if ct == "image/png" and bild.mode not in ("RGB", "RGBA", "L"):
        bild = bild.convert("RGB")
    elif ct == "image/jpeg" and bild.mode in ("RGBA", "LA", "P", "L"):
        bild = bild.convert("RGB")
    else:
        bild = bild.convert("RGB")
    bild = bild.resize((neue_breite, neue_hoehe), Image.Resampling.LANCZOS)
    puffer = io.BytesIO()
    if ct == "image/png":
        bild.save(puffer, format="PNG")
    else:
        bild.save(puffer, format="JPEG", quality=88)
    return puffer.getvalue()


def foto_hochladen(
    protokoll: Protokoll,
    datei,
    ausgefuehrt_von: Konto | None = None,
    inventarnummer: str = "",
) -> Protokoll:
    """F-134: Foto (JPG, PNG oder HEIC bis 10 MB) als Anlage hinter dem
    Protokoll speichern.

    Das Bild wird verkleinert in der DATEIABLAGE abgelegt; im PDF steht
    es als Anlage hinter dem Unterschriftenblock.
    Erlaubt, solange das Protokoll im Stand „scan-offen" oder
    „bearbeiter-offen" ist (F-22, F-134). Nach der Signatur gesperrt.
    """
    if not _stand_anhaenge_erlaubt(protokoll):
        raise GeratFehler(
            "Für ein abgeschlossenes Protokoll sind keine weiteren Anhänge "
            "möglich."
        )
    dateiname = getattr(datei, "name", "") or ""
    roh = datei.read(MAX_FOTO_GROESSE + 1)
    if len(roh) > MAX_FOTO_GROESSE:
        raise GeratFehler("Das Foto ist größer als 10 MB.")
    content_type = _typ_am_inhalt(roh) or ""
    erweiterung = _foto_erweitern(dateiname, content_type)
    if erweiterung is None:
        raise GeratFehler(
            "Fotoformat nicht erlaubt: JPG, PNG oder HEIC bis 10 MB."
        )
    if content_type == "image/heic":
        gewandelt = _heic_als_jpeg(roh)
        if gewandelt is not None:
            roh, content_type, erweiterung = gewandelt, "image/jpeg", ".jpg"
    try:
        verkleinert = _kleiner_bild_punkt(roh, content_type)
    except Exception as fehler:
        raise GeratFehler("Die Datei ist kein lesbares Bild.") from fehler

    # F-134: verkleinert in der DATEIABLAGE gespeichert; der Pfad steht
    # in anhaenge, das PDF lädt das Bild von dort.
    from django.core.files.storage import default_storage

    zeitstempel = jetzt_aware().strftime("%Y%m%d-%H%M%S")
    pfad = f"protokolle/{protokoll.id or 'neu'}/foto-{zeitstempel}{erweiterung}"
    pfad = default_storage.save(pfad, ContentFile(verkleinert))
    anhaenge = protokoll.anhaenge_liste()
    anhaenge.append(
        {
            "pfad": pfad,
            "inventarnummer": inventarnummer,
            "name": dateiname or f"foto{erweiterung}",
            "groesse": len(verkleinert),
            "typ": content_type,
            "hochgeladen_am": jetzt_aware().isoformat(),
        }
    )
    protokoll.anhaenge = anhaenge
    protokoll.fotos = len(anhaenge)
    fields = ["anhaenge", "fotos"]
    if getattr(protokoll, "scan_datei", None):
        fields.append("scan_datei")
    protokoll.save(update_fields=fields)
    return protokoll


# --- F-22: Scan des unterzeichneten Protokolls ---------------------------------

def scan_hochladen(
    protokoll: Protokoll,
    datei,
    ausgefuehrt_von: Konto | None = None,
) -> Protokoll:
    """F-22: hochgeladener Scan setzt das Protokoll auf „abgeschlossen".

    Nur für Protokolle im Stand „scan-offen". Danach sind Checkliste,
    Prüfpunkte und Anhänge gesperrt (F-132, F-133, F-134).
    """
    if protokoll.stand != Protokoll.STAND_SCAN_OFFEN:
        raise GeratFehler(
            "Nur ein Protokoll im Stand 'scan-offen' kann abgeschlossen "
            "werden."
        )
    roh = datei.read(MAX_FOTO_GROESSE + 1)
    if not roh:
        raise GeratFehler("Der Scan ist leer.")
    if len(roh) > MAX_FOTO_GROESSE:
        raise GeratFehler("Der Scan ist größer als 10 MB.")
    typ = _typ_am_inhalt(roh)
    if typ is None:
        raise GeratFehler("Scan nicht erlaubt: PDF, JPG, PNG oder HEIC bis 10 MB.")
    erweiterung = {"application/pdf": ".pdf", **ERLAUBTE_FOTO_TYPEN}[typ]
    zeitstempel = jetzt_aware().strftime("%Y%m%d-%H%M%S")
    pfad = f"protokolle/{protokoll.id}/scan-{zeitstempel}{erweiterung}"
    protokoll.scan_datei.save(pfad, ContentFile(roh), save=False)
    protokoll.scan_am = jetzt_aware()
    protokoll.scan_von = ausgefuehrt_von
    protokoll.stand = Protokoll.STAND_ABGESCHLOSSEN
    # F-139: Auch der Scan geht an beide Seiten, unter dem vorgesehenen Namen.
    from . import pdf as pdf_modul
    from .services import _ablage_mit_anhang
    protokoll.pdf_versand_offen = not _ablage_mit_anhang(
        protokoll, roh, pdf_modul.dateiname_protokoll(protokoll, typ), typ,
    )
    protokoll.save(
        update_fields=["scan_datei", "scan_am", "scan_von", "stand", "pdf_versand_offen"]
    )
    return protokoll


def protokoll_anlegen(
    person,
    gerat,
    datum: datetime | None = None,
    art: str = Protokoll.ART_AUSGABE,
    bearbeiter: Konto | None = None,
    rueckgabe_zu_protokoll: Protokoll | None = None,
    erzeugt_von: Konto | None = None,
    checkliste: dict | None = None,
    offboarding: dict | None = None,
) -> Protokoll:
    """M6 Teil 1 (F-130): Protokoll anlegen.

    Art „ausgabe" → FRM-001, Art „ruecknahme" → FRM-002 mit Bezug auf
    das Ausgabeprotokoll. Stand beginnt immer „scan-offen" (F-22).
    Nummer UP-JJJJ-NNNN (F-131).
    """
    from .services import _absenderzeile, _naechste_protokollnummer, position_aus_gerat, protokolltexte

    now = datum or jetzt_aware()
    if art == Protokoll.ART_RUECKNAHME:
        formular = "FRM-002"
    else:
        formular = "FRM-001"

    bearbeiter_name = ""
    if bearbeiter is not None:
        bearbeiter_name = bearbeiter.bezeichnung()
    empfaenger = ""
    if person is not None and getattr(person, "anschrift", None):
        empfaenger = str(person.anschrift).strip()

    return Protokoll.objects.create(
        nr=_naechste_protokollnummer(),
        person=person,
        geraet=gerat,
        datum=now.date() if hasattr(now, "date") else now,
        stand=Protokoll.STAND_SCAN_OFFEN,
        art=art,
        fassung="1.1",
        formularnummer=formular,
        absenderzeile=_absenderzeile(),
        positionen=[position_aus_gerat(gerat)],
        texte=protokolltexte(art),
        empfaenger_anschrift=empfaenger,
        bearbeiter=bearbeiter_name,
        checkliste=checkliste or {},
        offboarding=offboarding or {},
        rueckgabe_zu_protokoll=rueckgabe_zu_protokoll,
        erzeugt_von=erzeugt_von,
    )
