"""Service-Schicht für Geräte-Vorgänge (M2 Bestand, M3 Lebenszyklus).

AGENTS.md: „Ein Vorgang = eine Funktion, eine Transaktion. Statuswechsel
nur über die Service-Schicht, nicht in Views oder Templates."

F-10 bis F-14 (Aufnahme), F-15 (Bearbeiten), F-16 (Prüfung),
F-20 bis F-23 (Ausgabe), F-41 (Umzug), F-42 (Reparatur),
F-50 bis F-53 (Rückgabe, Austritt), F-55 bis F-58 (Ausmusterung, Archiv),
F-84 bis F-88 (Importkonflikte, Datenlücken).
"""
from __future__ import annotations

import os
from datetime import date

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from konten.models import Konto
from stammdaten.models import Ausstattungsprofil, Kategorie, Ort, Person, Einstellungen

from .models import Gerat, GeratKonflikt, Importlauf, Leihe, Protokoll, Vorgang
from konten.zeit import jetzt_wie_im_entwicklungsmodus


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
    Status beginnt bei „Auf Lager", außer eine Person ist benannt
    (dann „In Benutzung").
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
        # F-85: Import – der Vorgang „Import" steht in der Historie.
        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_IMPORT,
            zeitpunkt=erstellten,
            erzeugt_von=erzeugt_von,
            abschliesst=True,
        )
    else:
        # F-10: Aufnahme – Vorgang „Aufnahme" steht in der Historie.
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

    Status wird „In Benutzer", Person ist gesetzt, Ort ist leer.
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
    ziel_ort: Ort | None = None,
    zustand: int | None = None,
    zubehoer_komplett: bool = True,
    anmerkung: str = "",
    ausgefuehrt_von: Konto | None = None,
    unterschrift: str = "papier",
) -> Gerat:
    """Gerät ausgeben (F-20 bis F-23, F-131, M3).

    Ziel ist eine Person oder ein Ort (Arbeitsplatz, Raum, Lager).
    Status wird „In Benutzung", Person und/oder Ort werden gesetzt.
    Ein Vorgang wird geschrieben.

    F-131 (A-0098): Der Dialog trägt „Zustand", „Zubehör komplett" und
    „Bemerkung". Der Zustand geht in den Vorgang „Ausgabe" und auf das
    Gerät. Protokoll und Signatur bleiben M6, das Protokoll-PDF folgt
    mit F-130.

    A-0127: Unterschrift. Bei „tool" bleibt das Gerät „Auf Lager",
    Protokoll auf „bearbeiter-offen"; Status, Person und Ort kommen
    erst mit der Signatur. Bei „papier" wie bisher: sofort „In Benutzung".

    A-0128 (F-20): ``ziel_ort`` ist der Arbeitsplatz, wenn ``ziel``
    eine Person ist. Beides zusammen ist erlaubt.
    """
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Ausgemusterte Geräte können nicht ausgegeben werden.")
    if gerat.status == Gerat.STATUS_IN_REPARATUR:
        raise GeratFehler("Geräte in Reparatur können nicht ausgegeben werden.")

    # F-20: Reservierte Geräte sind nicht wählbar
    if _gerat_ist_reserviert(gerat):
        raise GeratFehler("Gerät ist reserviert und kann nicht ausgegeben werden (F-20).")

    person = ziel if isinstance(ziel, Person) else None
    ort = ziel if isinstance(ziel, Ort) else ziel_ort
    if person is None and ort is None:
        raise GeratFehler("Ausgabeziel muss eine Person oder ein Ort sein.")

    # A-0127: Unterschrift „tool" – Gerät bleibt „Auf Lager",
    # Protokoll auf „bearbeiter-offen". Status, Person und Ort kommen
    # erst mit der Signatur in protokoll_bearbeiter_signieren.
    if person is not None and unterschrift == "tool":
        # A-0128: Zweite Ausgabe abgelehnt, solange ein Protokoll
        # auf "bearbeiter-offen" steht (F-21).
        if Protokoll.objects.filter(
            geraet=gerat, stand=Protokoll.STAND_BEARBEITER_OFFEN
        ).exists():
            raise GeratFehler(
                "Für dieses Gerät steht bereits ein offenes Protokoll. "
                "Eine weitere Ausgabe ist solange nicht möglich (F-21)."
            )
        _protokoll_erstellen(
            person=person,
            gerat=gerat,
            art=Protokoll.ART_AUSGABE,
            bearbeiter=(
                ausgefuehrt_von.bezeichnung() if ausgefuehrt_von is not None else ""
            ),
            erzeugt_von=ausgefuehrt_von,
            stand=Protokoll.STAND_BEARBEITER_OFFEN,
            unterschrift_art="tool",
            ort_ziel=ort,
        )
        gerat.save()
        return gerat

    # F-20: Status wird „In Benutzung"
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

    # F-20 bis F-23: Ausgabe – Vorgang „Ausgabe" steht in der Historie.
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
    # A-0123 (M6 Teil 1): F-130, F-131, F-22 — Protokoll in der
    # Service-Schicht bei Ausgabe an eine Person. Stand ist „scan-offen";
    # das PDF entsteht erst, wenn die Checkliste beantwortet ist (F-132).
    if person is not None:
        _protokoll_erstellen(
            person=person,
            gerat=gerat,
            art=Protokoll.ART_AUSGABE,
            bearbeiter=(
                ausgefuehrt_von.bezeichnung() if ausgefuehrt_von is not None else ""
            ),
            erzeugt_von=ausgefuehrt_von,
        )
    gerat.save()
    return gerat


def _protokoll_erstellen(
    person: Person,
    gerat: Gerat,
    art: str = Protokoll.ART_AUSGABE,
    bearbeiter: str = "",
    erzeugt_von: Konto | None = None,
    rueckgabe_zu_protokoll: Protokoll | None = None,
    checkliste: dict | None = None,
    offboarding: dict | None = None,
    stand: str = Protokoll.STAND_SCAN_OFFEN,
    unterschrift_art: str = "papier",
    leihe: "Leihe | None" = None,
    ort_ziel: "Ort | None" = None,
) -> Protokoll:
    """A-0123 (M6 Teil 1): Protokoll in der Service-Schicht anlegen (F-130).

    Stand beginnt immer „scan-offen" (F-22), Nummer UP-JJJJ-NNNN (F-131).
    Art „ausgabe" → FRM-001, Art „ruecknahme" → FRM-002 mit Bezug auf
    das Ausgabeprotokoll (Kapitel 5).

    A-0127: Bei Unterschrift „tool" beginnt das Protokoll auf
    „bearbeiter-offen".

    A-0128: ``unterschrift_art`` wird beim Anlegen geschrieben (F-30).
    Bei Verleih (F-30, F-33): ``leihe`` verweist auf die Leihe,
    zu der das Protokoll gehört. Bei Ausgabe (F-20, F-21):
    ``ort_ziel`` ist der Arbeitsort/Zielort, der beim Signieren
    auf das Gerät gesetzt wird.
    """
    return Protokoll.objects.create(
        nr=_naechste_protokollnummer(),
        person=person,
        geraet=gerat,
        datum=timezone.now().date(),
        stand=stand,
        art=art,
        fassung="1.0",
        formularnummer=(
            "FRM-002" if art == Protokoll.ART_RUECKNAHME else "FRM-001"
        ),
        absenderzeile="Wamocon GmbH · IT",
        empfaenger_anschrift=str(person.anschrift).strip()
        if getattr(person, "anschrift", None)
        else "",
        bearbeiter=bearbeiter,
        checkliste=checkliste or {},
        offboarding=offboarding or {},
        rueckgabe_zu_protokoll=rueckgabe_zu_protokoll,
        erzeugt_von=erzeugt_von,
        unterschrift_art=unterschrift_art,
        leihe=leihe,
        ort_ziel=ort_ziel,
    )


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

    Status wird „Auf Lager", Person wird entfernt.
    Wenn fehlend=True, startet die Ausmusterung mit Grund „verloren".
    """
    if gerat.status not in (Gerat.STATUS_IN_BENUTZUNG, Gerat.STATUS_VERLIEHEN):
        raise GeratFehler("Nur Geräte in Benutzung oder verliehen können zurückgegeben werden.")

    # F-50: Zustand bei Rückgabe, Zubehör komplett, Mängel
    gerat.zustand = zustand_rueckgabe

    if fehlend:
        # F-50 (A-0097): „fehlt, Ausmusterung starten" aus der Auswahl „Danach"
        # startet die Ausmusterung mit Grund „verloren" (wie bisher, fehlend=True).
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

    # A-0123 (M6 Teil 1): F-130, F-131, F-22 — Protokoll in der
    # Service-Schicht bei Rücknahme. Stand ist „scan-offen"; der Bezug
    # auf das Ausgabeprotokoll trägt die Nummer (FRM-002, Kapitel 5).
    person = gerat.person
    if person is not None:
        ausgabe_protokoll = (
            Protokoll.objects.filter(
                geraet=gerat, person=person, art=Protokoll.ART_AUSGABE
            )
            .order_by("-datum", "-id")
            .first()
        )
        _protokoll_erstellen(
            person=person,
            gerat=gerat,
            art=Protokoll.ART_RUECKNAHME,
            bearbeiter=(
                ausgefuehrt_von.bezeichnung() if ausgefuehrt_von is not None else ""
            ),
            erzeugt_von=ausgefuehrt_von,
            rueckgabe_zu_protokoll=ausgabe_protokoll,
            offboarding=_offboarding_vorbelegung(gerat, person),
        )

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


def _offboarding_vorbelegung(gerat: Gerat, person: Person) -> dict:
    """FRM-002 Abschnitt 3: Vorbelegung der 13 Prüfpunkte IT-Offboarding.

    Rücknahme bei Austritt (Person hat ein Austrittsdatum): keine Option,
    außer Punkt 13 „Rückgabe im Hardware-Inventar dokumentiert" = erledigt.
    Jede andere Rückgabe: Punkt 1 = erledigt, Punkt 13 = erledigt,
    alle übrigen = nicht zutreffend.
    """
    punkte = dict(Protokoll.OFFBOARDING_PUNKTE)
    schluessel = list(punkte)
    # Alle 13 Punkte anlegen, Standard: nicht abgehakt (False)
    vorbelegung: dict[str, bool] = {k: False for k in schluessel}
    if person is not None and getattr(person, "austritt", None):
        vorbelegung[schluessel[-1]] = True  # Punkt 13: erledigt
    else:
        vorbelegung[schluessel[0]] = True   # Punkt 1: erledigt
        vorbelegung[schluessel[-1]] = True  # Punkt 13: erledigt
    return vorbelegung


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

    Abschluss mit neuem Zustand und Ziel „bisherige Zuordnung" oder „Lager".
    """
    if gerat.status != Gerat.STATUS_IN_REPARATUR:
        raise GeratFehler("Nur Geräte in Reparatur können repariert werden.")

    gerat.zustand = zustand

    if ziel == "zuordnung":
        # F-42: Ziel „Bisherige Zuordnung" – Gerät geht zurück zu Person/Ort.
        if gerat.person is None and gerat.ort is None:
            # Kein vorheriger Verbleib bekannt – Gerät geht ins Lager.
            gerat.status = Gerat.STATUS_AUF_LAGER
        else:
            gerat.status = Gerat.STATUS_IN_BENUTZUNG
    else:
        # F-42: Ziel „Lager"
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
    „Änderung" mit dem Feld, dem alten und dem neuen Wert
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
        raise GeratFehler("Für In Benutzung muss eine Person benannt sein.")
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

    Schreibt auch den Vorgang „Geprüft" (F-89, AUFTRAG M4), damit
    „Zuletzt geprüft" Datum und Konto trägt.
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
    """Konflikt lösen: „alten Wert behalten" oder „neuen Wert übernehmen" (F-86)."""
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

    Jedes Gerät, das noch bei der Person liegt („In Benutzung" oder
    „Verliehen"), wird ins Lager zurückgenommen: Status „Auf Lager",
    Person wird entfernt, Vorgang „Rückgabe" entsteht je Gerät.
    „Auf Lager" bleibt unverändert (dort ist die Person nicht zugeordnet).
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
    „mehr als Soll" und nichts fehlt.
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

    Ergebnis: „vollstaendig", „unvollstaendig" oder „mehr-als-soll",
    jeweils mit Fehlliste („fehlt: n x Kategorie") und Mehrliste
    („mehr: n x Kategorie").
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

    Ergebnis: Zeilen je Kategorie mit Summe „fehlt" und Lagerbestand
    („Auf Lager" an einem Lagerort), sortiert nach Kategorie.
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

    Geprüft = „Zuletzt geprüft" gesetzt und das Gerät ist erfasst
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

    Geprüft = „Zuletzt geprüft" gesetzt und das Gerät ist erfasst
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


# --- Import speichern (F-84 bis F-88, A-0114 Teil 3) -----------------------


def _eintrag_fuer_zeile(vorlage, zeile_nr: int) -> dict | None:
    """Den Zeilen-Eintrag der Vorlage für eine Excel-Zeilennummer finden."""
    for eintrag in vorlage.zeilen:
        if eintrag.get("zeile") == zeile_nr:
            return eintrag
    return None


def _person_auflösen(person_wert: str, wert_zu_person: dict) -> Person | None:
    """Person über die Wertezuordnung auflösen; neue Person ohne Konto anlegen (O-18)."""
    if not person_wert:
        return None
    person_ziel = wert_zu_person.get(person_wert, "")
    if not person_ziel:
        return None
    from . import import_parser
    person = import_parser._person_finden(person_ziel)
    if person is not None:
        return person
    # Neue Person ohne Konto (O-18)
    if "@" in person_ziel:
        return None
    teile = person_ziel.split()
    if not teile:
        return None
    return Person.objects.create(
        vorname=teile[0],
        nachname=teile[-1] if len(teile) > 1 else "",
        aktiv=True,
    )


def import_speichern(
    vorlage,
    vorschau,
    spalten_ziel: dict,
    wert_zu_kategorie: dict,
    wert_zu_person: dict,
    wert_zu_arbeitsplatz: dict,
    dateiname: str,
    blatt: str,
    konto,
) -> dict:
    """Speichert die Vorschau-Zeilen (F-84 bis F-87).

    Je Zeile:
    - „neu": Gerät anlegen mit allen Feldern aus der Zeile.
    - „ergaenzt": vorhandenes Gerät (VorschauZeile.gerat), leere Felder füllen.
    - „konflikt": vorhandenes Gerät, widersprüchliche Werte → GeratKonflikt.
    - „uebersprungen": nichts tun.

    F-85: Status und Verbleib ableiten.
    F-87: Vorgang „Import" mit Dateiname, Blatt, Zeile.
    Neue Personen aus der Wertezuordnung werden ohne Konto angelegt (O-18).

    Rückgabe: {„neu": int, „ergaenzt": int, „konflikt": int, „uebersprungen": int}
    """
    from . import import_parser
    from datetime import datetime as _datetime

    def datum_aus_datei(text):
        # import_parser._text_wert schreibt Datumswerte als TT.MM.JJJJ.
        for muster in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                return _datetime.strptime(text, muster).date()
            except ValueError:
                pass
        return None

    neu = ergaenzt = konflikt = ubersprungen = 0
    lauf: Importlauf | None = None

    with transaction.atomic():
        lauf = Importlauf.objects.create(
            dateiname=dateiname, blatt=blatt, erzeugt_von=konto,
        )

        # A-0912: Geräte dieses Laufs, damit die Garantiezeile sie findet.
        neu_nach_sn = {}

        for vz in vorschau:
            ergebnis = vz.ergebnis
            if ergebnis == "uebersprungen":
                ubersprungen += 1
                continue

            eintrag = _eintrag_fuer_zeile(vorlage, vz.zeile)
            if eintrag is None:
                ubersprungen += 1
                continue

            # Werte der Zeile holen
            seriennummer = import_parser._wert_von(vorlage, eintrag, "Seriennummer", spalten_ziel)
            geraetename = import_parser._wert_von(vorlage, eintrag, "Gerätename", spalten_ziel)
            hersteller = import_parser._wert_von(vorlage, eintrag, "Hersteller", spalten_ziel)
            modell = import_parser._wert_von(vorlage, eintrag, "Modell", spalten_ziel)
            kaufdatum_s = import_parser._wert_von(vorlage, eintrag, "Kaufdatum", spalten_ziel)
            garantie_s = import_parser._wert_von(vorlage, eintrag, "Garantie bis", spalten_ziel)
            preis_s = import_parser._wert_von(vorlage, eintrag, "Kaufpreis netto", spalten_ziel)
            lieferant = import_parser._wert_von(vorlage, eintrag, "Lieferant", spalten_ziel)
            rechnung = import_parser._wert_von(vorlage, eintrag, "Rechnungsnummer", spalten_ziel)
            notiz_s = import_parser._wert_von(vorlage, eintrag, "Notiz", spalten_ziel)

            # Kategorie über Wertezuordnung auflösen
            # A-0912 Nr. 2: zählt auch die Wahl „Kategorie/Modell“.
            kategorie = None
            kategorie_name = ""
            for spalte in vorlage.spalten:
                if spalten_ziel.get(spalte.name, import_parser.IGNORIEREN) not in ("Kategorie", import_parser.ZIEL_WAHL_KAT_MOD):
                    continue
                roh = (eintrag["werte"].get(spalte.name) or "").strip()
                if not import_parser._leer(roh):
                    kategorie_name = roh
                break
            if kategorie_name:
                if wert_zu_kategorie.get(kategorie_name):
                    kategorie = import_parser._kategorie_finden(wert_zu_kategorie[kategorie_name])
                elif ergebnis != "ergaenzt":
                    # „nicht übernommen“ (F-82, A-0912 Nr. 4): übersprungen.
                    ubersprungen += 1
                    continue

            # Person über Wertezuordnung auflösen, neu anlegen wenn nötig (O-18)
            person_wert = import_parser._wert_von(vorlage, eintrag, "Person", spalten_ziel)
            person = _person_auflösen(person_wert, wert_zu_person)

            # Ort über Wertezuordnung auflösen
            arbp_wert = import_parser._wert_von(vorlage, eintrag, "Arbeitsplatz", spalten_ziel)
            ort = None
            if arbp_wert:
                arbp_ziel = wert_zu_arbeitsplatz.get(arbp_wert, "")
                if arbp_ziel:
                    ort = import_parser._ort_finden(arbp_ziel)

            # F-85: Geräte ohne Person und Arbeitsplatz → Lagerort
            if person is None and ort is None:
                ort = import_parser._lagerort_finden()

            kaufdatum = datum_aus_datei(kaufdatum_s) if kaufdatum_s else None
            garantie_bis = datum_aus_datei(garantie_s) if garantie_s else None
            preis_wert = None
            if preis_s:
                try:
                    preis_wert = float(preis_s.replace(",", "."))
                except ValueError:
                    preis_wert = None

            # F-85: Defekt-Vermerk in der Notiz → Zustand Stufe 4.
            # A-0912 Nr. 6: Zeile 5 (Kommentar „Defect") hat Zustand 4.
            notiz_klein = notiz_s.lower() if notiz_s else ""
            defekt = "defekt" in notiz_klein or "defect" in notiz_klein
            if defekt:
                zustand_val = Gerat.ZUSTAND_EINGESCHRAENKT
            else:
                zustand_val = Gerat.ZUSTAND_GUT

            herkunft = f"{dateiname} / {blatt or '-'} / Zeile {vz.zeile}"

            if ergebnis == "neu":
                if kategorie is None:
                    ubersprungen += 1
                    continue
                # F-85: Status und Verbleib
                if person is not None:
                    ger_status = Gerat.STATUS_IN_BENUTZUNG
                    altbestand = True
                else:
                    ger_status = Gerat.STATUS_AUF_LAGER
                    altbestand = False

                notiz_final = notiz_s
                if defekt:
                    hinweis_defekt = "laut Altliste defekt: reparieren oder ausmustern"
                    notiz_final = (notiz_final + "; " + hinweis_defekt) if notiz_final else hinweis_defekt

                # F-84: die zweite Zeile mit derselben Nummer entsteht ohne sie,
                # die Notiz nennt sie.
                if "seriennummer-doppelt" in vz.hinweise and seriennummer:
                    vermerk = f"Seriennummer {seriennummer} doppelt im Blatt"
                    notiz_final = f"{notiz_final}; {vermerk}" if notiz_final else vermerk
                    seriennummer = ""

                gerat = Gerat.objects.create(
                    inventarnummer=naechste_inventarnummer(),
                    kategorie=kategorie,
                    hersteller=hersteller,
                    modell=modell,
                    seriennummer=seriennummer,
                    geraetename=geraetename,
                    status=ger_status,
                    zustand=zustand_val,
                    person=person,
                    ort=ort,
                    kaufdatum=kaufdatum,
                    kaufpreis_netto=preis_wert,
                    lieferant=lieferant,
                    rechnungsnummer=rechnung,
                    garantie_bis=garantie_bis,
                    notiz=notiz_final,
                    altbestand_ohne_protokoll=altbestand,
                    zustand_ungeprueft=not defekt,
                    erstellt_von=konto,
                    erstellt_am=timezone.now(),
                )
                if seriennummer:
                    neu_nach_sn[seriennummer.lower()] = gerat
                # F-87: Vorgang „Import"
                Vorgang.objects.create(
                    gerat=gerat,
                    typ=Vorgang.TYP_IMPORT,
                    erzeugt_von=konto,
                    notiz=herkunft,
                    abschliesst=True,
                )
                neu += 1

            elif ergebnis == "ergaenzt":
                gerat = vz.gerat or neu_nach_sn.get((seriennummer or "").lower())
                if gerat is None:
                    ubersprungen += 1
                    continue
                geaendert = []
                if not gerat.seriennummer and seriennummer:
                    gerat.seriennummer = seriennummer
                    geaendert.append("seriennummer")
                if not gerat.geraetename and geraetename:
                    gerat.geraetename = geraetename
                    geaendert.append("geraetename")
                if not gerat.hersteller and hersteller:
                    gerat.hersteller = hersteller
                    geaendert.append("hersteller")
                if not gerat.modell and modell:
                    gerat.modell = modell
                    geaendert.append("modell")
                if gerat.person is None and person is not None:
                    gerat.person = person
                    geaendert.append("person")
                if gerat.ort is None and ort is not None:
                    gerat.ort = ort
                    geaendert.append("ort")
                if gerat.kaufdatum is None and kaufdatum is not None:
                    gerat.kaufdatum = kaufdatum
                    geaendert.append("kaufdatum")
                if gerat.garantie_bis is None and garantie_bis is not None:
                    gerat.garantie_bis = garantie_bis
                    geaendert.append("garantie_bis")
                if gerat.kaufpreis_netto is None and preis_wert is not None:
                    gerat.kaufpreis_netto = preis_wert
                    geaendert.append("kaufpreis_netto")
                if not gerat.notiz and notiz_s:
                    gerat.notiz = notiz_s
                    geaendert.append("notiz")
                elif (notiz_s and kategorie_name.strip().lower() == import_parser.GARANZIE_TYPOBER
                        and notiz_s not in gerat.notiz):
                    # F-84: die Garantiezeile ergänzt auch die Notiz.
                    gerat.notiz = f"{gerat.notiz}; {notiz_s}"
                    geaendert.append("notiz")
                if not gerat.lieferant and lieferant:
                    gerat.lieferant = lieferant
                    geaendert.append("lieferant")
                if not gerat.rechnungsnummer and rechnung:
                    gerat.rechnungsnummer = rechnung
                    geaendert.append("rechnungsnummer")
                # F-85: Status ableiten
                if person is not None and gerat.status == Gerat.STATUS_AUF_LAGER:
                    gerat.status = Gerat.STATUS_IN_BENUTZUNG
                    gerat.altbestand_ohne_protokoll = True
                    geaendert += ["status", "altbestand_ohne_protokoll"]
                if gerat.zustand is None:
                    gerat.zustand = zustand_val
                    geaendert.append("zustand")
                if not gerat.zustand_ungeprueft and not defekt:
                    gerat.zustand_ungeprueft = True
                    geaendert.append("zustand_ungeprueft")
                if geaendert:
                    gerat.save(update_fields=geaendert)
                # F-87: Vorgang „Import"
                Vorgang.objects.create(
                    gerat=gerat,
                    typ=Vorgang.TYP_IMPORT,
                    erzeugt_von=konto,
                    notiz=herkunft,
                    abschliesst=True,
                )
                ergaenzt += 1

            elif ergebnis == "konflikt":
                gerat = vz.gerat
                if gerat is None:
                    ubersprungen += 1
                    continue
                # Widersprüchliche Werte: GeratKonflikt anlegen (F-84)
                if seriennummer and gerat.seriennummer \
                        and seriennummer.lower() != gerat.seriennummer.lower():
                    GeratKonflikt.objects.create(
                        gerat=gerat, feld="seriennummer",
                        alter_wert=gerat.seriennummer, neuer_wert=seriennummer,
                        herkunft=herkunft,
                    )
                if geraetename and gerat.geraetename \
                        and geraetename.lower() != gerat.geraetename.lower():
                    GeratKonflikt.objects.create(
                        gerat=gerat, feld="geraetename",
                        alter_wert=gerat.geraetename, neuer_wert=geraetename,
                        herkunft=herkunft,
                    )
                if hersteller and gerat.hersteller \
                        and hersteller.lower() != gerat.hersteller.lower():
                    GeratKonflikt.objects.create(
                        gerat=gerat, feld="hersteller",
                        alter_wert=gerat.hersteller, neuer_wert=hersteller,
                        herkunft=herkunft,
                    )
                if modell and gerat.modell \
                        and modell.lower() != gerat.modell.lower():
                    GeratKonflikt.objects.create(
                        gerat=gerat, feld="modell",
                        alter_wert=gerat.modell, neuer_wert=modell,
                        herkunft=herkunft,
                    )
                # F-87: Vorgang „Import"
                Vorgang.objects.create(
                    gerat=gerat,
                    typ=Vorgang.TYP_IMPORT,
                    erzeugt_von=konto,
                    notiz=herkunft,
                    abschliesst=True,
                )
                konflikt += 1

        # Zählungen im Importlauf festhalten
        assert lauf is not None
        lauf.anzahl_neu = neu
        lauf.anzahl_ergaenzt = ergaenzt
        lauf.anzahl_konflikt = konflikt
        lauf.anzahl_uebersprungen = ubersprungen
        lauf.save()

    return {"neu": neu, "ergaenzt": ergaenzt, "konflikt": konflikt, "uebersprungen": ubersprungen}


# --- M5 Verleih (F-30, F-36, F-133, F-20) ------------------------------------

def _naechste_leihnummer() -> str:
    """Nächste Leihnummer L-NNNN (fortlaufend, TESTSCHNITTSTELLE 3)."""
    from .models import Leihe
    letzte = Leihe.objects.order_by("-nr").first()
    if letzte and letzte.nr:
        try:
            return f"L-{int(letzte.nr[2:]) + 1:04d}"
        except ValueError:
            pass
    return "L-0001"


def _naechste_protokollnummer() -> str:
    """Nächste Protokollnummer UP-JJJJ-NNNN (fortlaufend je Jahr, TESTSCHNITTSTELLE 3)."""
    from .models import Protokoll
    jahr = timezone.now().year
    letzte = (
        Protokoll.objects.filter(nr__startswith=f"UP-{jahr}-")
        .order_by("-nr")
        .first()
    )
    if letzte and letzte.nr:
        try:
            return f"UP-{jahr}-{int(letzte.nr[-4:]) + 1:04d}"
        except ValueError:
            pass
    return f"UP-{jahr}-0001"


def leih_gerat_ausgeben(
    gerat: Gerat,
    person: Person,
    rueckgabe_bis: date,
    zweck: str,
    ausgefuehrt_von: Konto,
    unterschrift: str = "papier",
) -> Leihe | None:
    """Vorgang „Verleih" (F-30, Kapitel 3.2, Kapitel 8).

    Voraussetzungen (F-30, Kapitel 8):
    - Gerät ist „Auf Lager"
    - Gerät ist nicht reserviert (F-20)
    - Person ist gesetzt (Pflicht)
    - Rückgabedatum ist Pflicht
    - Zweck ist Pflicht

    Ergebnis:
    - Gerät: Status „Verliehen"
    - Leihe: Status „ausgegeben"
    - Protokoll: Stand "scan-offen" (F-22, Kapitel 8.2)
    - Vorgang: Typ „ausgabe", leihgabe_an, zurueck_am

    A-0127: Unterschrift. Bei „tool" bleibt das Gerät „Auf Lager",
    Protokoll auf „bearbeiter-offen"; Status kommt erst mit der Signatur.
    """
    from .models import Leihe, Protokoll, Vorgang
    from django.db import transaction

    if gerat.status != Gerat.STATUS_AUF_LAGER:
        raise GeratFehler(f"Gerät ist nicht auf Lager (Status: {gerat.status}).")

    if _gerat_ist_reserviert(gerat):
        raise GeratFehler("Gerät ist reserviert und kann nicht verliehen werden (F-20).")

    if not zweck or not zweck.strip():
        raise GeratFehler("Zweck ist Pflicht (F-30).")

    # A-0127: Unterschrift „tool" – Gerät bleibt „Auf Lager",
    # Protokoll auf „bearbeiter-offen". Status kommt erst mit der Signatur.
    # A-0128: Zweite Ausgabe/Verleih abgelehnt, solange ein Protokoll
    # auf "bearbeiter-offen" steht (F-30, F-33).
    if unterschrift == "tool":
        if Protokoll.objects.filter(
            geraet=gerat, stand=Protokoll.STAND_BEARBEITER_OFFEN
        ).exists():
            raise GeratFehler(
                "Für dieses Gerät steht bereits ein offenes Protokoll. "
                "Ein weiterer Verleih ist solange nicht möglich (F-30)."
            )
        # A-0128: Leihe zuerst anlegen, dann Protokoll mit Bezug.
        leih_nr = _naechste_leihnummer()
        leihe = Leihe.objects.create(
            nr=leih_nr,
            gerat=gerat,
            person=person,
            rueckgabe_bis=rueckgabe_bis,
            zweck=zweck.strip(),
            status=Leihe.STATUS_AUSGEGEBEN,
            erzeugt_von=ausgefuehrt_von,
        )
        Protokoll.objects.create(
            person=person,
            geraet=gerat,
            datum=timezone.now().date(),
            nr=_naechste_protokollnummer(),
            stand=Protokoll.STAND_BEARBEITER_OFFEN,
            fotos=0,
            erzeugt_von=ausgefuehrt_von,
            unterschrift_art="tool",
            leihe=leihe,
        )
        return leihe

    # Nächste Leihnummer und Protokollnummer
    leih_nr = _naechste_leihnummer()
    protokoll_nr = _naechste_protokollnummer()

    with transaction.atomic():
        # Protokoll (F-21, F-22): Stand "scan-offen", Nummer UP-JJJJ-NNNN
        Protokoll.objects.create(
            person=person,
            geraet=gerat,
            datum=timezone.now().date(),
            nr=protokoll_nr,
            stand=Protokoll.STAND_SCAN_OFFEN,
            fotos=0,
            erzeugt_von=ausgefuehrt_von,
        )

        # Gerät: Status → Verliehen (F-30)
        gerat.status = Gerat.STATUS_VERLIEHEN
        gerat.person = person
        gerat.ort = None
        gerat.save(update_fields=["status", "person", "ort"])

        # Leihe: Status „ausgegeben" (F-30)
        leihe = Leihe.objects.create(
            nr=leih_nr,
            gerat=gerat,
            person=person,
            rueckgabe_bis=rueckgabe_bis,
            zweck=zweck.strip(),
            status=Leihe.STATUS_AUSGEGEBEN,
            erzeugt_von=ausgefuehrt_von,
        )

        # Vorgang (Kapitel 8)
        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_AUSGABE,
            erzeugt_von=ausgefuehrt_von,
            leihgabe_an=person,
            zurueck_am=rueckgabe_bis,
            notiz=zweck.strip(),
            abschliesst=False,
        )

    return leihe


def _gerat_ist_reserviert(
    gerat: Gerat, beginn: date | None = None, ende: date | None = None
) -> bool:
    """Ist das Gerät reserviert? (F-20, Kapitel 4, F-34)

    Ohne Zeitraum: es gibt eine genehmigte Leihe für das Gerät. Mit
    Zeitraum: Überschneidung mit einer genehmigten Leihe desselben
    Geräts – ein Gerät gehört in einem Zeitraum nur zu einer
    genehmigten Leihe (F-34, O-12).
    """
    from django.db.models import Q

    qs = Leihe.objects.filter(
        gerat=gerat, genehmigt=True, status=Leihe.STATUS_GENEHMIGT
    )
    if beginn is not None and ende is not None:
        qs = qs.filter(
            Q(
                beginn__isnull=False,
                beginn__lte=ende,
                ende__isnull=False,
                ende__gte=beginn,
            )
            | Q(beginn__isnull=True)
        )
    return qs.exists()


def leihe_zurueckgeben(
    leihe: Leihe,
    ausgefuehrt_von: Konto,
) -> None:
    """Rückgabe eines verliehenen Geräts (F-133, Kapitel 8).

    Setzt die Leihe auf „zurueckgegeben" und das Gerät auf „Auf Lager".
    Belegt die Prüfpunkte nach F-133.
    """
    from .models import Vorgang
    from django.db import transaction

    gerat = leihe.gerat
    if leihe.status != Leihe.STATUS_AUSGEGEBEN:
        raise GeratFehler("Leihe ist nicht ausgegeben.")

    with transaction.atomic():
        # Gerät zurück ins Lager (F-133)
        gerat.status = Gerat.STATUS_AUF_LAGER
        gerat.person = None
        gerat.save(update_fields=["status", "person"])

        # Leihe → zurückgegeben
        leihe.status = Leihe.STATUS_ZURUECKGEGEBEN
        leihe.genehmigt = False
        leihe.save(update_fields=["status", "genehmigt"])

        # Vorgang „Rückgabe"
        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_RUECKGABE,
            erzeugt_von=ausgefuehrt_von,
            leihgabe_an=leihe.person,
            notiz="Rückgabe Leihgerät",
            abschliesst=True,
        )


# --- F-93, F-32: Mails bei Leihanfrage und Entscheidung (M7 Teil 2) -----------

def _mail_anfrage_an_it(leihe: Leihe) -> None:
    """F-93: Neue Leihanfrage → sofort Mail an die IT.

    Abschaltbar über Einstellungen (F-96).
    """
    from django.core.mail import send_mail
    from django.conf import settings as _settings

    einstellungen = Einstellungen.aktuelles()
    if not einstellungen.mail_leihe_neu:
        return
    it_email = einstellungen.email_it
    if not it_email:
        return
    kat_name = leihe.kat.name if leihe.kat else ""
    gerat_name = leihe.gerat.inventarnummer if leihe.gerat else "keines (Kategorie)"
    beginn = leihe.beginn.strftime("%d.%m.%Y") if leihe.beginn else ""
    ende = leihe.ende.strftime("%d.%m.%Y") if leihe.ende else ""
    basis = _settings.BASIS_URL.rstrip("/") if _settings.BASIS_URL else "http://127.0.0.1:8000"
    send_mail(
        subject=f"Neue Leihanfrage – {leihe.person.vorname} {leihe.person.nachname}",
        message=(
            f"Neue Leihanfrage eingegangen.\n\n"
            f"Person: {leihe.person.vorname} {leihe.person.nachname}\n"
            f"Kategorie: {kat_name}\n"
            f"Gerät: {gerat_name}\n"
            f"Zeitraum: {beginn} bis {ende}\n"
            f"Zweck: {leihe.zweck}\n\n"
            f"Entscheidung: {basis}/verleih/\n\n"
            f"{einstellungen.absenderzeile or 'Wamocon GmbH · IT'}"
        ),
        from_email=_settings.DEFAULT_FROM_EMAIL or "inventar@beispiel.test",
        recipient_list=[it_email],
        fail_silently=True,
    )


def _mail_entscheidung_an_person(leihe: Leihe, genehmigt: bool, begruendung: str = "") -> None:
    """F-32: Entscheidung über Leihanfrage → sofort Mail an die Person.

    Abschaltbar über Einstellungen (F-96).
    """
    from django.core.mail import send_mail
    from django.conf import settings as _settings

    einstellungen = Einstellungen.aktuelles()
    if genehmigt:
        if not einstellungen.mail_verleih_genehmigung:
            return
    else:
        if not einstellungen.mail_verleih_ablehnung:
            return
    empfaenger = leihe.person.email
    if not empfaenger:
        return
    basis = _settings.BASIS_URL.rstrip("/") if _settings.BASIS_URL else "http://127.0.0.1:8000"
    if genehmigt:
        gerat_name = leihe.gerat.inventarnummer if leihe.gerat else ""
        beginn = leihe.beginn.strftime("%d.%m.%Y") if leihe.beginn else ""
        ende = leihe.ende.strftime("%d.%m.%Y") if leihe.ende else ""
        betrag = (
            f"Ihre Leihanfrage wurde genehmigt.\n\n"
            f"Gerät: {gerat_name}\n"
            f"Zeitraum: {beginn} bis {ende}\n\n"
            f"Details: {basis}/verleih/\n\n"
            f"{einstellungen.absenderzeile or 'Wamocon GmbH · IT'}"
        )
        subject = f"Leihanfrage genehmigt – {gerat_name}"
    else:
        betrag = (
            f"Ihre Leihanfrage wurde abgelehnt.\n\n"
            f"Begründung: {begruendung}\n\n"
            f"Details: {basis}/verleih/\n\n"
            f"{einstellungen.absenderzeile or 'Wamocon GmbH · IT'}"
        )
        subject = "Leihanfrage abgelehnt"
    send_mail(
        subject=subject,
        message=betrag,
        from_email=_settings.DEFAULT_FROM_EMAIL or "inventar@beispiel.test",
        recipient_list=[empfaenger],
        fail_silently=True,
    )


def leihe_anfragen(
    person: Person,
    kat: Kategorie,
    beginn: date,
    ende: date,
    zweck: str,
    gerat: Gerat | None,
    erzeugt_von: Konto,
) -> Leihe:
    """M5 Teil 2 (F-31, F-34, F-37): Mitarbeiter fragt ein Leihgerät an.

    Speichert die Leihe im Status „angefragt\" (O-12). Ein konkretes Gerät
    wird erst mit dem Genehmigen zugewiesen (F-32); wurde eines gewählt,
    muss es in der Kategorie und im Leihpool stehen (F-31). Eine
    Überschneidung mit einer genehmigten Leihe desselben Geräts lehnt
    diese Anfrage ab (F-34).
    """
    if not zweck or not zweck.strip():
        raise GeratFehler("Zweck ist Pflicht (F-31).")
    if beginn > ende:
        raise GeratFehler("Beginn ist nach dem Ende.")
    if gerat is not None:
        if gerat.kategorie_id != kat.id:
            raise GeratFehler("Das gewählte Gerät steht nicht in dieser Kategorie.")
        if not gerat.leihpool:
            raise GeratFehler("Das gewählte Gerät steht nicht im Leihpool.")
        if _gerat_ist_reserviert(gerat, beginn, ende):
            raise GeratFehler(
                "Das Gerät ist in diesem Zeitraum bereits für eine genehmigte "
                "Leihe reserviert (F-34)."
            )
    with transaction.atomic():
        leihe = Leihe.objects.create(
            nr=_naechste_leihnummer(),
            gerat=gerat,
            person=person,
            kat=kat,
            beginn=beginn,
            ende=ende,
            rueckgabe_bis=ende,
            zweck=zweck.strip(),
            status=Leihe.STATUS_ANGEFRAGT,
            erzeugt_von=erzeugt_von,
        )
        if gerat is not None:
            _gerat_reserve_halten(gerat, beginn, ende)
        # F-93: sofort Mail an die IT
        _mail_anfrage_an_it(leihe)
        return leihe


def leihe_genehmigen(
    leihe: Leihe,
    gerat: Gerat,
    ausgefuehrt_von: Konto,
) -> Leihe:
    """M5 Teil 2 (F-32, F-34): IT genehmigt mit Zuweisung eines Geräts.

    Das Gerät muss in der Leihkategorie stehen und im Leihpool verfügbar
    sein. Ein Gerät gehört in einem Zeitraum nur zu einer genehmigten
    Leihe; eine Überschneidung schlägt mit einer Meldung fehl (F-34).
    Bei Erfolg: Leihe „genehmigt\", Gerät „Auf Lager\" mit reserviert
    bis zum Leihende (F-20).
    """
    from .models import Vorgang

    if leihe.status != Leihe.STATUS_ANGEFRAGT:
        raise GeratFehler("Diese Leihe ist nicht angefragt.")
    if gerat.kategorie_id != leihe.kat.id:
        raise GeratFehler("Das Gerät steht nicht in der angefragten Kategorie.")
    if not gerat.leihpool:
        raise GeratFehler("Das Gerät steht nicht im Leihpool.")
    if _gerat_ist_reserviert(gerat, leihe.beginn, leihe.ende):
        raise GeratFehler(
            "Das Gerät ist in diesem Zeitraum bereits für eine genehmigte "
            "Leihe reserviert (F-34)."
        )
    with transaction.atomic():
        leihe.gerat = gerat
        leihe.genehmigt = True
        leihe.status = Leihe.STATUS_GENEHMIGT
        leihe.decided_at = timezone.now()
        leihe.save(
            update_fields=["gerat", "genehmigt", "status", "decided_at"]
        )
        _gerat_reserve_halten(gerat, leihe.beginn, leihe.ende)
        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_AENDERUNG,
            erzeugt_von=ausgefuehrt_von,
            notiz="Leihe genehmigt und Gerät reserviert (F-32).",
            abschliesst=False,
        )
        # F-32: Mail an die Person
        _mail_entscheidung_an_person(leihe, genehmigt=True)
        return leihe


def leihe_ablehnen(
    leihe: Leihe,
    begruendung: str,
    ausgefuehrt_von: Konto,
) -> Leihe:
    """M5 Teil 2 (F-32): IT lehnt mit Pflichtbegründung ab.

    Ohne Begründung wird die Ablehnung nicht gespeichert.
    """
    from .models import Vorgang

    if leihe.status != Leihe.STATUS_ANGEFRAGT:
        raise GeratFehler("Diese Leihe ist nicht angefragt.")
    if not begruendung or not begruendung.strip():
        raise GeratFehler("Begründung ist Pflicht (F-32).")
    with transaction.atomic():
        leihe.abgelehnt = True
        leihe.abgelehnt_bis = begruendung.strip()
        leihe.abgelehnt_von = ausgefuehrt_von
        leihe.genehmigt = False
        leihe.status = Leihe.STATUS_ABGELEHNT
        leihe.decided_at = timezone.now()
        leihe.save(
            update_fields=[
                "abgelehnt",
                "abgelehnt_bis",
                "abgelehnt_von",
                "genehmigt",
                "status",
                "decided_at",
            ]
        )
        if leihe.gerat_id is not None:
            Vorgang.objects.create(
                gerat=leihe.gerat,
                typ=Vorgang.TYP_AENDERUNG,
                erzeugt_von=ausgefuehrt_von,
                notiz="Leihe abgelehnt (F-32).",
                abschliesst=False,
            )
        # F-32: Mail an die Person
        _mail_entscheidung_an_person(leihe, genehmigt=False, begruendung=begruendung.strip())
        return leihe


def leihe_zurueckziehen(
    leihe: Leihe,
    ausgefuehrt_von: Konto,
) -> Leihe:
    """M5 Teil 2 (F-37): Mitarbeiter zieht die Leihe zurück.

    Solange die Leihe nicht ausgegeben ist, endet damit auch eine
    Reservierung: reserviert und reserviert_bis werden geleert.
    """
    from .models import Vorgang

    if not leihe.ist_zurueckziehbar():
        raise GeratFehler(
            "Diese Leihe ist nicht zurückziehbar – sie ist ausgegeben "
            "(F-37)."
        )
    with transaction.atomic():
        leihe.status = Leihe.STATUS_ZURUECKGEZOGEN
        leihe.decided_at = timezone.now()
        leihe.save(update_fields=["status", "decided_at"])
        if leihe.gerat_id is not None:
            gerat = leihe.gerat
            if _gerat_reserve_ist_leihe(gerat, leihe):
                gerat.reserviert = False
                gerat.reserviert_bis = None
                gerat.save(update_fields=["reserviert", "reserviert_bis"])
            Vorgang.objects.create(
                gerat=gerat,
                typ=Vorgang.TYP_AENDERUNG,
                erzeugt_von=ausgefuehrt_von,
                notiz="Leihe zurückgezogen, Reservierung aufgehoben (F-37).",
                abschliesst=False,
            )
        return leihe


def _gerat_reserve_halten(gerat: Gerat, beginn: date, ende: date) -> None:
    """Reservierung setzen oder verlängern (F-20, Kapitel 4).

    reserviert_bis ist das Maximum aller genehmigten Leihen (O-12).
    """
    from konten.zeit import jetzt_wie_im_entwicklungsmodus

    heute = jetzt_wie_im_entwicklungsmodus().date()
    bis = max(ende, heute)
    if not gerat.reserviert_bis or gerat.reserviert_bis < bis:
        gerat.reserviert = True
        gerat.reserviert_bis = bis
        gerat.save(update_fields=["reserviert", "reserviert_bis"])


def _gerat_reserve_ist_leihe(gerat: Gerat, leihe: Leihe) -> bool:
    """Gehört die aktuelle Reservierung nur zu dieser Leihe?

    Nur dann darf Zurückziehen sie aufheben, sonst bliebe die
    Reservierung für eine andere genehmigte Leihe bestehen (O-12).
    """
    if gerat.reserviert_bis is None or leihe.ende is None:
        return gerat.reserviert is True and leihe.ist_zurueckziehbar()
    return gerat.reserviert_bis == leihe.ende and gerat.reserviert is True

def leihe_ausgeben(
    leihe: Leihe,
    ausgefuehrt_von: Konto,
) -> Leihe:
    """M5 Teil 4 (F-33, F-21, F-22): IT gibt eine genehmigte Leihe aus.

    Voraussetzungen (F-33):
    - Leihe ist genehmigt
    - Gerät ist im Leihpool
    - Gerät ist nicht reserviert (F-20), außer durch die Leihe selbst

    Ergebnis:
    - Gerät: Status "Verliehen", Person gesetzt
    - Leihe: Status "ausgegeben"
    - Protokoll: Stand "scan-offen" (F-21, F-22)
    - Vorgang: Typ "ausgabe", leihgabe_an, zurueck_am
    - Reservierung endet (reserviert=False, reserviert_bis=None)
    """
    from .models import Protokoll, Vorgang
    from django.db import transaction

    if leihe.status != Leihe.STATUS_GENEHMIGT:
        raise GeratFehler("Diese Leihe ist nicht genehmigt (F-33).")

    if leihe.gerat_id is None:
        raise GeratFehler("Die Leihe hat kein Gerät zugewiesen.")

    gerat = leihe.gerat
    if gerat.status != Gerat.STATUS_AUF_LAGER:
        raise GeratFehler(f"Gerät ist nicht auf Lager (Status: {gerat.status}).")

    if not gerat.leihpool:
        raise GeratFehler("Gerät steht nicht im Leihpool (F-33).")

    # Prüfen, ob das Gerät für jemand anderen reserviert ist (F-20)
    # Eine Reservierung durch die Leihe selbst (gleiche Person) ist erlaubt
    if _gerat_ist_reserviert(gerat):
        # Reservierung prüfen: nur ablehnen, wenn sie nicht zur Leihe gehört
        andere_reservation = None
        for leihe_anderer in Leihe.objects.filter(
            gerat=gerat,
            genehmigt=True,
            status=Leihe.STATUS_GENEHMIGT,
        ).exclude(person=leihe.person):
            andere_reservation = leihe_anderer
            break
        if andere_reservation is not None:
            raise GeratFehler("Gerät ist für eine andere Person reserviert und kann nicht ausgegeben werden (F-20).")

    person = leihe.person
    if person is None:
        raise GeratFehler("Die Leihe hat keine Person.")

    rueckgabe_bis = leihe.rueckgabe_bis
    if rueckgabe_bis is None:
        raise GeratFehler("Rückgabedatum fehlt.")

    with transaction.atomic():
        # A-0123 (M6 Teil 1): F-21, F-22, F-130 — Protokoll in der
        # Service-Schicht bei Verleih. Stand ist „scan-offen".
        _protokoll_erstellen(
            person=person,
            gerat=gerat,
            art=Protokoll.ART_AUSGABE,
            bearbeiter=(
                ausgefuehrt_von.bezeichnung() if ausgefuehrt_von is not None else ""
            ),
            erzeugt_von=ausgefuehrt_von,
        )

        # Gerät: Status → Verliehen (F-33)
        gerat.status = Gerat.STATUS_VERLIEHEN
        gerat.person = person
        gerat.ort = None
        gerat.save(update_fields=["status", "person", "ort"])

        # Leihe: Status → ausgegeben (F-33)
        leihe.status = Leihe.STATUS_AUSGEGEBEN
        leihe.save(update_fields=["status"])

        # Vorgang "Ausgabe" (Kapitel 8)
        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_AUSGABE,
            erzeugt_von=ausgefuehrt_von,
            leihgabe_an=person,
            zurueck_am=rueckgabe_bis,
            notiz=leihe.zweck or "Leihgerät ausgegeben (F-33).",
            abschliesst=False,
        )

        # Reservierung endet (F-20): das Gerät ist jetzt verliehen
        gerat.reserviert = False
        gerat.reserviert_von = None
        gerat.reserviert_bis = None
        gerat.save(update_fields=["reserviert", "reserviert_von", "reserviert_bis"])

    return leihe


def leihe_verlaengern(
    leihe: Leihe,
    rueckgabe_bis_neu: date,
    ausgefuehrt_von: Konto,
) -> Leihe:
    """M5 Teil 4 (F-35): Mitarbeiter fragt Verlängerung an; IT gewährt oder lehnt ab.

    Voraussetzungen (F-35):
    - Leihe ist ausgegeben
    - Neue Rückgabedatum muss nach dem alten liegen

    Ablehnung:
    - Gerät ist für einen Zeitraum nach dem neuen Rückgabedatum reserviert (F-35)

    Ergebnis bei Erfolg:
    - Leihe: rueckgabe_bis wird verschoben
    - Vorgang "Änderung" wird angelegt
    """
    from .models import Vorgang
    from django.db import transaction

    if leihe.status != Leihe.STATUS_AUSGEGEBEN:
        raise GeratFehler("Diese Leihe ist nicht ausgegeben (F-35).")

    gerat = leihe.gerat
    if gerat is None:
        raise GeratFehler("Die Leihe hat kein Gerät zugewiesen.")

    altes_rueckgabe_bis = leihe.rueckgabe_bis
    if rueckgabe_bis_neu <= altes_rueckgabe_bis:
        raise GeratFehler("Neues Rückgabedatum muss nach dem alten liegen (F-35).")

    # Prüfen, ob das Gerät nach dem neuen Rückgabedatum reserviert ist (F-35)
    if _gerat_ist_reserviert(gerat, rueckgabe_bis_neu, rueckgabe_bis_neu):
        raise GeratFehler(
            "Verlängerung abgelehnt: Das Gerät ist für den gewünschten "
            "Zeitraum bereits reserviert (F-35)."
        )

    with transaction.atomic():
        leihe.rueckgabe_bis = rueckgabe_bis_neu
        if leihe.ende is None or rueckgabe_bis_neu > leihe.ende:
            leihe.ende = rueckgabe_bis_neu
        leihe.save(update_fields=["rueckgabe_bis", "ende"])

        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_AENDERUNG,
            erzeugt_von=ausgefuehrt_von,
            aenderung_feld="rueckgabe_bis",
            aenderung_alter_wert=str(altes_rueckgabe_bis),
            aenderung_neuer_wert=str(rueckgabe_bis_neu),
            notiz="Verlängerung der Leihe (F-35).",
            abschliesst=False,
        )

    return leihe


def leihen_ueberfaellig() -> list:
    """Alle Leihen, die überfällig sind (F-36)."""
    from .models import Leihe
    from konten.zeit import jetzt_wie_im_entwicklungsmodus

    heute = jetzt_wie_im_entwicklungsmodus().date()
    return [
        l for l in Leihe.objects.filter(
            status=Leihe.STATUS_AUSGEGEBEN,
            rueckgabe_bis__isnull=False,
        ).select_related("gerat", "person")
        if l.rueckgabe_bis and l.rueckgabe_bis < heute
    ]


# --- A-0125 M6 Teil 2: Signatur, Gegenzeichnung (F-135, F-136, F-137, F-141) ---
#
# F-135: Bearbeiter prüft das PDF und signiert mit erneuter Passwortabfrage.
# Danach ist der Inhalt gesperrt; Korrekturen erzeugen eine neue Fassung.
#
# F-136: Mail mit persönlichem Link (14 Tage), Person sieht das PDF und
# signiert nach Eingabe eines Einmalcodes (6 Stellen, 10 Min., 5 Versuche).
#
# F-137: Zu jeder Signatur werden Name, E-Mail, Zeitpunkt, Nachweisnummer,
# Identifizierungsmerkmal, IP-Adresse und Hashwert gespeichert.
#
# F-141: Rücknahme ist erst mit der Signatur der Person abgeschlossen;
# die Geräte sind trotzdem sofort im Lager.


def _client_ip(request) -> str:
    """IP-Adresse aus der Request-Header (F-137)."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "127.0.0.1")


def _pdf_hash(pdf_bytes: bytes) -> str:
    """SHA-256-Hash des PDFs (F-137)."""
    import hashlib
    return hashlib.sha256(pdf_bytes).hexdigest()


def protokoll_bearbeiter_signieren(
    protokoll: Protokoll,
    password: str,
    request=None,
) -> tuple[Protokoll, bool]:
    """F-135: Bearbeiter signiert das Protokoll.

    Passwort muss zum Konto des Bearbeiters passen. Danach:
    - Inhalt gesperrt (bearbeiter_signiert_am gesetzt)
    - Stand → gegenzeichnung-offen
    - Token für die Gegenzeichnung erzeugt (14 Tage)
    - Mail mit Link in die Mailablage (F-136)
    - Prüfprotokoll-Eintrag (F-137)
    """
    from konten.models import Konto
    from konten.zeit import jetzt_wie_im_entwicklungsmodus
    from .models import SignaturAufzeichnung

    now = jetzt_wie_im_entwicklungsmodus()
    ip = _client_ip(request) if request else "127.0.0.1"

    # Passwort prüfen: der Bearbeiter muss ein Konto mit diesem Passwort haben.
    bearbeiter_name = protokoll.bearbeiter
    konto = Konto.objects.filter(
        email__iexact=bearbeiter_name
    ).first() if bearbeiter_name else None
    if konto is None:
        # Fallback: Bearbeiter-Feld ist ein Name, kein E-Mail.
        # Wir prüfen gegen die erzeugte Person.
        konto = protokoll.erzeugt_von
    if konto is None:
        return protokoll, False
    if not konto.check_password(password):
        return protokoll, False

    # F-132: Signatur wird abgelehnt, solange die Checkliste noch offen ist.
    offene = protokoll.checkliste_unbeantwortet()
    if offene:
        return protokoll, False

    # Prüfprotokoll: PDF-Hash berechnen (F-137).
    # F-132, F-135: pdf_bauen muss erfolgreich sein; bei offenem Inhalt
    # wird die Signatur abgelehnt, statt leeren Inhalt zu signieren.
    from . import pdf as pdf_modul
    try:
        pdf_bytes = pdf_modul.pdf_bauen(protokoll)
    except GeratFehler:
        return protokoll, False
    pdf_hash = _pdf_hash(pdf_bytes)

    # Signatur setzen (F-135).
    protokoll.bearbeiter_signatur = password[:6]  # nur als Hinweis, nicht das Passwort selbst
    protokoll.bearbeiter_signiert_am = now
    protokoll.bearbeiter_signiert_von = konto
    protokoll.bearbeiter_ip = ip
    protokoll.pdf_hash_bearbeiter = pdf_hash

    # F-137: Prüfprotokoll-Eintrag.
    SignaturAufzeichnung.objects.create(
        protokoll=protokoll,
        art=SignaturAufzeichnung.KIND_BEARBEITER,
        name=konto.bezeichnung,
        email=konto.email,
        zeitpunkt=now,
        nachweisnummer=protokoll.nr,
        identifikationsmerkmal=f"Passwort-Abfrage ({konto.email})",
        ip_adresse=ip,
        hashwert=pdf_hash,
    )

    # A-0128: Bei Unterschrift „tool" entstehen Status, Person, Ort
    # und der Vorgang mit der Signatur des Bearbeiters (F-21, F-135).
    # Bei Verleih (F-30, F-33): Status Verliehen, Leihe wird weitergeführt.
    if protokoll.unterschrift_art == "tool":
        gerat = protokoll.geraet
        if protokoll.leihe is not None:
            # Verleih: Status Verliehen, Person gesetzt, Ort leer (F-30).
            gerat.status = Gerat.STATUS_VERLIEHEN
            gerat.person = protokoll.person
            gerat.ort = None
            gerat.save(update_fields=["status", "person", "ort"])
            # Leihe weiterführen: Status bleibt „ausgegeben" (F-33).
            # (Wurde beim Anlegen bereits gesetzt; hier sicherstellen.)
            if protokoll.leihe.status != Leihe.STATUS_AUSGEGEBEN:
                protokoll.leihe.status = Leihe.STATUS_AUSGEGEBEN
                protokoll.leihe.save()
        else:
            # Ausgabe: Status In Benutzung, Person und Ort gesetzt (F-20, F-21).
            gerat.status = Gerat.STATUS_IN_BENUTZUNG
            gerat.person = protokoll.person
            if protokoll.ort_ziel is not None:
                gerat.ort = protokoll.ort_ziel
            gerat.save(update_fields=["status", "person", "ort"])
            # Vorgang „Ausgabe" in die Historie (F-21).
            Vorgang.objects.create(
                gerat=gerat,
                typ=Vorgang.TYP_AUSGABE,
                zeitpunkt=now,
                erzeugt_von=konto,
                leihgabe_an=protokoll.person,
                notiz=f"Ausgabe per Protokoll {protokoll.nr} (F-21)",
                abschliesst=True,
            )

    # F-136: Token für die Gegenzeichnung erzeugen (14 Tage gültig).
    import secrets
    token = secrets.token_hex(32)
    empfaenger = protokoll.person.email or protokoll.person.email_arbeit
    protokoll.gegenzeichnung_token = token
    protokoll.gegenzeichnung_token_erstellt = now
    protokoll.gegenzeichnung_empfaenger = empfaenger
    protokoll.stand = Protokoll.STAND_GEGENZEICHNUNG_OFFEN
    protokoll.save()

    # Mail in die Mailablage (F-136, TESTSCHNITTSTELLE 4: code-senden).
    _mail_gegenzeichnen_link(
        protokoll, token, empfaenger,
        bearbeiter_name=konto.bezeichnung,
    )

    return protokoll, True


def _mail_gegenzeichnen_link(
    protokoll: Protokoll,
    token: str,
    empfaenger: str,
    bearbeiter_name: str = "",
) -> None:
    """Mail mit persönlichem Link in die Mailablage (F-136).

    TESTSCHNITTSTELLE 4: POST /protokolle/<Nummer>/code-senden/
    erzeugt eine Mail mit der Zeile „Einmalcode:".
    """
    from django.core.mail import send_mail

    link = f"/signieren/{token}/"
    betref = f"Gegenzeichnung: Protokoll {protokoll.nr}"
    inhalt = (
        f"Sehr geehrte {protokoll.person.vorname} {protokoll.person.nachname},\n\n"
        f"das Protokoll {protokoll.nr} steht zur Gegenzeichnung bereit.\n"
        f"Öffnen Sie den folgenden Link, sehen Sie das PDF und signieren Sie "
        f"mit dem Einmalcode, der Ihnen per Mail zugeht:\n\n"
        f"Link: {link}\n\n"
        f"Der Link ist 14 Tage gültig.\n\n"
        f"Mit freundlichen Grüßen\n"
        f"Wamocon GmbH · IT"
    )
    if empfaenger:
        send_mail(betref, inhalt, "it@wamocon.de", [empfaenger], fail_silently=True)


def protokoll_code_senden(
    protokoll: Protokoll,
    empfaenger: str | None = None,
    request=None,
) -> tuple[bool, str]:
    """F-136: Einmalcode erzeugen und per Mail senden.

    TESTSCHNITTSTELLE 4: POST /protokolle/<Nummer>/code-senden/
    Erzeugt einen 6-stelligen Code (10 Min. gültig, 5 Versuche) und
    schickt eine Mail mit der Zeile „Einmalcode: <code>".

    Liefert (erfolgreich, meldung).
    """
    from .models import SignaturCode
    import secrets

    now = jetzt_wie_im_entwicklungsmodus()
    from datetime import timedelta
    code = f"{secrets.randbelow(10**6):06d}"
    gueltig_bis = now + timedelta(minutes=10)

    # Alte, noch gültige Codes ungültig machen.
    SignaturCode.objects.filter(
        protokoll=protokoll, gueltig=True
    ).update(gueltig=False)

    SignaturCode.objects.create(
        protokoll=protokoll,
        code=code,
        erstellt_am=now,
        gueltig_bis=gueltig_bis,
    )

    empfaenger = empfaenger or protokoll.gegenzeichnung_empfaenger
    empfaenger = empfaenger or protokoll.person.email or protokoll.person.email_arbeit
    betref = f"Einmalcode für Protokoll {protokoll.nr}"
    inhalt = (
        f"Sehr geehrte {protokoll.person.vorname} {protokoll.person.nachname},\n\n"
        f"Ihr Einmalcode für die Gegenzeichnung des Protokolls {protokoll.nr}:\n\n"
        f"Einmalcode: {code}\n\n"
        f"Der Code ist 10 Minuten gültig und darf 5-mal verwendet werden.\n\n"
        f"Mit freundlichen Grüßen\n"
        f"Wamocon GmbH · IT"
    )
    if empfaenger:
        from django.core.mail import send_mail
        send_mail(betref, inhalt, "it@wamocon.de", [empfaenger], fail_silently=True)
    return True, "Code gesendet."


def _mail_versand_mit_anhang(
    protokoll: Protokoll,
    pdf_bytes: bytes,
    dateiname: str,
) -> None:
    """F-139: Mail an Person und Bearbeiter mit dem PDF als Anhang.

    Je eine Ausfertigung. Dateiname nach F-139.
    """
    from django.core.mail import EmailMessage

    empfaenger = protokoll.person.email or protokoll.person.email_arbeit
    if not empfaenger:
        return

    betref = f"Protokoll {protokoll.nr} – Gegenzeichnung abgeschlossen"
    inhalt = (
        f"Vielen Dank. Ihre Gegenzeichnung des Protokolls {protokoll.nr} "
        f"ist abgeschlossen.\n\n"
        f"Anbei erhalten Sie das versiegelte Protokoll-PDF "
        f"({dateiname}).\n\n"
        f"Wamocon GmbH · IT"
    )

    msg = EmailMessage(
        subject=betref,
        body=inhalt,
        from_email="it@wamocon.de",
        to=[empfaenger],
    )
    msg.attach(dateiname, pdf_bytes, "application/pdf")
    msg.send(fail_silently=True)

    # Bearbeiter-Kopie (falls vorhanden und anders als die Person).
    bearbeiter_email = ""
    if protokoll.erzeugt_von is not None:
        bearbeiter_email = protokoll.erzeugt_von.email or ""
    if bearbeiter_email and bearbeiter_email != empfaenger:
        msg2 = EmailMessage(
            subject=betref,
            body=inhalt,
            from_email="it@wamocon.de",
            to=[bearbeiter_email],
        )
        msg2.attach(dateiname, pdf_bytes, "application/pdf")
        msg2.send(fail_silently=True)


def _mail_bestätigung(protokoll: Protokoll) -> None:
    """Bestätigungsmail an die Person, wenn das Siegel nicht verfügbar ist."""
    from django.core.mail import send_mail

    empfaenger = protokoll.person.email or protokoll.person.email_arbeit
    if empfaenger:
        send_mail(
            f"Gegenzeichnung abgeschlossen: Protokoll {protokoll.nr}",
            (
                f"Vielen Dank. Ihre Gegenzeichnung des Protokolls {protokoll.nr} "
                f"ist abgeschlossen.\n\nWamocon GmbH · IT"
            ),
            "it@wamocon.de",
            [empfaenger],
            fail_silently=True,
        )


def _ablage_mit_anhang(
    protokoll: Protokoll,
    pdf_bytes: bytes,
    dateiname: str,
) -> None:
    """F-139: Das fertige PDF ablegen und als Anhang senden.

    Ablageorte:
    - Am Gerät: var/protokolle/<Gerat>/<dateiname>
    - An der Person: var/personen/<person_id>/<dateiname>
    - Unter /meine-geraete/: var/meine-geraete/<person_id>/<dateiname>

    Mail: Person und Bearbeiter (falls vorhanden), je eine Ausfertigung
    mit dem PDF als Anhang.
    """
    from pathlib import Path

    from django.conf import settings

    var_root = Path(settings.DATEIABLAGE)
    person_id = str(protokoll.person_id)

    # Am Gerät ablegen.
    gerat_dir = var_root / "protokolle" / str(protokoll.geraet_id)
    gerat_dir.mkdir(parents=True, exist_ok=True)
    (gerat_dir / dateiname).write_bytes(pdf_bytes)

    # An der Person ablegen.
    person_dir = var_root / "personen" / person_id
    person_dir.mkdir(parents=True, exist_ok=True)
    (person_dir / dateiname).write_bytes(pdf_bytes)

    # Unter /meine-geraete/ ablegen.
    meine_geraete_dir = var_root / "meine-geraete" / person_id
    meine_geraete_dir.mkdir(parents=True, exist_ok=True)
    (meine_geraete_dir / dateiname).write_bytes(pdf_bytes)

    # Mail an Person.
    person_email = protokoll.person.email or protokoll.person.email_arbeit
    if person_email:
        _mail_anhang(protokoll, pdf_bytes, dateiname, person_email)

    # Mail an Bearbeiter (falls vorhanden und anders als die Person).
    if protokoll.erzeugt_von is not None:
        bearbeiter_email = protokoll.erzeugt_von.email or ""
        if bearbeiter_email and bearbeiter_email != person_email:
            _mail_anhang(protokoll, pdf_bytes, dateiname, bearbeiter_email)


def _mail_anhang(
    protokoll: Protokoll,
    pdf_bytes: bytes,
    dateiname: str,
    empfaenger: str,
) -> None:
    """F-139: Mail mit dem PDF als Anhang an einen Empfänger."""
    from django.core.mail import EmailMessage

    msg = EmailMessage(
        subject=f"Protokoll {protokoll.nr} – Gegenzeichnung abgeschlossen",
        body=(
            f"Vielen Dank. Die Gegenzeichnung des Protokolls {protokoll.nr} "
            f"ist abgeschlossen.\n\n"
            f"Anbei erhalten Sie das versiegelte Protokoll-PDF "
            f"({dateiname}).\n\n"
            f"Wamocon GmbH · IT"
        ),
        from_email="it@wamocon.de",
        to=[empfaenger],
    )
    msg.attach(dateiname, pdf_bytes, "application/pdf")
    msg.send(fail_silently=True)


def protokoll_link_neu_senden(
    protokoll: Protokoll,
) -> tuple[Protokoll, bool, str]:
    """F-140: Abgelaufener Link wird neu gesendet (neuer Token, neue Mail).

    Erinnerung am dritten Tag kommt mit dem Tageslauf in M7.
    """
    from datetime import timedelta
    from konten.zeit import jetzt_wie_im_entwicklungsmodus
    from .models import SignaturCode
    import secrets

    now = jetzt_wie_im_entwicklungsmodus()

    # F-135: Bearbeiter muss schon signiert haben.
    if protokoll.bearbeiter_signiert_am is None:
        return protokoll, False, "Der Bearbeiter hat noch nicht signiert."

    # Alte Codes ungültig machen.
    SignaturCode.objects.filter(protokoll=protokoll, gueltig=True).update(
        gueltig=False
    )

    # Neuer Token.
    neuer_token = secrets.token_urlsafe(32)
    protokoll.gegenzeichnung_token = neuer_token
    protokoll.gegenzeichnung_token_erstellt = now
    protokoll.link_neu_gesendet_am = now
    protokoll.stand = Protokoll.STAND_GEGENZEICHNUNG_OFFEN
    protokoll.save()

    # Neue Mail mit Link und Code.
    from django.core.mail import send_mail
    empfaenger = protokoll.person.email or protokoll.person.email_arbeit
    if empfaenger:
        code = secrets.choice("23456789") + secrets.choice("23456789") + secrets.choice("23456789")
        SignaturCode.objects.create(
            protokoll=protokoll,
            code=code,
            erstellt_am=now,
            gueltig_bis=now + timedelta(minutes=10),
            gueltig=True,
        )
        basis = os.environ.get("INVENTAR_BASIS_URL", "http://127.0.0.1:8000")
        link = f"{basis}/signieren/{neuer_token}/"
        send_mail(
            f"Protokoll {protokoll.nr} – neuer Link zur Gegenzeichnung",
            (
                f"Ihr alter Link zur Gegenzeichnung ist abgelaufen. "
                f"Bitte nutzen Sie den neuen Link:\n\n"
                f"{link}\n\n"
                f"Einmalcode: {code}\n\n"
                f"Wamocon GmbH · IT"
            ),
            "it@wamocon.de",
            [empfaenger],
            fail_silently=True,
        )

    return protokoll, True, "Neuer Link gesendet."


def protokoll_gegenzeichnen(
    token: str,
    code: str,
    request=None,
) -> tuple[Protokoll | None, bool, str]:
    """F-136: Person signiert per Token-Link mit Einmalcode.

    TESTSCHNITTSTELLE 3: GET /signieren/<token>/ ohne Anmeldung.
    POST /signieren/<token>/ mit {"code": "..."}.

    - Falscher Code: abgelehnt, Versuch gezählt.
    - Nach 5 Fehlversuchen: kein Code mehr gültig (F-136, N-05).
    - Code nach 10 Minuten: abgelaufen (TESTSCHNITTSTELLE 3).
    - Token nach 14 Tagen: abgelaufen (TESTSCHNITTSTELLE 3).

    Liefert (protokoll, erfolg, meldung).
    """
    from konten.zeit import jetzt_wie_im_entwicklungsmodus
    from .models import SignaturAufzeichnung, SignaturCode

    protokoll = Protokoll.objects.filter(
        gegenzeichnung_token=token
    ).select_related("person", "geraet").first()
    if protokoll is None:
        return None, False, "Unbekannter Link."

    # F-136: Token abgelaufen nach 14 Tagen.
    if protokoll.gegenzeichnung_abgelaufen:
        return protokoll, False, "Der Link ist abgelaufen."

    # F-135: Bearbeiter muss schon signiert haben.
    if protokoll.bearbeiter_signiert_am is None:
        return protokoll, False, "Der Bearbeiter hat noch nicht signiert."

    # F-136: Code suchen.
    code_objekt = SignaturCode.objects.filter(
        protokoll=protokoll, code=code, gueltig=True
    ).first()
    if code_objekt is None:
        # Code existiert nicht oder ist ungültig.
        # Prüfen, ob es einen aktiven Code gibt, um den Versuch zu zählen.
        aktiver = SignaturCode.objects.filter(
            protokoll=protokoll, gueltig=True
        ).order_by("-erstellt_am").first()
        if aktiver is not None:
            aktiver.versucht_anzahl += 1
            if aktiver.versucht_anzahl >= 5:
                aktiver.gueltig = False
            aktiver.save()
            if aktiver.ist_gesperrt():
                return protokoll, False, (
                    "Zu viele Fehlversuche. Der Code ist nicht mehr gültig."
                )
        return protokoll, False, "Code ungültig."

    # Code-Prüfung: Zeitfenster.
    if not code_objekt.ist_gueltig():
        if code_objekt.ist_gesperrt():
            return protokoll, False, (
                "Zu viele Fehlversuche. Der Code ist nicht mehr gültig."
            )
        return protokoll, False, "Code abgelaufen."

    # Code korrekt: Signatur setzen (F-136, F-137).
    now = jetzt_wie_im_entwicklungsmodus()
    ip = _client_ip(request) if request else "127.0.0.1"

    # F-138: Siegel erst nach der letzten Signatur – Zeitpunkt vor
    # pdf_fertig_bauen setzen, damit die Bedingung greift.
    protokoll.gegenzeichnung_signiert_am = now

    from . import pdf as pdf_modul
    try:
        # F-137, F-138: Fertiges PDF mit Prüfprotokoll und Siegel.
        pdf_bytes = pdf_modul.pdf_fertig_bauen(protokoll)
    except Exception:
        pdf_bytes = b""
    pdf_hash = _pdf_hash(pdf_bytes)

    code_objekt.verifiziert_am = now
    code_objekt.verifiziert_von_ip = ip
    code_objekt.save()

    protokoll.gegenzeichnung_ip = ip
    protokoll.pdf_hash_gegenzeichnung = pdf_hash
    protokoll.stand = Protokoll.STAND_ABGESCHLOSSEN

    # F-141: Bei Rücknahme – Geräte sofort im Lager.
    if protokoll.art == Protokoll.ART_RUECKNAHME:
        protokoll.ruecknahme_geraet_im_lager = True

    protokoll.save()

    # F-137: Prüfprotokoll-Eintrag für die Gegenzeichnung.
    SignaturAufzeichnung.objects.create(
        protokoll=protokoll,
        art=SignaturAufzeichnung.KIND_GEGENZEICHNUNG,
        name=f"{protokoll.person.vorname} {protokoll.person.nachname}",
        email=protokoll.person.email or protokoll.person.email_arbeit,
        zeitpunkt=now,
        nachweisnummer=protokoll.nr,
        identifikationsmerkmal=f"Einmalcode ({code[:2]}…)",
        ip_adresse=ip,
        hashwert=pdf_hash,
    )

    # --- A-0126 M6 Teil 3: Siegel (F-138) und Versand (F-139) --------------
    # F-137, F-138: pdf_fertig_bauen hat bereits das Siegel angelegt.
    # F-139: Das fertige PDF geht als Anhang an Person und Bearbeiter.
    if pdf_bytes:
        dateiname = pdf_modul.dateiname_protokoll(protokoll)
        protokoll.pdf_siegel = pdf_bytes
        protokoll.pdf_dateiname = dateiname
        protokoll.save()
        _ablage_mit_anhang(protokoll, pdf_bytes, dateiname)
    else:
        _mail_bestätigung(protokoll)

    return protokoll, True, "Gegenzeichnung abgeschlossen."


def protokoll_korrigieren(
    protokoll: Protokoll,
    bearbeiter_konto=None,
) -> tuple[Protokoll, bool]:
    """F-135: Korrektur erzeugt eine neue Fassung mit neuer Nummer.

    Das Original wird gesperrt; die neue Fassung erhält eine neue Nummer
    (UP-JJJJ-NNNN, NNNN+1) und dieselben Daten.
    """
    from konten.zeit import jetzt_wie_im_entwicklungsmodus

    if protokoll.bearbeiter_signiert_am is None:
        # F-135: Nur signierte Protokolle können korrigiert werden.
        return protokoll, False

    # Neue Nummer: NNNN+1 (F-135).
    neue_nr = _naechste_protokollnummer()
    jetzt = jetzt_wie_im_entwicklungsmodus()

    # Original: Korrekturen markieren.
    # (Das Original bleibt bearbeitbar bis die neue Fassung signiert ist.)

    from .models import SignaturCode, SignaturAufzeichnung
    neue = Protokoll.objects.create(
        nr=neue_nr,
        person=protokoll.person,
        geraet=protokoll.geraet,
        datum=protokoll.datum,
        stand=Protokoll.STAND_BEARBEITER_OFFEN,
        erzeugt_von=protokoll.erzeugt_von,
        fotos=protokoll.fotos,
        art=protokoll.art,
        fassung="2.0",
        formularnummer=protokoll.formularnummer,
        absenderzeile=protokoll.absenderzeile,
        empfaenger_anschrift=protokoll.empfaenger_anschrift,
        bearbeiter=protokoll.bearbeiter,
        checkliste=dict(protokoll.checkliste or {}),
        offboarding=dict(protokoll.offboarding or {}),
        anhaenge=list(protokoll.anhaenge or []),
        rueckgabe_zu_protokoll=protokoll.rueckgabe_zu_protokoll,
        ist_korrektur=True,
        korrigiert_zu_protokoll=protokoll,
    )

    # Alte Codes ungültig machen.
    SignaturCode.objects.filter(protokoll=protokoll, gueltig=True).update(
        gueltig=False
    )

    return neue, True
