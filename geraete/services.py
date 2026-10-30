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
from stammdaten.models import Ausstattungsprofil, Kategorie, Ort, Person

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


def seriennummer_pruefen(
    hersteller: str, seriennummer: str, ausschluss_geraet: Gerat | None = None
) -> Gerat | None:
    """Gibt ein anderes Gerät mit derselben Seriennummer und demselben Hersteller zurück.

    F-10 (A-0097): Vergleich ohne Groß- und Kleinschreibung und ohne
    Leerzeichen am Rand. ``ausschluss_geraet`` wird ignoriert, z. B. beim
    Bearbeiten eines vorhandenen Geräts.
    """
    if not seriennummer or not seriennummer.strip():
        return None
    if not hersteller or not hersteller.strip():
        return None
    queryset = Gerat.objects.filter(
        hersteller__iexact=hersteller.strip(),
        seriennummer__iexact=seriennummer.strip(),
    )
    if ausschluss_geraet is not None:
        queryset = queryset.exclude(pk=ausschluss_geraet.pk)
    return queryset.order_by("pk").first()


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
    # F-10 (A-0097): dieselbe Seriennummer beim selben Hersteller wird abgelehnt,
    # ohne Groß- und Kleinschreibung und ohne Leerzeichen am Rand.
    doppelte = seriennummer_pruefen(hersteller, seriennummer)
    if doppelte is not None:
        raise GeratFehler(
            f"Seriennummer ist schon bei einem anderen Gerät hinterlegt ({doppelte.inventarnummer})."
        )
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
    erstellten = gerat.erstellt_am
    if altbestand_ohne_protokoll:
        # F-85: Import – der Vorgang „Import“ steht in der Historie.
        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_IMPORT,
            zeitpunkt=erstellten,
            erzeugt_von=erzeugt_von,
            abschliesst=True,
        )
    else:
        # F-10: Aufnahme – Vorgang „Aufnahme“ steht in der Historie.
        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_AUFNAHME,
            zeitpunkt=erstellten,
            erzeugt_von=erzeugt_von,
            abschliesst=True,
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
    zustand: int | None = None,
    zubehoer_komplett: bool = True,
    anmerkung: str = "",
    ausgefuehrt_von: Konto | None = None,
) -> Gerat:
    """Gerät ausgeben (F-20 bis F-23, F-131, M3).

    Ziel ist eine Person oder ein Ort (Arbeitsplatz, Raum, Lager).
    Status wird „In Benutzung“, Person und/oder Ort werden gesetzt.
    Ein Vorgang wird geschrieben.

    F-131 (A-0098): Der Dialog trägt „Zustand“, „Zubehör komplett“ und
    „Bemerkung“. Der Zustand geht in den Vorgang „Ausgabe“ und auf das
    Gerät. Protokoll und Signatur bleiben M6, das Protokoll-PDF folgt
    mit F-130.
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

    # F-131 (A-0098): Zustand auf das Gerät; in den Vorgang geht er
    # über die Notiz wie bei der Rückgabe (F-50).
    if zustand is not None:
        gerat.zustand = int(zustand)

    teile = []
    if zustand is not None:
        stufe = int(zustand)
        zustaende = dict(Gerat.ZUSTAENDE)
        teile.append("Zustand: " + zustaende.get(stufe, str(stufe)))
    if zubehoer_komplett is not None:
        teile.append("Zubehör komplett: " + ("Ja" if zubehoer_komplett else "Nein"))
    if anmerkung:
        teile.append(anmerkung)
    bemerkt = ", ".join(teile)

    # F-20 bis F-23: Ausgabe – Vorgang „Ausgabe“ steht in der Historie.
    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_AUSGABE,
        zeitpunkt=timezone.now(),
        erzeugt_von=ausgefuehrt_von,
        leihgabe_an=person,
        zurueck_am=None,
        notiz=bemerkt,
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
    disposition: str = "",
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

    # F-55: Grund, Datum, Verbleib.
    if not grund:
        raise GeratFehler("Grund der Ausmusterung muss angegeben werden.")
    if not datum:
        raise GeratFehler("Datum der Ausmusterung muss angegeben werden.")
    verloren = grund in ("verloren", "gestohlen")
    if not verloren and not disposition:
        raise GeratFehler("Verbleib muss angegeben werden.")

    # F-56: Löschnachweis bei Datenträgern (Fehlt das Gerät, entfällt er.)
    if gerat.kategorie.hat_datentraeger and not verloren:
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
        # F-50 (A-0097): „fehlt, Ausmusterung starten“ aus der Auswahl „Danach“
        # startet die Ausmusterung mit Grund „verloren“ (wie bisher, fehlend=True).
        return ausmustern(
            gerat,
            grund="verloren",
            datum=date.today(),
            disposition="Verlust",
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
        # F-42: Ziel „Bisherige Zuordnung“ – Gerät geht zurück zu Person/Ort.
        if gerat.person is None and gerat.ort is None:
            # Kein vorheriger Verbleib bekannt – Gerät geht ins Lager.
            gerat.status = Gerat.STATUS_AUF_LAGER
        else:
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
        reparatur_ziel=ziel,
        notiz=f"Zustand: {zustand}, Ziel: {ziel}",
        abschliesst=True,
    )
    gerat.save()
    return gerat


@transaction.atomic
def gerat_bearbeiten(
    gerat: Gerat, *, werte: dict, erzeugt_von: Konto | None = None
) -> Gerat:
    """Gerät ändern (F-15). Inventarnummer bleibt unverändert (F-12).

    A-0098 (F-40): je geändertem Feld entsteht ein Vorgang vom Typ
    „Änderung“ mit dem Feld, dem alten und dem neuen Wert
    (``aenderung_feld``, ``aenderung_alter_wert``, ``aenderung_neuer_wert``).
    Ohne Änderung entsteht kein Vorgang.
    """
    # F-58 (A-0097): Ausgemusterte Geräte sind nicht mehr änderbar.
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Ausgemusterte Geräte sind nicht mehr änderbar.")
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
    # F-10 (A-0097): dieselbe Seriennummer beim selben Hersteller wird abgelehnt.
    if "seriennummer" in werte or "hersteller" in werte:
        neue_seriennummer = werte.get("seriennummer", gerat.seriennummer) or ""
        neuer_hersteller = werte.get("hersteller", gerat.hersteller) or ""
        doppelte = seriennummer_pruefen(neuer_hersteller, neue_seriennummer, gerat)
        if doppelte is not None:
            raise GeratFehler(
                f"Seriennummer ist schon bei einem anderen Gerät hinterlegt ({doppelte.inventarnummer})."
            )
    for name, wert in werte.items():
        alter = _wert_anzeigen(gerat, name)
        neuer = _wert_anzeigen_wert(wert)
        if neuer != alter:
            Vorgang.objects.create(
                gerat=gerat,
                typ=Vorgang.TYP_AENDERUNG,
                zeitpunkt=timezone.now(),
                erzeugt_von=erzeugt_von,
                aenderung_feld=name,
                aenderung_alter_wert=alter,
                aenderung_neuer_wert=neuer,
                abschliesst=True,
            )
    for name, wert in werte.items():
        setattr(gerat, name, wert)
    gerat.save()
    return gerat


def _wert_anzeigen(gerat: Gerat, feld: str) -> str:
    """Zeigt den alten Wert eines Feldes für die Historie an (F-40, A-0098)."""
    return _wert_anzeigen_wert(getattr(gerat, feld))


def _wert_anzeigen_wert(wert) -> str:
    """Zeigt einen Feldwert für die Historie an (F-40, A-0098)."""
    if wert is None:
        return ""
    if isinstance(wert, bool):
        return "ja" if wert else "nein"
    return str(wert)


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
    """Prüfung abhaken: Datum und Kontext (F-16).

    Schreibt auch den Vorgang „Geprüft“ (F-89, AUFTRAG M4), damit
    „Zuletzt geprüft“ Datum und Konto trägt.
    """
    gerat.zuletzt_geprueft_am = timezone.now()
    gerat.zuletzt_geprueft_von = geprueft_von
    gerat.save()
    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_AENDERUNG,
        zeitpunkt=timezone.now(),
        erzeugt_von=geprueft_von,
        notiz="Geprüft bei der Erstinventur (F-89).",
        abschliesst=True,
    )
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


# --- M4 Arbeitsplätze (F-62 bis F-64, F-89) -----------------------------------

# F-62: Geräte in diesen Statuses zählen zur Ist-Ausstattung.
# Ausgemusterte und in Reparatur (außer Haus) sind nicht am Platz.
# Verliehen zählt: das Gerät ist physisch da (bei der Person am Platz).
_ERFASST = (
    Gerat.STATUS_IN_BENUTZUNG,
    Gerat.STATUS_VERLIEHEN,
    Gerat.STATUS_AUF_LAGER,
)


def gerate_am_ort(ort: Ort) -> list[Gerat]:
    """Alle erfassten Geräte an einem Ort (F-62, F-66).

    Ausgemusterte und in Reparatur stehende Geräte sind nicht am Platz.
    """
    return list(
        Gerat.objects.filter(ort=ort, status__in=_ERFASST)
        .select_related("kategorie")
        .order_by("kategorie__name", "inventarnummer")
    )


def gerate_der_person(person: Person) -> list[Gerat]:
    """Geräte, die eine Person nutzt (F-66: getrennt unter dem Platz)."""
    return list(
        Gerat.objects.filter(person=person, status__in=_ERFASST)
        .select_related("kategorie")
        .order_by("kategorie__name", "inventarnummer")
    )


@transaction.atomic
def person_alle_zuruecknehmen(
    person: Person, *, ausgefuehrt_von: Konto | None = None
) -> int:
    """Alle Geräte einer Person zurücknehmen (F-52, A-0099).

    Jedes Gerät, das noch bei der Person liegt („In Benutzung“ oder
    „Verliehen“), wird ins Lager zurückgenommen: Status „Auf Lager“,
    Person wird entfernt, Vorgang „Rückgabe“ entsteht je Gerät.
    „Auf Lager“ bleibt unverändert (dort ist die Person nicht zugeordnet).
    Gibt die Anzahl der zurückgenommenen Geräte zurück.
    """
    gerate = list(
        Gerat.objects.filter(
            person=person,
            status__in=[Gerat.STATUS_IN_BENUTZUNG, Gerat.STATUS_VERLIEHEN],
        ).order_by("inventarnummer")
    )
    for gerat in gerate:
        gerat_rueckgeben(
            gerat,
            zustand_rueckgabe=gerat.zustand,
            zubesehoer_komplett=True,
            maengel="",
            ziel="lager",
            fehlend=False,
            ausgefuehrt_von=ausgefuehrt_von,
        )
    return len(gerate)


def soll_zahlen(ort: Ort) -> list[tuple[Kategorie, int]]:
    """Soll-Ausstattung eines Ortes als Liste (Kategorie, Anzahl) (F-62).

    Ohne Profil ist das Soll leer; dann ist jeder erfasste Eintrag
    „mehr als Soll“ und nichts fehlt.
    """
    if ort.typ != Ort.TYP_ARBEITSPLATZ or ort.profil is None:
        return []
    return [
        (pos.kategorie, pos.anzahl)
        for pos in ort.profil.positionen.select_related("kategorie")
        .order_by("kategorie__name")
    ]


def soll_ist_abgleich(ort: Ort) -> dict:
    """Soll-Ist-Abgleich je Arbeitsplatz (F-62).

    Ergebnis: „vollstaendig“, „unvollstaendig“ oder „mehr-als-soll“,
    jeweils mit Fehlliste („fehlt: n x Kategorie“) und Mehrliste
    („mehr: n x Kategorie“).
    """
    soll = dict((k, a) for k, a in soll_zahlen(ort))
    ist: dict[Kategorie, int] = {}
    for gerat in gerate_am_ort(ort):
        ist[gerat.kategorie] = ist.get(gerat.kategorie, 0) + 1

    fehlend: list[tuple[Kategorie, int]] = []
    zuviel: list[tuple[Kategorie, int]] = []
    for kategorie, anzahl in soll.items():
        hat = ist.get(kategorie, 0)
        if hat < anzahl:
            fehlend.append((kategorie, anzahl - hat))
        elif hat > anzahl:
            zuviel.append((kategorie, hat - anzahl))
    for kategorie, hat in ist.items():
        if kategorie not in soll and hat > 0:
            zuviel.append((kategorie, hat))
    fehlend.sort(key=lambda x: x[0].name)
    zuviel.sort(key=lambda x: x[0].name)

    if fehlend:
        ergebnis = "unvollstaendig"
    elif zuviel:
        ergebnis = "mehr-als-soll"
    else:
        ergebnis = "vollstaendig"

    return {
        "ergebnis": ergebnis,
        "fehlend": fehlend,
        "zuviel": zuviel,
        "soll": soll,
        "ist": ist,
    }


def bedarf_uebersicht(orte: list[Ort] | None = None) -> dict:
    """Bedarf: fehlende Ausstattung je Kategorie mit Lagerbestand (F-63).

    Ergebnis: Zeilen je Kategorie mit Summe „fehlt“ und Lagerbestand
    („Auf Lager“ an einem Lagerort), sortiert nach Kategorie.
    """
    if orte is None:
        orte = list(
            Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ).order_by("kennung")
        )
    summe: dict[Kategorie, int] = {}
    for ort in orte:
        if ort.typ != Ort.TYP_ARBEITSPLATZ:
            continue
        abgleich = soll_ist_abgleich(ort)
        for kategorie, mangelt in abgleich["fehlend"]:
            summe[kategorie] = summe.get(kategorie, 0) + mangelt
    summe = dict(sorted(summe.items(), key=lambda x: x[0].name))

    lager_orte = Ort.objects.filter(typ=Ort.TYP_LAGER)
    lagerbestand: dict[Kategorie, int] = {}
    for kategorie in summe:
        lagerbestand[kategorie] = (
            Gerat.objects.filter(
                kategorie=kategorie,
                status=Gerat.STATUS_AUF_LAGER,
                ort__in=lager_orte,
            ).count()
        )
    return {"summe": summe, "lagerbestand": lagerbestand}


# --- Erstinventur (F-89, AUFTRAG M4) ------------------------------------------

def fortschritt_je_ort(orte: list[Ort] | None = None) -> list[dict]:
    """Fortschritt: geprüfte Geräte / alle Geräte, auch je Ort (F-89).

    Geprüft = „Zuletzt geprüft“ gesetzt und das Gerät ist erfasst
    (nicht ausgemustert, nicht in Reparatur).
    """
    if orte is None:
        orte = list(
            Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ).order_by("kennung")
        )
    zeilen: list[dict] = []
    for ort in orte:
        alle = list(Gerat.objects.filter(ort=ort, status__in=_ERFASST))
        geprueft = [g for g in alle if g.zuletzt_geprueft_am is not None]
        zeilen.append(
            {
                "ort": ort,
                "geprueft": len(geprueft),
                "alle": len(alle),
                "vollstaendig": bool(alle) and len(geprueft) == len(alle),
            }
        )
    return zeilen


def fortschritt_des_orts(ort: Ort) -> dict:
    """Fortschritt eines einzelnen Orts (F-89, Markierung ``inventur-fortschritt``).

    Geprüft = „Zuletzt geprüft“ gesetzt und das Gerät ist erfasst
    (nicht ausgemustert, nicht in Reparatur).
    """
    alle = list(Gerat.objects.filter(ort=ort, status__in=_ERFASST))
    geprueft = [g for g in alle if g.zuletzt_geprueft_am is not None]
    return {
        "ort": ort,
        "geprueft": len(geprueft),
        "alle": len(alle),
        "vollstaendig": bool(alle) and len(geprueft) == len(alle),
    }


# --- Raumplan (F-65 bis F-69, A-0076 Teil 1) ------------------------------------


def plan_auswahl() -> list[dict]:
    """Alle Pläne je Standort und Etage, sortiert (F-65)."""
    from stammdaten.models import Plan

    return list(Plan.objects.order_by("standort", "etage"))


def plan_finde(standort: str, etage: str):
    """Plan nach Standort und Etage, sonst None."""
    from stammdaten.models import Plan

    return Plan.objects.filter(standort=standort, etage=etage).first()


def plaetze_des_plans(plan) -> list[dict]:
    """Plätze eines Plans mit Soll-Ist-Ergebnis, sortiert nach Kennung
    (F-65, F-66): jede Zeile trägt Ort und Abgleich.
    """
    zeilen = []
    for ort in Ort.objects.filter(
        typ=Ort.TYP_ARBEITSPLATZ, plan_id=plan.id
    ).order_by("kennung"):
        zeilen.append({"ort": ort, "abgleich": soll_ist_abgleich(ort)})
    return zeilen


def raumorte_des_plans(plan) -> list[Ort]:
    """Räume eines Plans, sortiert nach Kennung (F-68)."""
    return list(
        Ort.objects.filter(
            typ=Ort.TYP_RAUM, plan_id=plan.id
        ).order_by("kennung")
    )


def ohne_position(plan) -> list[dict]:
    """Plätze eines Plans ohne Position (F-67, Markierung ``ohne-position``)."""
    return [
        zeile
        for zeile in plaetze_des_plans(plan)
        if zeile["ort"].position_x is None or zeile["ort"].position_y is None
    ]


def grundriss_pfad(plan) -> str:
    """Pfad der Grundriss-Datei in der DATEIABLAGE (F-65)."""
    return plan.grundriss
