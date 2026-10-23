"""Service-Schicht für Geräte-Vorgänge (M2 Bestand, M3 Lebenszyklus).

AGENTS.md: „Ein Vorgang = eine Funktion, eine Transaktion. Statuswechsel
nur über die Service-Schicht, nicht in Views oder Templates.“

F-10 bis F-14 (Aufnahme), F-15 (Bearbeiten), F-16 (Prüfung),
F-20 bis F-23 (Ausgabe), F-41 (Umzug), F-42 (Reparatur),
F-50 bis F-53 (Rückgabe, Austritt), F-55 bis F-58 (Ausmusterung, Archiv),
F-84 bis F-88 (Importkonflikte, Datenlücken).
"""
from __future__ import annotations

from datetime import date

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from konten.models import Konto
from stammdaten.models import Kategorie, Ort, Person

from .models import Gerat, GeratKonflikt, Vorgang


class GeratFehler(ValueError):
    """Fehler eines Gerät-Vorgangs; die Meldung darf in die Oberfläche."""


# --- Inventarnummer ---------------------------------------------------------

def naechste_inventarnummer() -> str:
    """Nächste freie Inventarnummer im Format WMC-00001 (O-03)."""
    hoechst = Gerat.objects.aggregate(m=Max("inventarnummer"))["m"]
    zaehler = 1
    if hoechst and str(hoechst).startswith("WMC-"):
        try:
            zaehler = int(str(hoechst)[4:]) + 1
        except ValueError:
            zaehler = 1
    return f"WMC-{zaehler:05d}"


# --- Vorgänge ---------------------------------------------------------------


@transaction.atomic
def gerat_anlegen(
    *,
    kategorie: Kategorie,
    hersteller: str,
    modell: str,
    seriennummer: str = "",
    zustand: int = Gerat.ZUSTAND_GUT,
    leihpool: bool = False,
    person: Person | None = None,
    ort: Ort | None = None,
    geraetename: str = "",
    standardzuehoer: str = "",
    technische_daten: str = "",
    kaufdatum=None,
    kaufpreis_netto=None,
    lieferant: str = "",
    rechnungsnummer: str = "",
    garantie_bis=None,
    notiz: str = "",
    altbestand_ohne_protokoll: bool = False,
    zustand_ungeprueft: bool = False,
    kaufdatum_nicht_ermittelbar: bool = False,
    garantie_nicht_ermittelbar: bool = False,
    erzeugt_von: Konto | None = None,
    pruefen: bool = True,
) -> Gerat:
    """Neues Gerät anlegen (F-11, F-12, F-13, F-14).

    Inventarnummer wird automatisch vergeben und ist danach unveränderlich.
    Status beginnt bei „Auf Lager“, außer eine Person ist benannt
    (dann „In Benutzung“).
    """
    if person is not None and ort is not None:
        raise GeratFehler("Ein Gerät steht bei einer Person oder an einem Ort, nicht beides.")
    status = (
        Gerat.STATUS_IN_BENUTZUNG if person is not None else Gerat.STATUS_AUF_LAGER
    )
    gerat = Gerat.objects.create(
        inventarnummer=naechste_inventarnummer(),
        kategorie=kategorie,
        hersteller=hersteller.strip(),
        modell=modell.strip(),
        seriennummer=seriennummer.strip(),
        status=status,
        zustand=zustand,
        leihpool=leihpool,
        person=person,
        ort=ort,
        geraetename=geraetename.strip(),
        standardzuehoer=standardzuehoer,
        technische_daten=technische_daten,
        kaufdatum=kaufdatum,
        kaufpreis_netto=kaufpreis_netto,
        lieferant=lieferant.strip(),
        rechnungsnummer=rechnungsnummer.strip(),
        garantie_bis=garantie_bis,
        notiz=notiz,
        altbestand_ohne_protokoll=altbestand_ohne_protokoll,
        zustand_ungeprueft=zustand_ungeprueft,
        kaufdatum_nicht_ermittelbar=kaufdatum_nicht_ermittelbar,
        garantie_nicht_ermittelbar=garantie_nicht_ermittelbar,
        erstellt_am=timezone.now(),
        erstellt_von=erzeugt_von,
    )
    return gerat


@transaction.atomic
def gerat_vergeben(
    gerat: Gerat, person: Person, *, erzeugt_von: Konto | None = None
) -> Gerat:
    """Gerät an eine Person vergeben (F-45, M2/M3).

    Status wird „In Benutzer“, Person ist gesetzt, Ort ist leer.
    """
    gerat.person = person
    gerat.ort = None
    gerat.status = Gerat.STATUS_IN_BENUTZUNG
    gerat.save()
    return gerat


@transaction.atomic
def gerat_ausgeben(
    gerat: Gerat,
    ziel: Person | Ort,
    *,
    zurueck_am: date | None = None,
    anmerkung: str = "",
    ausgefuehrt_von: Konto | None = None,
) -> Gerat:
    """Gerät ausgeben (F-20 bis F-23, M3).

    Ziel ist eine Person oder ein Ort (Arbeitsplatz, Raum, Lager).
    Status wird „In Benutzung“, Person und/oder Ort werden gesetzt.
    Ein Vorgang wird geschrieben.
    """
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Ausgemusterte Geräte können nicht ausgegeben werden.")
    if gerat.status == Gerat.STATUS_IN_REPARATUR:
        raise GeratFehler("Geräte in Reparatur können nicht ausgegeben werden.")

    person = ziel if isinstance(ziel, Person) else None
    ort = ziel if isinstance(ziel, Ort) else None
    if person is None and ort is None:
        raise GeratFehler("Ausgabeziel muss eine Person oder ein Ort sein.")

    # F-20: Status wird „In Benutzung“
    gerat.status = Gerat.STATUS_IN_BENUTZUNG
    gerat.person = person
    gerat.ort = ort

    # F-23: Ausgabe an einen Ort — kein Protokoll nötig, aber Vorgang
    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_AENDERUNG if ort is not None and person is None else Vorgang.TYP_AENDERUNG,
        zeitpunkt=timezone.now(),
        erzeugt_von=ausgefuehrt_von,
        leihgabe_an=person,
        zurueck_am=zurueck_am,
        notiz=anmerkung,
        abschliesst=True,
    )
    gerat.save()
    return gerat


@transaction.atomic
def ausmustern(
    gerat: Gerat,
    *,
    grund: str,
    datum: date,
    disposition: str,
    loeschung_art: str = "",
    loeschung_nachweis: str = "",
    bestaetigt_gemeldt: bool = False,
    ausgefuehrt_von: Konto | None = None,
) -> Gerat:
    """Gerät ausmustern (F-55 bis F-58, M3).

    F-55: Grund (defekt, veraltet, verkauft, verloren, gestohlen), Datum, Verbleib.
    F-56: Löschnachweis bei Datenträgern (Art der Löschung, Nachweis).
    F-57: Verlust und Diebstahl (Pflichtbestätigung, dass der Vorfall gemeldet wurde).
    F-58: Archiv (Ausgemusterte Geräte bleiben lesbar und sind nicht mehr änderbar).
    """
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Gerät ist bereits ausgemustert.")

    # F-55: Grund, Datum, Verbleib
    if not grund:
        raise GeratFehler("Grund der Ausmusterung muss angegeben werden.")
    if not datum:
        raise GeratFehler("Datum der Ausmusterung muss angegeben werden.")

    # F-56: Löschnachweis bei Datenträgern
    if gerat.kategorie.hat_datentraeger:
        if not loeschung_art:
            raise GeratFehler("Art der Löschung muss angegeben werden (F-56).")
        if not loeschung_nachweis:
            raise GeratFehler("Nachweis der Löschung muss angegeben werden (F-56).")

    # F-57: Verlust und Diebstahl
    if grund in ("verloren", "gestohlen"):
        if not bestaetigt_gemeldt:
            raise GeratFehler("Pflichtbestätigung, dass der Vorfall gemeldet wurde (F-57).")

    gerat.status = Gerat.STATUS_AUSGEMUSTERT
    gerat.person = None
    gerat.ort = None

    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_AUSMUSTERUNG,
        zeitpunkt=timezone.now(),
        erzeugt_von=ausgefuehrt_von,
        ausmusterung_grund=grund,
        ausmusterung_datum=datum,
        ausmusterung_disposition=disposition,
        notiz=f"Löschen: {loeschung_art}, Nachweis: {loeschung_nachweis}, Gemeldet: {bestaetigt_gemeldt}",
        abschliesst=True,
    )
    gerat.save()
    return gerat


@transaction.atomic
def gerat_rueckgeben(
    gerat: Gerat,
    *,
    zustand_rueckgabe: int = Gerat.ZUSTAND_GUT,
    zubesehoer_komplett: bool = True,
    maengel: str = "",
    ziel: str = "lager",  # "lager" oder "reparatur"
    fehlend: bool = False,
    ausgefuehrt_von: Konto | None = None,
) -> Gerat:
    """Gerät zurückgeben (F-50, F-58, M3).

    Status wird „Auf Lager“, Person wird entfernt.
    Wenn fehlend=True, startet die Ausmusterung mit Grund „verloren“.
    """
    if gerat.status not in (Gerat.STATUS_IN_BENUTZUNG, Gerat.STATUS_VERLIEHEN):
        raise GeratFehler("Nur Geräte in Benutzung oder verliehen können zurückgegeben werden.")

    # F-50: Zustand bei Rückgabe, Zubehör komplett, Mängel
    gerat.zustand = zustand_rueckgabe

    if fehlend:
        # F-50: „Fehlt“ startet die Ausmusterung mit Grund „verloren“
        return ausmustern(
            gerat,
            grund="verloren",
            datum=date.today(),
            disposition="Verlust",
            loeschung_art="physisch zerstört durch Dienstleister",
            loeschung_nachweis="Verlustmeldung",
            bestaetigt_gemeldt=True,
            ausgefuehrt_von=ausgefuehrt_von,
        )

    if ziel == "reparatur":
        # F-50: Ziel Reparatur
        gerat.status = Gerat.STATUS_IN_REPARATUR
    else:
        # F-50: Ziel Lager
        gerat.status = Gerat.STATUS_AUF_LAGER

    gerat.person = None
    gerat.ort = None

    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_RUECKGABE,
        zeitpunkt=timezone.now(),
        erzeugt_von=ausgefuehrt_von,
        notiz=f"Zustand: {zustand_rueckgabe}, Zubehör komplett: {zubesehoer_komplett}, Mängel: {maengel}",
        abschliesst=True,
    )
    gerat.save()
    return gerat


@transaction.atomic
def gerat_umziehen(
    gerat: Gerat,
    ziel_ort: Ort,
    *,
    ausgefuehrt_von: Konto | None = None,
) -> Gerat:
    """Gerät umziehen (F-41, M3).

    Geräte in Benutzung wechseln den Arbeitsplatz oder Raum ohne Personenwechsel.
    """
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Ausgemusterte Geräte können nicht umgezogen werden.")
    if gerat.status not in (Gerat.STATUS_IN_BENUTZUNG, Gerat.STATUS_AUF_LAGER):
        raise GeratFehler("Nur Geräte in Benutzung oder auf Lager können umgezogen werden.")

    alter_ort = gerat.ort
    gerat.ort = ziel_ort

    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_UMZUG,
        zeitpunkt=timezone.now(),
        erzeugt_von=ausgefuehrt_von,
        umzug_ziel_ort=ziel_ort,
        notiz=f"Umzug von {alter_ort.kennung if alter_ort else 'Lager'} zu {ziel_ort.kennung}",
        abschliesst=True,
    )
    gerat.save()
    return gerat


@transaction.atomic
def gerat_in_reparatur_geschickt(
    gerat: Gerat,
    *,
    dienstleister: str,
    vorgangsnummer: str,
    notiz: str,
    ausgefuehrt_von: Konto | None = None,
) -> Gerat:
    """Reparatur starten (F-42, M3).

    Start mit Dienstleister, Vorgangsnummer und Notiz.
    """
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Ausgemusterte Geräte können nicht repariert werden.")
    if gerat.status not in (Gerat.STATUS_AUF_LAGER, Gerat.STATUS_IN_BENUTZUNG):
        raise GeratFehler("Nur Geräte auf Lager oder in Benutzung können repariert werden.")

    gerat.status = Gerat.STATUS_IN_REPARATUR

    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_REPARATUR,
        zeitpunkt=timezone.now(),
        erzeugt_von=ausgefuehrt_von,
        reperatur_anleitung=f"Dienstleister: {dienstleister}, Vorgangsnummer: {vorgangsnummer}, Notiz: {notiz}",
        abschliesst=False,
    )
    gerat.save()
    return gerat


@transaction.atomic
def gerat_reparatur_fertig(
    gerat: Gerat,
    *,
    zustand: int,
    ziel: str,  # "lager" oder "zuordnung"
    kosten: float | None = None,
    beleg: str = "",
    ausgefuehrt_von: Konto | None = None,
) -> Gerat:
    """Reparatur abschließen (F-42, M3).

    Abschluss mit neuem Zustand und Ziel „bisherige Zuordnung“ oder „Lager“.
    """
    if gerat.status != Gerat.STATUS_IN_REPARATUR:
        raise GeratFehler("Nur Geräte in Reparatur können repariert werden.")

    gerat.zustand = zustand

    if ziel == "zuordnung":
        # F-42: Ziel „bisherige Zuordnung“
        gerat.status = Gerat.STATUS_IN_BENUTZUNG
    else:
        # F-42: Ziel „Lager“
        gerat.status = Gerat.STATUS_AUF_LAGER
        gerat.person = None
        gerat.ort = None

    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_REPARATUR,
        zeitpunkt=timezone.now(),
        erzeugt_von=ausgefuehrt_von,
        reparatur_kosten=kosten,
        reparatur_beleg=beleg,
        notiz=f"Zustand: {zustand}, Ziel: {ziel}",
        abschliesst=True,
    )
    gerat.save()
    return gerat


@transaction.atomic
def gerat_bearbeiten(
    gerat: Gerat, *, werte: dict, erzeugt_von: Konto | None = None
) -> Gerat:
    """Gerät ändern (F-15). Inventarnummer bleibt unverändert (F-12)."""
    zulassig = {
        "kategorie", "hersteller", "modell", "seriennummer", "zustand",
        "leihpool", "person", "ort", "geraetename", "standardzuehoer",
        "technische_daten", "kaufdatum", "kaufpreis_netto", "lieferant",
        "rechnungsnummer", "garantie_bis", "notiz",
        "kaufdatum_nicht_ermittelbar", "garantie_nicht_ermittelbar",
    }
    unbekannt = set(werte) - zulassig
    if unbekannt:
        raise GeratFehler(
            "Diese Angaben kann die App nicht ändern: " + ", ".join(sorted(unbekannt))
        )
    for name, wert in werte.items():
        if name in ("hersteller", "modell", "seriennummer", "geraetename",
                    "lieferant", "rechnungsnummer", "standardzuehoer",
                    "technische_daten", "notiz") and wert is not None:
            werte[name] = wert.strip() if isinstance(wert, str) else wert
    if werte.get("person") is not None and werte.get("ort") is not None and \
            werte.get("person") and werte.get("ort"):
        raise GeratFehler("Ein Gerät steht bei einer Person oder an einem Ort, nicht beides.")
    for name, wert in werte.items():
        setattr(gerat, name, wert)
    gerat.save()
    return gerat


@transaction.atomic
def statuswechsel(
    gerat: Gerat, neuer_status: str, *,
    person: Person | None = None,
    ort: Ort | None = None,
    anmerkung: str = "",
    ausgefuehrt_von: Konto | None = None,
) -> Gerat:
    """Statuswechsel als Vorgang (Kapitel 4; hier: Lager, Person, Ort).

    Die ausführliche Vorgangshistorie (Protokoll) ist Teil von M3/M4;
    bis dahin gilt der Statuswechsel als Quelle (F-09).
    """
    if neuer_status not in dict(Gerat.STATUSES):
        raise GeratFehler(f"Unbekannter Status: {neuer_status}")
    if neuer_status == Gerat.STATUS_IN_BENUTZUNG and person is None:
        raise GeratFehler("Für „In Benutzung“ muss eine Person benannt sein.")
    gerat.status = neuer_status
    if neuer_status in (Gerat.STATUS_AUF_LAGER, Gerat.STATUS_IN_BENUTZUNG,
                        Gerat.STATUS_IN_REPARATUR, Gerat.STATUS_VERLIEHEN):
        if neuer_status == Gerat.STATUS_IN_BENUTZUNG:
            gerat.person = person
            gerat.ort = None
        else:
            gerat.person = None
            gerat.ort = ort
    else:  # ausgemustert
        gerat.person = None
        gerat.ort = None
    gerat.save()
    return gerat


# --- Prüfung (F-16) ----------------------------------------------------------

@transaction.atomic
def gerat_pruefen(gerat: Gerat, geprueft_von: Konto) -> Gerat:
    """Prüfung abhaken: Datum und Kontext (F-16)."""
    gerat.zuletzt_geprueft_am = timezone.now()
    gerat.zuletzt_geprueft_von = geprueft_von
    gerat.save()
    return gerat


# --- Importkonflikte (F-84, F-86, F-88) ---------------------------------------

@transaction.atomic
def konflikt_anlegen(
    gerat: Gerat, feld: str, alter_wert: str, neuer_wert: str, herkunft: str = ""
) -> GeratKonflikt:
    """Offenen Importkonflikt anlegen (F-86, F-88)."""
    return GeratKonflikt.objects.create(
        gerat=gerat, feld=feld, alter_wert=alter_wert,
        neuer_wert=neuer_wert, herkunft=herkunft, offen=True,
        erzeugt_am=timezone.now(),
    )


@transaction.atomic
def konflikt_loesen(
    konflikt: GeratKonflikt, nehmen: str, ausgefuehrt_von: Konto | None = None
) -> GeratKonflikt:
    """Konflikt lösen: „alten Wert behalten“ oder „neuen Wert übernehmen“ (F-86)."""
    if nehmen not in ("alt", "neu"):
        raise GeratFehler("Ein Konflikt wird gelöst, indem der alte Wert behalten oder der neue Wert übernommen wird.")
    if nehmen == "neu":
        setattr(konflikt.gerat, konflikt.feld, konflikt.neuer_wert)
        konflikt.gerat.save()
    konflikt.offen = False
    konflikt.save()
    return konflikt


def offene_konflikte_fuer(gerat: Gerat) -> list[GeratKonflikt]:
    return list(GeratKonflikt.objects.filter(gerat=gerat, offen=True))


def unvollstaendige_geraete() -> list[Gerat]:
    """Arbeitsliste: Geräte mit Datenlücken oder offenem Konflikt (F-88)."""
    ids = set(
        GeratKonflikt.objects.filter(offen=True).values_list("gerat_id", flat=True)
    )
    auswahl = list(Gerat.objects.all())
    return [g for g in auswahl if g.ist_unvollstaendig() or g.pk in ids]
