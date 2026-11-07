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
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from konten.models import Konto
from stammdaten.models import Ausstattungsprofil, Kategorie, Ort, Person, Einstellungen

from .models import Gerat, GeratKonflikt, Importlauf, Leihe, Protokoll, Vorgang
from konten.mail import link_ins_tool, mail_absender, mail_signatur
from konten.zeit import jetzt_aware, jetzt_wie_im_entwicklungsmodus


class GeratFehler(ValueError):
    """Fehler eines Gerät-Vorgangs; die Meldung darf in die Oberfläche."""


# --- Inventarnummer ---------------------------------------------------------

def naechste_inventarnummer() -> str:
    """Nächste freie Inventarnummer im Format WMC-00001 (O-03)."""
    hoechst = Gerat.objects.aggregate(m=Max("inventarnummer"))["m"]
    zaehler = Einstellungen.aktuelles().inventar_zaehler + 1
    if hoechst and str(hoechst).startswith("WMC-"):
        try:
            zaehler = max(zaehler, int(str(hoechst)[4:]) + 1)
        except ValueError:
            pass
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
        erstellt_am=jetzt_aware(),
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
    """Ein Gerät ausgeben (F-20 bis F-23, F-131). Siehe ``geraete_ausgeben``."""
    geraete_ausgeben(
        [gerat],
        ziel,
        ziel_ort=ziel_ort,
        eingaben={gerat.inventarnummer: {
            "zustand": zustand,
            "zubehoer_komplett": zubehoer_komplett,
            "anmerkung": anmerkung,
        }},
        ausgefuehrt_von=ausgefuehrt_von,
        unterschrift=unterschrift,
    )
    return gerat


def _ausgabe_entwurf(gerat: Gerat) -> Protokoll | None:
    """Der offene Entwurf einer Ausgabe oder Leihe, in dem das Gerät steht (F-21).

    Eine Rücknahme sperrt nichts, das Gerät ist da schon im Lager (F-141). Eine neue
    Fassung auch nicht, das Original hat seine Wirkung schon gehabt (F-135).
    """
    return gerat.alle_protokolle().filter(
        stand=Protokoll.STAND_BEARBEITER_OFFEN, art=Protokoll.ART_AUSGABE, ist_korrektur=False,
    ).first()


def _zustand_pruefen(wert, gerat: Gerat) -> int | None:
    """Der Zustand kommt aus dem Formular: leer oder eine der vier Stufen (Kapitel 3.2)."""
    if wert in (None, ""):
        return None
    if str(wert) not in {str(stufe) for stufe, _text in Gerat.ZUSTAENDE}:
        raise GeratFehler(f"{gerat.inventarnummer}: Bitte einen der vier Zustände wählen.")
    return int(wert)


def _ohne_ausgabe_entwurf(gerat: Gerat) -> None:
    """F-21: Solange ein Entwurf offen ist, ändert sich am Gerät nichts."""
    entwurf = _ausgabe_entwurf(gerat)
    if entwurf is not None:
        raise GeratFehler(
            f"Für dieses Gerät steht ein offenes Protokoll ({entwurf.nr}). "
            "Bitte zuerst signieren oder verwerfen."
        )


def ausgabe_sperrgrund(gerat: Gerat) -> str:
    """Warum dieses Gerät nicht ausgegeben werden kann (F-20, F-21); leer, wenn es geht."""
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        return "Ausgemusterte Geräte können nicht ausgegeben werden."
    if gerat.status == Gerat.STATUS_IN_REPARATUR:
        return "Geräte in Reparatur können nicht ausgegeben werden."
    # Kapitel 4: Nur „Auf Lager“; ein Personenwechsel läuft über die Rückgabe.
    if gerat.status != Gerat.STATUS_AUF_LAGER:
        return "Nur Geräte „Auf Lager“ können ausgegeben werden. Bitte zuerst zurücknehmen."
    if _ausgabe_entwurf(gerat) is not None:
        return (
            "Für dieses Gerät steht bereits ein offenes Protokoll. "
            "Eine weitere Ausgabe ist solange nicht möglich."
        )
    if _gerat_ist_reserviert(gerat):
        return "Gerät ist reserviert und kann nicht ausgegeben werden."
    return ""


def _ausgabe_notiz(nummer: str, position: dict) -> str:
    """Text des Vorgangs „Ausgabe“: Protokoll, Zustand, Zubehör, Bemerkung (F-131)."""
    teile = [f"Protokoll {nummer}"] if nummer else []
    if position.get("zustand_ausgabe"):
        stufe = int(position["zustand_ausgabe"])
        teile.append("Zustand: " + dict(Gerat.ZUSTAENDE).get(stufe, str(stufe)))
    if position.get("zubehoer_komplett") is not None:
        teile.append("Zubehör komplett: " + ("Ja" if position["zubehoer_komplett"] else "Nein"))
    if position.get("bemerkung"):
        teile.append(position["bemerkung"])
    return ", ".join(teile)


@transaction.atomic
def geraete_ausgeben(
    geraete: list,
    ziel: Person | Ort,
    *,
    ziel_ort: Ort | None = None,
    eingaben: dict | None = None,
    ausgefuehrt_von: Konto | None = None,
    unterschrift: str = "papier",
) -> Protokoll | None:
    """Ein oder mehrere Geräte ausgeben, mit einem Protokoll (F-20 bis F-23, F-131).

    Ziel ist eine Person, dazu optional ein Arbeitsplatz, oder nur ein Ort vom Typ
    Arbeitsplatz oder Raum. ``eingaben`` trägt je Inventarnummer ``zustand``,
    ``zubehoer_komplett`` und ``anmerkung`` aus dem Dialog.

    Unterschrift „tool“: Die Geräte bleiben „Auf Lager“, das Protokoll steht auf
    „bearbeiter-offen“; Status, Person und Ort kommen mit der Signatur (F-21).
    Unterschrift „papier“: sofort „In Benutzung“ (F-22). Ohne Person kein Protokoll (F-23).
    """
    if not geraete:
        raise GeratFehler("Kein Gerät gewählt.")
    for gerat in geraete:
        grund = ausgabe_sperrgrund(gerat)
        if grund:
            raise GeratFehler(f"{gerat.inventarnummer}: {grund}" if len(geraete) > 1 else grund)

    person = ziel if isinstance(ziel, Person) else None
    ort = ziel if isinstance(ziel, Ort) else ziel_ort
    if person is None and ort is None:
        raise GeratFehler("Ausgabeziel muss eine Person oder ein Ort sein.")
    # F-20: Ausgegeben wird an Arbeitsplätze und Räume, das Lager ist kein Ziel.
    if ort is not None and ort.typ not in (Ort.TYP_ARBEITSPLATZ, Ort.TYP_RAUM):
        raise GeratFehler("Ausgegeben wird an einen Arbeitsplatz oder Raum, nicht ans Lager.")

    positionen = []
    for gerat in geraete:
        werte = (eingaben or {}).get(gerat.inventarnummer, {})
        positionen.append(position_aus_gerat(
            gerat,
            zustand_ausgabe=_zustand_pruefen(werte.get("zustand"), gerat),
            zubehoer_komplett=werte.get("zubehoer_komplett", True),
            bemerkung=(werte.get("anmerkung") or "").strip(),
        ))

    protokoll = None
    if person is not None:
        tool = unterschrift == "tool"
        protokoll = _protokoll_erstellen(
            person=person,
            gerat=geraete[0],
            art=Protokoll.ART_AUSGABE,
            bearbeiter=ausgefuehrt_von.bezeichnung() if ausgefuehrt_von is not None else "",
            erzeugt_von=ausgefuehrt_von,
            stand=Protokoll.STAND_BEARBEITER_OFFEN if tool else Protokoll.STAND_SCAN_OFFEN,
            unterschrift_art="tool" if tool else "papier",
            ort_ziel=ort,
            positionen=positionen,
        )
        protokoll.weitere_geraete.set(geraete[1:])
        if tool:
            return protokoll

    for gerat, position in zip(geraete, positionen):
        gerat.status = Gerat.STATUS_IN_BENUTZUNG
        gerat.person = person
        gerat.ort = ort
        gerat.altbestand_ohne_protokoll = False
        gerat.zustand = int(position["zustand_ausgabe"])
        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_AUSGABE,
            zeitpunkt=jetzt_aware(),
            erzeugt_von=ausgefuehrt_von,
            leihgabe_an=person,
            notiz=_ausgabe_notiz(protokoll.nr if protokoll else "", position),
            protokoll=protokoll,
            abschliesst=True,
        )
        gerat.save()
    return protokoll


def position_aus_gerat(
    gerat: Gerat,
    *,
    zustand_ausgabe=None,
    zustand_rueckgabe=None,
    zubehoer_komplett=True,
    bemerkung: str = "",
    ausgabe_protokoll: str = "",
) -> dict:
    """Eine Zeile der Gerätetabelle im Protokoll (F-21, F-50, F-131)."""
    return {
        "inventarnummer": gerat.inventarnummer,
        "bezeichnung": f"{gerat.hersteller} {gerat.modell}".strip(),
        "geraetename": gerat.geraetename,
        "seriennummer": gerat.seriennummer,
        "standardzubehoer": gerat.standardzuehoer,
        "zustand_ausgabe": zustand_ausgabe if zustand_ausgabe is not None else gerat.zustand,
        "zustand_rueckgabe": zustand_rueckgabe,
        "zubehoer_komplett": zubehoer_komplett,
        "bemerkung": bemerkung,
        "ausgabe_protokoll": ausgabe_protokoll,
    }


def protokolltexte(art: str) -> dict:
    """Texte und Prüfpunkte, die für ein neues Protokoll gelten (F-130, F-132, F-133)."""
    from stammdaten import checklisten

    e = Einstellungen.aktuelles()
    punkte = {
        liste: [list(punkt) for punkt in checklisten.aktive_punkte(liste)]
        for liste in (checklisten.ZUGAENGE, checklisten.OFFBOARDING)
    }
    if art == Protokoll.ART_RUECKNAHME:
        return {
            "nutzung": "",
            "erklaerung": e.erklaerungen_ruecknahme,
            "unterzeichnung": e.unterzeichnung_ruecknahme,
            "version": f"{e.erklaerungen_ruecknahme_version} / {e.unterzeichnung_ruecknahme_version}",
            "punkte": punkte,
        }
    return {
        "nutzung": e.nutzungsbedingungen_ausgabe,
        "erklaerung": e.erklaerungen_ausgabe,
        "unterzeichnung": e.unterzeichnung_ausgabe,
        "version": f"{e.nutzungsbedingungen_version} / {e.erklaerungen_version} / {e.unterzeichnung_version}",
        "punkte": punkte,
    }


def _absenderzeile() -> str:
    from stammdaten.models import Einstellungen
    return Einstellungen.aktuelles().absenderzeile


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
    positionen: list | None = None,
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
        # TESTSCHNITTSTELLE 1.2: Datum nach der Zeit der Anwendung (F-95 rechnet damit).
        datum=jetzt_wie_im_entwicklungsmodus().date(),
        stand=stand,
        art=art,
        fassung="1.1",
        formularnummer=(
            "FRM-002" if art == Protokoll.ART_RUECKNAHME else "FRM-001"
        ),
        absenderzeile=_absenderzeile(),
        positionen=positionen if positionen is not None else [position_aus_gerat(gerat)],
        texte=protokolltexte(art),
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
    loeschung_datei=None,
    bestaetigt_gemeldt: bool = False,
    ausgefuehrt_von: Konto | None = None,
) -> Gerat:
    """Gerät ausmustern (F-55 bis F-58, Kapitel 4).

    F-55: Grund, Datum und Verbleib sind immer Pflicht. Ausgemustert wird nur aus
    „Auf Lager“ oder „In Reparatur“; „verloren“ und „gestohlen“ gehen aus jedem Status.
    F-56: Bei Datenträgern Art der Löschung und Nachweis (Datei oder Nummer).
    F-57: Bei Verlust und Diebstahl statt dessen die Bestätigung der Meldung.
    F-58: Danach bleibt das Gerät lesbar und ist nicht mehr änderbar.
    """
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Gerät ist bereits ausgemustert.")
    _ohne_ausgabe_entwurf(gerat)
    reservierungen = list(Leihe.objects.filter(gerat=gerat, status=Leihe.STATUS_GENEHMIGT))
    if reservierungen and grund not in AUSMUSTERUNG_VERLOREN:
        raise GeratFehler(
            f"Das Gerät ist für die Leihe {reservierungen[0].nr} reserviert. "
            "Bitte zuerst die Reservierung aufheben."
        )
    if not grund:
        raise GeratFehler("Grund der Ausmusterung muss angegeben werden.")
    if not datum:
        raise GeratFehler("Datum der Ausmusterung muss angegeben werden.")
    if not (disposition or "").strip():
        raise GeratFehler("Verbleib muss angegeben werden.")
    verloren = grund in AUSMUSTERUNG_VERLOREN
    if not verloren and gerat.status not in (Gerat.STATUS_AUF_LAGER, Gerat.STATUS_IN_REPARATUR):
        raise GeratFehler(
            "Aus diesem Status lässt sich nur mit Grund „verloren“ oder „gestohlen“ ausmustern (Kapitel 4). "
            "Bitte zuerst zurücknehmen."
        )
    if gerat.kategorie.hat_datentraeger and not verloren:
        if not loeschung_art:
            raise GeratFehler("Art der Löschung muss angegeben werden.")
        if not loeschung_nachweis and not loeschung_datei:
            raise GeratFehler("Nachweis der Löschung muss angegeben werden.")
    if verloren and not bestaetigt_gemeldt:
        raise GeratFehler("Pflichtbestätigung, dass der Vorfall gemeldet wurde.")

    teile = []
    if not verloren and loeschung_art:
        teile.append("Löschung: " + LOESCHUNG_ARTEN.get(loeschung_art, loeschung_art))
    if not verloren and loeschung_nachweis:
        teile.append("Nachweis: " + loeschung_nachweis)
    if verloren:
        teile.append("Vorfall an Datenschutz bzw. Informationssicherheit gemeldet")

    _leihen_beenden(gerat, verloren=verloren)
    # Verloren oder gestohlen: Die reservierte Leihe kann nicht stattfinden, die Person erfährt es.
    for leihe in reservierungen:
        leihe_ablehnen(leihe, f"Das Gerät wurde als {grund} gemeldet.", ausgefuehrt_von)
    for leihe in Leihe.objects.filter(gerat=gerat, status=Leihe.STATUS_ANGEFRAGT):
        leihe_ablehnen(leihe, "Das Gerät wurde ausgemustert.", ausgefuehrt_von)
    gerat.reserviert = False
    gerat.reserviert_bis = None
    gerat.status = Gerat.STATUS_AUSGEMUSTERT
    gerat.person = None
    gerat.ort = None
    vorgang = Vorgang(
        gerat=gerat,
        typ=Vorgang.TYP_AUSMUSTERUNG,
        zeitpunkt=jetzt_aware(),
        erzeugt_von=ausgefuehrt_von,
        ausmusterung_grund=grund,
        ausmusterung_datum=datum,
        ausmusterung_disposition=disposition.strip(),
        loeschung_art="" if verloren else loeschung_art,
        loeschung_nachweis="" if verloren else loeschung_nachweis,
        vorfall_gemeldet=bool(verloren and bestaetigt_gemeldt),
        notiz=", ".join(teile),
        abschliesst=True,
    )
    if loeschung_datei and not verloren:
        vorgang.nachweis_datei.save(*_nachweis_pruefen(loeschung_datei), save=False)
    vorgang.save()
    gerat.save()
    return gerat


AUSMUSTERUNG_VERLOREN = ("verloren", "gestohlen")
LOESCHUNG_ARTEN = {
    "nist": "Gelöscht durch die IT nach NIST SP 800-88",
    "zerstoert": "Physisch zerstört durch Dienstleister",
}
_ANHANG_ENDUNGEN = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
_ANHANG_GROESSE = 10 * 1024 * 1024


def _nachweis_pruefen(datei, wort: str = "Nachweis") -> tuple:
    """Anhang: PDF, JPG oder PNG bis 10 MB, am Inhalt geprüft (Kapitel 3.1, N-02)."""
    from django.core.files.base import ContentFile
    from .protokoll import _typ_am_inhalt

    roh = datei.read(_ANHANG_GROESSE + 1)
    if len(roh) > _ANHANG_GROESSE:
        raise GeratFehler(f"Der {wort} ist größer als 10 MB.")
    endung = _ANHANG_ENDUNGEN.get(_typ_am_inhalt(roh) or "")
    if endung is None:
        raise GeratFehler(f"{wort} nicht erlaubt: PDF, JPG oder PNG bis 10 MB.")
    return f"nachweis-{jetzt_aware():%Y%m%d-%H%M%S}{endung}", ContentFile(roh)


def anhang_hinzufuegen(gerat: Gerat, datei, ausgefuehrt_von: Konto | None = None):
    """Kapitel 3.1: PDF, JPG oder PNG bis 10 MB am Gerät, mit Eintrag in der Historie."""
    from .models import GeratAnhang

    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Ausgemusterte Geräte sind nicht mehr änderbar.")
    if datei is None:
        raise GeratFehler("Bitte eine Datei wählen.")
    pfad, inhalt = _nachweis_pruefen(datei, "Anhang")
    # Die Endung kommt vom geprüften Typ, nicht vom Hochladenden.
    stamm = (getattr(datei, "name", "") or "Anhang").rsplit(".", 1)[0][:190] or "Anhang"
    name = f"{stamm}.{pfad.rsplit('.', 1)[-1]}"
    anhang = GeratAnhang(gerat=gerat, name=name, hochgeladen_am=jetzt_aware(), hochgeladen_von=ausgefuehrt_von)
    anhang.datei.save(pfad.replace("nachweis-", "anhang-"), inhalt, save=False)
    anhang.save()
    Vorgang.objects.create(
        gerat=gerat, typ=Vorgang.TYP_AENDERUNG, zeitpunkt=jetzt_aware(), erzeugt_von=ausgefuehrt_von,
        notiz=f"Anhang hinzugefügt: {name}", abschliesst=True,
    )
    return anhang


def standard_lager() -> Ort | None:
    """Der Lagerort, wenn der Dialog keinen nennt (Kapitel 4: Auf Lager heißt Lagerort)."""
    return Ort.objects.filter(typ=Ort.TYP_LAGER).order_by("kennung").first()


def _ausgabeprotokoll_fuer(gerat: Gerat, person: Person) -> Protokoll | None:
    return (
        gerat.alle_protokolle()
        .filter(person=person, art=Protokoll.ART_AUSGABE)
        .exclude(stand=Protokoll.STAND_ERSETZT)
        .first()
    )


def zustand_bei_ausgabe(gerat: Gerat):
    """Zustand laut Ausgabeprotokoll (F-50, F-131); ohne Protokoll leer."""
    if gerat.person_id is None:
        return ""
    quelle = _ausgabeprotokoll_fuer(gerat, gerat.person)
    if quelle is None:
        return ""
    for position in quelle.positionen or []:
        if position.get("inventarnummer") == gerat.inventarnummer and position.get("zustand_ausgabe"):
            return position["zustand_ausgabe"]
    return gerat.zustand


def _ja(wert) -> bool:
    """Der Dialog liefert „ja“ und „nein“, Aufrufer im Code True und False."""
    return wert == "ja" if isinstance(wert, str) else bool(wert)


@transaction.atomic
def geraete_zuruecknehmen(
    person: Person | None,
    posten: list,
    *,
    ausgefuehrt_von: Konto | None = None,
    unterschrift: str = "tool",
    empfaenger: str = "",
) -> Protokoll | None:
    """Ein oder mehrere Geräte zurücknehmen, mit einem Protokoll (F-50, F-51, F-52, F-141).

    Je Posten ``gerat``, ``zustand_rueckgabe``, ``zubehoer_komplett``, ``maengel``,
    ``ziel`` („lager“ oder „reparatur“) und optional ``lagerort``. Die Geräte sind sofort
    im Lager, das Protokoll wartet auf beide Signaturen (F-141), beim Papierweg auf den
    Scan (F-22). ``empfaenger`` ist die Adresse für den Link bei Rückgabe per Post.
    """
    if not posten:
        raise GeratFehler("Kein Gerät gewählt.")
    positionen = []
    grundlage = None
    for eintrag in posten:
        gerat = eintrag["gerat"]
        if gerat.status not in (
            Gerat.STATUS_IN_BENUTZUNG, Gerat.STATUS_VERLIEHEN, Gerat.STATUS_IN_REPARATUR,
        ):
            raise GeratFehler("Nur Geräte in Benutzung oder verliehen können zurückgegeben werden.")
        quelle = _ausgabeprotokoll_fuer(gerat, person) if person is not None else None
        grundlage = grundlage or quelle
        positionen.append(position_aus_gerat(
            gerat,
            zustand_ausgabe=zustand_bei_ausgabe(gerat),
            zustand_rueckgabe=_zustand_pruefen(eintrag["zustand_rueckgabe"], gerat) or gerat.zustand,
            zubehoer_komplett=_ja(eintrag.get("zubehoer_komplett", True)),
            bemerkung=(eintrag.get("maengel") or "").strip(),
            ausgabe_protokoll=quelle.nr if quelle is not None else "",
        ))

    protokoll = None
    if person is not None:
        tool = unterschrift == "tool"
        protokoll = _protokoll_erstellen(
            person=person,
            gerat=posten[0]["gerat"],
            art=Protokoll.ART_RUECKNAHME,
            bearbeiter=ausgefuehrt_von.bezeichnung() if ausgefuehrt_von is not None else "",
            erzeugt_von=ausgefuehrt_von,
            stand=Protokoll.STAND_BEARBEITER_OFFEN if tool else Protokoll.STAND_SCAN_OFFEN,
            unterschrift_art="tool" if tool else "papier",
            rueckgabe_zu_protokoll=grundlage,
            offboarding=_offboarding_vorbelegung(posten[0]["gerat"], person, ausgefuehrt_von),
            positionen=positionen,
            leihe=Leihe.objects.filter(gerat=posten[0]["gerat"], status=Leihe.STATUS_AUSGEGEBEN).first(),
        )
        protokoll.weitere_geraete.set([e["gerat"] for e in posten[1:]])
        if empfaenger.strip():
            protokoll.gegenzeichnung_empfaenger = empfaenger.strip()
            protokoll.save(update_fields=["gegenzeichnung_empfaenger"])

    for eintrag, position in zip(posten, positionen):
        gerat = eintrag["gerat"]
        gerat.zustand = position["zustand_rueckgabe"]
        _leihen_beenden(gerat)
        if gerat.status == Gerat.STATUS_IN_REPARATUR:
            # Bleibt beim Dienstleister, die gemerkte Zuordnung endet hier.
            gerat.ort = None
        elif eintrag.get("ziel") == "reparatur":
            gerat.status = Gerat.STATUS_IN_REPARATUR
            gerat.ort = None
        else:
            gerat.status = Gerat.STATUS_AUF_LAGER
            gerat.ort = eintrag.get("lagerort") or standard_lager()
        in_reparatur = gerat.status == Gerat.STATUS_IN_REPARATUR
        gerat.person = None
        gerat.altbestand_ohne_protokoll = False
        teile = [f"Protokoll {protokoll.nr}"] if protokoll is not None else []
        teile += [
            f"Zustand: {position['zustand_rueckgabe']}",
            "Zubehör komplett: " + ("Ja" if position["zubehoer_komplett"] else "Nein"),
            f"Mängel: {position['bemerkung']}",
        ]
        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_RUECKGABE,
            zeitpunkt=jetzt_aware(),
            erzeugt_von=ausgefuehrt_von,
            notiz=", ".join(teile),
            protokoll=protokoll,
            abschliesst=True,
        )
        if in_reparatur and eintrag.get("ziel") == "reparatur":
            # F-42: Die Reparatur läuft, Dienstleister und Vorgangsnummer trägt die IT nach.
            Vorgang.objects.create(
                gerat=gerat,
                typ=Vorgang.TYP_REPARATUR,
                zeitpunkt=jetzt_aware(),
                erzeugt_von=ausgefuehrt_von,
                reperatur_anleitung="Aus der Rückgabe. Dienstleister und Vorgangsnummer noch nicht erfasst.",
                abschliesst=False,
            )
        gerat.save()
    return protokoll


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
    unterschrift: str = "tool",
    empfaenger: str = "",
    lagerort: Ort | None = None,
) -> Gerat:
    """Ein Gerät zurücknehmen (F-50). Siehe ``geraete_zuruecknehmen``.

    „Fehlt“ führt in den Dialog Ausmustern mit Grund „verloren“; die Meldung
    an den Datenschutz bestätigt dort ein Mensch (F-57), nicht dieser Aufruf.
    """
    if gerat.status not in (Gerat.STATUS_IN_BENUTZUNG, Gerat.STATUS_VERLIEHEN):
        raise GeratFehler("Nur Geräte in Benutzung oder verliehen können zurückgegeben werden.")
    if fehlend:
        raise GeratFehler("Ein fehlendes Gerät läuft über den Dialog Ausmustern mit Grund „verloren“.")
    geraete_zuruecknehmen(
        gerat.person,
        [{
            "gerat": gerat,
            "zustand_rueckgabe": zustand_rueckgabe,
            "zubehoer_komplett": zubesehoer_komplett,
            "maengel": maengel,
            "ziel": ziel,
            "lagerort": lagerort,
        }],
        ausgefuehrt_von=ausgefuehrt_von,
        unterschrift=unterschrift,
        empfaenger=empfaenger,
    )
    return gerat


def _bearbeiter_kuerzel(konto: Konto | None) -> str:
    if konto is None:
        return ""
    person = getattr(konto, "person", None)
    if person is not None:
        return person.kuerzel
    return "".join(teil[0] for teil in konto.bezeichnung().replace("@", " ").split()[:2]).upper()


def _offboarding_vorbelegung(gerat: Gerat, person: Person, konto: Konto | None = None) -> dict:
    """FRM-002 Abschnitt 3: Vorbelegung der 13 Prüfpunkte IT-Offboarding.

    Bei Austritt (Person hat ein Austrittsdatum) ist nur Punkt 13 gesetzt, den Rest
    beantwortet die IT. Jede andere Rückgabe: Punkte 1 und 13 erledigt, die übrigen
    nicht zutreffend.
    """
    from stammdaten.checklisten import PUNKT_INVENTAR, PUNKT_ZURUECKSETZEN

    schluessel = [k for k, _text in Protokoll.OFFBOARDING_PUNKTE]
    erledigt = {
        "status": "erledigt",
        "datum": jetzt_aware().strftime("%d.%m.%Y"),
        "kuerzel": _bearbeiter_kuerzel(konto),
        "bemerkung": "",
    }
    if getattr(person, "austritt", None):
        return {PUNKT_INVENTAR: erledigt}
    vorbelegung = {
        k: {"status": "nicht_zutreffend", "datum": "", "kuerzel": "", "bemerkung": ""}
        for k in schluessel
    }
    vorbelegung[PUNKT_ZURUECKSETZEN] = dict(erledigt)
    vorbelegung[PUNKT_INVENTAR] = dict(erledigt)
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
    # Kapitel 4: Nur „In Benutzung“ kennt den Umzug; ins Lager führt die Rückgabe.
    if gerat.status != Gerat.STATUS_IN_BENUTZUNG:
        raise GeratFehler("Nur Geräte in Benutzung können umgezogen werden.")
    if gerat.ort_id == ziel_ort.pk:
        raise GeratFehler("Das Gerät steht schon an diesem Ort.")
    if ziel_ort.typ == Ort.TYP_LAGER:
        raise GeratFehler("Ziel eines Umzugs ist ein Arbeitsplatz oder Raum; ins Lager führt die Rückgabe.")

    alter_ort = gerat.ort
    gerat.ort = ziel_ort
    gerat.altbestand_ohne_protokoll = False

    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_UMZUG,
        zeitpunkt=jetzt_aware(),
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
    nachtragen: bool = False,
) -> Gerat:
    """Reparatur starten (F-42, M3).

    Start mit Dienstleister, Vorgangsnummer und Notiz. ``nachtragen``: Das Gerät kam
    aus einer Rückgabe in Reparatur, die Angaben folgen jetzt (F-50).
    """
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Ausgemusterte Geräte können nicht repariert werden.")
    erlaubt = (Gerat.STATUS_AUF_LAGER, Gerat.STATUS_IN_BENUTZUNG)
    if nachtragen:
        erlaubt += (Gerat.STATUS_IN_REPARATUR,)
    if gerat.status not in erlaubt:
        raise GeratFehler("Nur Geräte auf Lager oder in Benutzung können repariert werden.")
    _ohne_ausgabe_entwurf(gerat)

    gerat.status = Gerat.STATUS_IN_REPARATUR

    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_REPARATUR,
        zeitpunkt=jetzt_aware(),
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
    lagerort: Ort | None = None,
    zubehoer_komplett: bool = True,
    maengel: str = "",
    unterschrift: str = "tool",
    empfaenger: str = "",
) -> Gerat:
    """Reparatur abschließen (F-42, M3).

    Abschluss mit neuem Zustand und Ziel „bisherige Zuordnung" oder „Lager".
    Hatte das Gerät eine Person, läuft „Lager“ über dieselbe Rücknahme wie am Gerät,
    mit Protokoll und Signatur (Erwin 05.11.).
    """
    if gerat.status != Gerat.STATUS_IN_REPARATUR:
        raise GeratFehler("Nur Geräte in Reparatur können repariert werden.")

    gerat.zustand = zustand
    ruecknahme = ziel != "zuordnung" and gerat.person_id is not None

    if ziel == "zuordnung":
        # F-42: Ziel „Bisherige Zuordnung" – Gerät geht zurück zu Person/Ort.
        # Ein Gerät, das vor der Reparatur im Lager stand, ist danach wieder „Auf Lager“.
        if gerat.person is None and (gerat.ort is None or gerat.ort.typ == Ort.TYP_LAGER):
            gerat.status = Gerat.STATUS_AUF_LAGER
            gerat.ort = gerat.ort or standard_lager()
        else:
            gerat.status = Gerat.STATUS_IN_BENUTZUNG
    elif not ruecknahme:
        # F-42: Ziel „Lager"
        gerat.status = Gerat.STATUS_AUF_LAGER
        gerat.person = None
        gerat.ort = lagerort or standard_lager()

    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_REPARATUR,
        zeitpunkt=jetzt_aware(),
        erzeugt_von=ausgefuehrt_von,
        reparatur_kosten=kosten,
        reparatur_beleg=beleg,
        reparatur_ziel=ziel,
        notiz=f"Zustand: {zustand}, Ziel: " + {"lager": "Lager", "zuordnung": "bisherige Zuordnung"}.get(ziel, ziel),
        abschliesst=True,
    )
    gerat.save()
    if ruecknahme:
        # Die Rücknahme setzt Lager und Person; die Historie bleibt ohne Zwischenstand.
        gerat.status = Gerat.STATUS_IN_BENUTZUNG
        geraete_zuruecknehmen(
            gerat.person,
            [{
                "gerat": gerat, "zustand_rueckgabe": zustand, "ziel": "lager", "lagerort": lagerort,
                "zubehoer_komplett": zubehoer_komplett, "maengel": maengel,
            }],
            ausgefuehrt_von=ausgefuehrt_von,
            unterschrift=unterschrift or "tool",
            empfaenger=empfaenger,
        )
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
        "leihpool", "ort", "geraetename", "standardzuehoer",
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
                zeitpunkt=jetzt_aware(),
                erzeugt_von=erzeugt_von,
                aenderung_feld=name,
                aenderung_alter_wert=alter,
                aenderung_neuer_wert=neuer,
                abschliesst=True,
            )
    # F-88: Wer den Zustand einträgt, hat ihn gesehen; der Vermerk „ungeprüft“ endet.
    if "zustand" in werte and _wert_anzeigen_wert(werte["zustand"]) != _wert_anzeigen(gerat, "zustand"):
        gerat.zustand_ungeprueft = False
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
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Ausgemusterte Geräte sind nicht mehr änderbar.")
    jetzt = jetzt_aware()
    gerat.zuletzt_geprueft_am = jetzt
    gerat.zuletzt_geprueft_von = geprueft_von
    # F-88: Wer das Gerät in der Hand hatte, hat den Zustand gesehen.
    gerat.zustand_ungeprueft = False
    gerat.save()
    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_AENDERUNG,
        zeitpunkt=jetzt,
        erzeugt_von=geprueft_von,
        notiz="Geprüft bei der Erstinventur.",
        abschliesst=True,
    )
    return gerat


@transaction.atomic
def erstinventur_bestaetigen(
    gerat: Gerat, *, werte: dict, ziel_ort: Ort | None, geprueft_von: Konto,
) -> Gerat:
    """Erstinventur am Gerät (F-89): Lücken nachtragen, Verbleib bestätigen, „Geprüft“.

    ``werte`` trägt nur, was im Dialog geändert wurde. ``ziel_ort`` ist der Ort,
    an dem das Gerät tatsächlich steht, wenn es nicht der eingetragene ist.
    """
    from . import import_parser

    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Ausgemusterte Geräte sind nicht mehr änderbar.")
    if werte:
        gerat_bearbeiten(gerat, werte=werte, erzeugt_von=geprueft_von)
    if ziel_ort is not None and ziel_ort.pk != gerat.ort_id:
        if gerat.status == Gerat.STATUS_IN_BENUTZUNG:
            gerat_umziehen(gerat, ziel_ort, ausgefuehrt_von=geprueft_von)
        elif gerat.status == Gerat.STATUS_AUF_LAGER and ziel_ort.typ == Ort.TYP_LAGER:
            gerat_bearbeiten(gerat, werte={"ort": ziel_ort}, erzeugt_von=geprueft_von)
        elif gerat.status == Gerat.STATUS_AUF_LAGER and import_parser.ist_importiert_unbewegt(gerat):
            # F-85: Auch vor Ort festgestellt gilt: Arbeitsplatz heißt In Benutzung, Altbestand.
            gerat.status = Gerat.STATUS_IN_BENUTZUNG
            gerat.altbestand_ohne_protokoll = True
            gerat.save(update_fields=["status", "altbestand_ohne_protokoll"])
            gerat_bearbeiten(gerat, werte={"ort": ziel_ort}, erzeugt_von=geprueft_von)
        else:
            raise GeratFehler(
                "Dieses Gerät kommt nur über eine Ausgabe an einen Arbeitsplatz oder Raum."
            )
    return gerat_pruefen(gerat, geprueft_von)


# --- Importkonflikte (F-84, F-86, F-88) ---------------------------------------

@transaction.atomic
def konflikt_anlegen(
    gerat: Gerat, feld: str, alter_wert: str, neuer_wert: str, herkunft: str = ""
) -> GeratKonflikt:
    """Offenen Importkonflikt anlegen (F-86, F-88)."""
    return GeratKonflikt.objects.create(
        gerat=gerat, feld=feld, alter_wert=alter_wert,
        neuer_wert=neuer_wert, herkunft=herkunft, offen=True,
        erzeugt_am=jetzt_aware(),
    )


def _konfliktwert_uebernehmen(konflikt: GeratKonflikt, ausgefuehrt_von: Konto | None) -> None:
    """Den neuen Wert ans Gerät schreiben, je Feld in seinem Typ (F-84), mit Historie (F-43)."""
    from decimal import Decimal, InvalidOperation

    from . import import_parser

    gerat = konflikt.gerat
    feld = konflikt.feld
    wert: object = konflikt.neuer_wert
    if feld in ("kaufdatum", "garantie_bis"):
        wert = import_parser.datum_aus_text(konflikt.neuer_wert)
    elif feld == "kategorie":
        wert = Kategorie.objects.filter(name=konflikt.neuer_wert).first()
        if wert is None:
            raise GeratFehler("Diese Kategorie gibt es nicht mehr.")
    elif feld == "kaufpreis_netto":
        try:
            wert = Decimal(konflikt.neuer_wert)
        except InvalidOperation as e:
            raise GeratFehler("Der neue Kaufpreis ist keine Zahl.") from e
    elif feld in ("person", "ort"):
        # Kapitel 4: Personenwechsel und Umzug sind Vorgänge. Beim Altbestand
        # gab es noch keinen; dort berichtigt der Konflikt nur die alte Liste.
        if not gerat.altbestand_ohne_protokoll:
            raise GeratFehler(
                "Dieses Gerät wurde schon bewegt: Person und Ort ändern sich nur über Rückgabe, "
                "Ausgabe oder Umzug."
            )
        if feld == "person":
            wert = _person_aus_ziel(konflikt.neuer_wert)
        else:
            wert = Ort.objects.filter(kennung=konflikt.neuer_wert).first()
            if wert is None:
                wert, _ = Ort.objects.get_or_create(
                    kennung=import_parser.neue_kennung(konflikt.neuer_wert),
                    defaults={"typ": Ort.TYP_ARBEITSPLATZ},
                )
    setattr(gerat, feld, wert)
    gerat.save()
    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_AENDERUNG,
        zeitpunkt=jetzt_aware(),
        erzeugt_von=ausgefuehrt_von,
        aenderung_feld=feld,
        aenderung_alter_wert=konflikt.alter_wert,
        aenderung_neuer_wert=konflikt.neuer_wert,
        notiz="Importkonflikt gelöst.",
        abschliesst=True,
    )


@transaction.atomic
def konflikt_loesen(
    konflikt: GeratKonflikt, nehmen: str, ausgefuehrt_von: Konto | None = None
) -> GeratKonflikt:
    """Konflikt lösen: „alten Wert behalten" oder „neuen Wert übernehmen" (F-86)."""
    if nehmen not in ("alt", "neu"):
        raise GeratFehler("Ein Konflikt wird gelöst, indem der alte Wert behalten oder der neue Wert übernommen wird.")
    if konflikt.gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Ausgemusterte Geräte sind nicht mehr änderbar.")
    if nehmen == "neu":
        _konfliktwert_uebernehmen(konflikt, ausgefuehrt_von)
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
    """Alle Geräte einer Person zurücknehmen, mit einem Protokoll (F-52).

    Ohne Eingaben je Gerät: Der Zustand bleibt, Zubehör gilt als komplett.
    Liefert die Anzahl der zurückgenommenen Geräte.
    """
    gerate = geraete_fuers_offboarding(person)
    if gerate:
        geraete_zuruecknehmen(
            person,
            [{"gerat": g, "zustand_rueckgabe": g.zustand, "zubehoer_komplett": True, "maengel": "", "ziel": "lager"}
             for g in gerate],
            ausgefuehrt_von=ausgefuehrt_von,
        )
    return len(gerate)


def geraete_fuers_offboarding(person: Person) -> list[Gerat]:
    """F-52: Alles, was noch bei der Person liegt, auch Geräte in Reparatur."""
    return list(
        Gerat.objects.filter(
            person=person,
            status__in=[Gerat.STATUS_IN_BENUTZUNG, Gerat.STATUS_VERLIEHEN, Gerat.STATUS_IN_REPARATUR],
        ).select_related("kategorie").order_by("inventarnummer")
    )


def vorschlag_fuer_person(person: Person) -> dict | None:
    """F-24: Was dem festen Arbeitsplatz der Person laut Profil fehlt, mit freien Geräten vom Lager."""
    ort = person.feste_plaetze.filter(typ=Ort.TYP_ARBEITSPLATZ).order_by("kennung").first()
    if ort is None:
        return None
    zeilen, nummern = [], []
    for kategorie, anzahl in soll_ist_abgleich(ort)["fehlend"]:
        frei = []
        lager = Gerat.objects.filter(
            status=Gerat.STATUS_AUF_LAGER, kategorie=kategorie, leihpool=False,
        ).order_by("inventarnummer")
        for gerat in lager:
            if len(frei) == anzahl:
                break
            if not ausgabe_sperrgrund(gerat):
                frei.append(gerat)
        zeilen.append({"kategorie": kategorie, "anzahl": anzahl, "geraete": frei})
        nummern += [g.inventarnummer for g in frei]
    if not zeilen:
        return None
    from urllib.parse import urlencode
    abfrage = urlencode(
        [("auswahl", n) for n in nummern] + [("person", person.pk), ("ort", ort.pk)]
    )
    return {"ort": ort, "zeilen": zeilen, "nummern": nummern, "abfrage": abfrage}


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
    („mehr: n x Kategorie"). Ein Gerät „Auf Lager“ ist nicht ausgegeben und
    zählt deshalb nicht zur Ist-Ausstattung, auch wenn es am Platz vermerkt ist.
    """
    soll = dict((k, a) for k, a in soll_zahlen(ort))
    ist: dict[Kategorie, int] = {}
    for gerat in gerate_am_ort(ort):
        if gerat.status == Gerat.STATUS_AUF_LAGER:
            continue
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
    (alle Geräte „Auf Lager", sortiert nach Kategorie). Ein zurückgegebenes
    Gerät hat oft keinen Ort und ist trotzdem auf Lager.
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

    lagerbestand: dict[Kategorie, int] = {}
    for kategorie in summe:
        lagerbestand[kategorie] = _im_lager(kategorie).count()
    zeilen = [
        {"kategorie": k, "fehlt": anzahl, "lager": lagerbestand[k]}
        for k, anzahl in summe.items()
    ]
    return {"summe": summe, "lagerbestand": lagerbestand, "zeilen": zeilen}


def _im_lager(kategorie: Kategorie):
    """Geräte „Auf Lager“ einer Kategorie: am Lagerort oder ohne Ort (Kapitel 4)."""
    from django.db.models import Q

    return Gerat.objects.filter(kategorie=kategorie, status=Gerat.STATUS_AUF_LAGER).filter(
        Q(ort__isnull=True) | Q(ort__typ=Ort.TYP_LAGER)
    )


def fehlendes_vom_lager(ort: Ort) -> list[dict]:
    """F-66: Je fehlender Kategorie die freien Lagergeräte (ohne reservierte, F-20)."""
    zeilen = []
    for kategorie, fehlt in soll_ist_abgleich(ort)["fehlend"]:
        frei = [
            g for g in _im_lager(kategorie).order_by("inventarnummer")
            if not _gerat_ist_reserviert(g)
        ]
        zeilen.append(
            {
                "kategorie": kategorie,
                "fehlt": fehlt,
                "geraete": [
                    {"gerat": g, "vorbelegt": i < fehlt} for i, g in enumerate(frei)
                ],
            }
        )
    return zeilen


@transaction.atomic
def fehlendes_ausgeben(ort: Ort, geraete_ids: list[int], *, ausgefuehrt_von: Konto) -> int:
    """F-66: Gewählte Lagergeräte an den Arbeitsplatz ausgeben, alle oder keins.

    Nur freie Geräte einer fehlenden Kategorie, je Kategorie höchstens so viele,
    wie fehlen. Das Gerät gehört zum Platz, nicht zu einer Person, also kein
    Protokoll (Kapitel 3.2).
    """
    zeilen = fehlendes_vom_lager(ort)
    erlaubt = {e["gerat"].pk: z for z in zeilen for e in z["geraete"]}
    if not geraete_ids:
        raise GeratFehler("Bitte mindestens ein Gerät wählen.")
    gewaehlt = {int(i) for i in geraete_ids if str(i).isdigit()}
    if len(gewaehlt) < len(set(geraete_ids)) or not gewaehlt <= erlaubt.keys():
        raise GeratFehler("Ein gewähltes Gerät ist nicht mehr frei. Bitte erneut wählen.")
    for z in zeilen:
        anzahl = sum(1 for e in z["geraete"] if e["gerat"].pk in gewaehlt)
        if anzahl > z["fehlt"]:
            raise GeratFehler(
                f"Für {z['kategorie'].name} fehlen nur {z['fehlt']}, gewählt sind {anzahl}."
            )
    for gerat in Gerat.objects.filter(pk__in=gewaehlt).order_by("inventarnummer"):
        gerat_ausgeben(
            gerat, ort, ausgefuehrt_von=ausgefuehrt_von, anmerkung="Fehlendes vom Lager"
        )
    return len(gewaehlt)


# --- Erstinventur (F-89, AUFTRAG M4) ------------------------------------------

def fortschritt_je_ort(orte: list[Ort] | None = None) -> list[dict]:
    """Fortschritt: geprüfte Geräte / alle Geräte, auch je Ort (F-89).

    Geprüft = „Zuletzt geprüft" gesetzt und das Gerät ist erfasst
    (nicht ausgemustert, nicht in Reparatur).
    """
    if orte is None:
        # F-89: „auch je Ort“: Arbeitsplätze, Räume und Lager, nicht nur Arbeitsplätze.
        orte = list(Ort.objects.order_by("kennung"))
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
    """Plätze und Räume ohne Position (F-67, Markierung ``ohne-position``).

    Dazu gehören Orte desselben Standorts, die noch keinem Plan zugeordnet sind.
    """
    from django.db.models import Q

    orte = Ort.objects.filter(
        Q(plan_id=plan.id, position_x__isnull=True)
        | Q(plan_id=plan.id, position_y__isnull=True)
        | Q(plan_id__isnull=True, standort=plan.standort),
        typ__in=(Ort.TYP_ARBEITSPLATZ, Ort.TYP_RAUM),
    ).order_by("kennung")
    return [{"ort": ort, "abgleich": soll_ist_abgleich(ort)} for ort in orte]


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


def _person_aus_ziel(person_ziel: str) -> Person | None:
    """Person zur Zuordnung aus Schritt 3; fehlt sie, entsteht sie ohne Konto (F-82, O-18).

    Der Nachname ist das letzte Wort, alles davor bleibt Vorname: „Anna Maria
    Schmidt“ wird nicht zu „Anna Schmidt“.
    """
    from . import import_parser
    person_ziel = (person_ziel or "").strip()
    if not person_ziel:
        return None
    person = import_parser._person_finden(person_ziel)
    if person is not None or "@" in person_ziel:
        return person
    teile = person_ziel.split()
    return Person.objects.create(
        vorname=" ".join(teile[:-1]) if len(teile) > 1 else teile[0],
        nachname=teile[-1] if len(teile) > 1 else "",
        # Die Bestandsliste nennt keine Anrede; raten wäre im Protokoll falsch.
        anrede="",
        aktiv=True,
    )


def _ort_aus_ziel(w) -> Ort | None:
    """Ort zur Zuordnung aus Schritt 3; ein fehlender Arbeitsplatz entsteht hier (F-82)."""
    if w.ort is not None:
        return w.ort
    if not w.ort_neu:
        return None
    ort, _ = Ort.objects.get_or_create(
        kennung=w.ort_neu, defaults={"typ": Ort.TYP_ARBEITSPLATZ},
    )
    return ort


def _import_vorgang(gerat: Gerat, herkunft: str, konto) -> None:
    """F-87: Vorgang „Import“ mit Dateiname, Blatt und Zeile, je Zeile einmal."""
    if Vorgang.objects.filter(gerat=gerat, typ=Vorgang.TYP_IMPORT, notiz=herkunft).exists():
        return
    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_IMPORT,
        zeitpunkt=jetzt_aware(),
        erzeugt_von=konto,
        notiz=herkunft,
        abschliesst=True,
    )


def _import_neu(w, kategorie, vz, herkunft: str, konto) -> Gerat:
    """Zeile „neu“: Gerät anlegen, Status und Verbleib ableiten (F-85)."""
    from . import import_parser

    person = _person_aus_ziel(w.person_ziel)
    ort = _ort_aus_ziel(w)
    arbeitsplatz = ort if ort is not None and ort.typ != Ort.TYP_LAGER else None
    in_benutzung = person is not None or arbeitsplatz is not None
    if not in_benutzung and ort is None:
        ort = import_parser._lagerort_finden()

    notiz = w.notiz
    if w.defekt:
        notiz = f"{notiz}; {import_parser.HINWEIS_DEFEKT}" if notiz else import_parser.HINWEIS_DEFEKT
    # F-84: die zweite Zeile mit derselben Nummer entsteht ohne sie, die Notiz nennt sie.
    seriennummer = w.seriennummer
    if "seriennummer-doppelt" in vz.hinweise and seriennummer:
        vermerk = f"Seriennummer {seriennummer} doppelt im Blatt"
        notiz = f"{notiz}; {vermerk}" if notiz else vermerk
        seriennummer = ""

    gerat = Gerat.objects.create(
        inventarnummer=naechste_inventarnummer(),
        kategorie=kategorie,
        hersteller=w.hersteller,
        modell=w.modell,
        seriennummer=seriennummer,
        geraetename=w.geraetename,
        status=Gerat.STATUS_IN_BENUTZUNG if in_benutzung else Gerat.STATUS_AUF_LAGER,
        zustand=Gerat.ZUSTAND_EINGESCHRAENKT if w.defekt else Gerat.ZUSTAND_GUT,
        person=person,
        ort=arbeitsplatz if in_benutzung else ort,
        kaufdatum=w.kaufdatum,
        kaufpreis_netto=w.kaufpreis,
        lieferant=w.lieferant,
        rechnungsnummer=w.rechnungsnummer,
        garantie_bis=w.garantie_bis,
        notiz=notiz,
        altbestand_ohne_protokoll=in_benutzung,
        zustand_ungeprueft=not w.defekt,
        erstellt_von=konto,
        erstellt_am=jetzt_aware(),
    )
    _import_vorgang(gerat, herkunft, konto)
    return gerat


def _import_ergaenzen(gerat: Gerat, w, herkunft: str, konto) -> None:
    """Zeile „ergänzt“ oder „Konflikt“: leere Felder füllen, Verbleib nach F-85."""
    from . import import_parser

    plan = import_parser.ergaenzungen(gerat, w)
    verbleib = import_parser.verbleib_plan(gerat, w)
    for feld, wert in plan.items():
        setattr(gerat, feld, wert)
    geaendert = list(plan)
    if verbleib["person"]:
        gerat.person = _person_aus_ziel(w.person_ziel)
        geaendert.append("person")
    if verbleib["ort"]:
        gerat.ort = _ort_aus_ziel(w)
        geaendert.append("ort")
    if verbleib["lager_raeumen"]:
        gerat.ort = None
        geaendert.append("ort")
    if verbleib["in_benutzung"]:
        gerat.status = Gerat.STATUS_IN_BENUTZUNG
        gerat.altbestand_ohne_protokoll = True
        geaendert += ["status", "altbestand_ohne_protokoll"]
    if geaendert:
        gerat.save(update_fields=sorted(set(geaendert)))
    _import_vorgang(gerat, herkunft, konto)


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
    kategorie_standard: str = "",
    neuer_person_name: str = "",
) -> dict:
    """Speichert die Vorschau-Zeilen (F-84 bis F-87).

    Je Zeile:
    - „neu“: Gerät anlegen mit allen Feldern aus der Zeile.
    - „ergaenzt“: vorhandenes Gerät (VorschauZeile.gerat), leere Felder füllen.
    - „konflikt“: ebenso, dazu je abweichendem Wert ein offener GeratKonflikt.
    - „uebersprungen“: nichts tun.

    Das Ergebnis jeder Zeile steht in der Vorschau; hier wird es nur ausgeführt,
    damit die Zahlen nach dem Speichern dieselben sind wie davor (F-86).
    F-85: Status und Verbleib ableiten. F-87: Vorgang „Import“ mit Dateiname,
    Blatt, Zeile. Neue Personen und Arbeitsplätze entstehen erst hier (F-82, O-18).

    Rückgabe: {„neu“: int, „ergaenzt“: int, „konflikt“: int, „uebersprungen“: int}
    """
    from . import import_parser

    zahl = {"neu": 0, "ergaenzt": 0, "konflikt": 0, "uebersprungen": 0}
    standard = import_parser._kategorie_finden(kategorie_standard) if kategorie_standard else None

    with transaction.atomic():
        lauf = Importlauf.objects.create(
            dateiname=dateiname, blatt=blatt, erzeugt_von=konto, erzeugt_am=jetzt_aware(),
        )
        if neuer_person_name:
            _person_aus_ziel(neuer_person_name)

        # A-0912: Geräte dieses Laufs, damit die Garantiezeile sie findet.
        neu_nach_sn: dict[str, Gerat] = {}

        for vz in vorschau:
            eintrag = _eintrag_fuer_zeile(vorlage, vz.zeile)
            if vz.ergebnis == "uebersprungen" or eintrag is None:
                zahl["uebersprungen"] += 1
                continue

            w = import_parser.zeile_lesen(
                vorlage, eintrag, spalten_ziel, wert_zu_kategorie,
                wert_zu_person, wert_zu_arbeitsplatz, standard,
            )
            herkunft = import_parser.herkunft_text(dateiname, blatt, vz.zeile)

            if vz.ergebnis == "neu":
                gerat = _import_neu(w, vz.kategorie, vz, herkunft, konto)
                if gerat.seriennummer:
                    neu_nach_sn[gerat.seriennummer.lower()] = gerat
                zahl["neu"] += 1
                continue

            gerat = vz.gerat or neu_nach_sn.get(w.seriennummer.lower())
            if gerat is None:
                zahl["uebersprungen"] += 1
                continue
            abweichend = import_parser.abweichungen(gerat, w) if vz.ergebnis == "konflikt" else []
            _import_ergaenzen(gerat, w, herkunft, konto)
            # F-84: Abweichende Werte überschreibt der Import nicht, er meldet sie,
            # und derselbe Konflikt steht nur einmal offen.
            for feld, alt, neu in abweichend:
                if not GeratKonflikt.objects.filter(
                    gerat=gerat, feld=feld, neuer_wert=neu, offen=True,
                ).exists():
                    GeratKonflikt.objects.create(
                        gerat=gerat, feld=feld, alter_wert=alt, neuer_wert=neu,
                        herkunft=herkunft, erzeugt_am=jetzt_aware(),
                    )
            zahl[vz.ergebnis] += 1

        # Zählungen im Importlauf festhalten
        lauf.anzahl_neu = zahl["neu"]
        lauf.anzahl_ergaenzt = zahl["ergaenzt"]
        lauf.anzahl_konflikt = zahl["konflikt"]
        lauf.anzahl_uebersprungen = zahl["uebersprungen"]
        lauf.save()

    return zahl


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
    jahr = jetzt_wie_im_entwicklungsmodus().year
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
    zustand: int | None = None,
    zubehoer_komplett: bool = True,
    anmerkung: str = "",
) -> Leihe | None:
    """Vorgang „Verleih" (F-30, Kapitel 3.2, Kapitel 8).

    Voraussetzungen (F-30, Kapitel 8):
    - Gerät ist „Auf Lager"
    - Gerät ist nicht reserviert (F-20)
    - Person ist gesetzt (Pflicht)
    - Rückgabedatum ist Pflicht
    - Zweck ist Pflicht

    Ergebnis auf dem Papierweg (F-22):
    - Gerät: Status „Verliehen"
    - Leihe: Status „ausgegeben"
    - Protokoll: Stand "scan-offen" (F-22, Kapitel 8.2)
    - Vorgang: Typ „ausgabe", leihgabe_an, zurueck_am

    A-0127: Unterschrift. Bei „tool" bleibt das Gerät „Auf Lager" und ist
    reserviert, die Leihe steht auf „genehmigt", das Protokoll auf
    „bearbeiter-offen"; Status und Vorgang kommen erst mit der Signatur
    (F-30: zum selben Zeitpunkt wie in F-21).
    """
    from .models import Leihe, Protokoll
    from django.db import transaction

    if gerat.status != Gerat.STATUS_AUF_LAGER:
        raise GeratFehler(f"Gerät ist nicht auf Lager (Status: {gerat.status}).")

    if not zweck or not zweck.strip():
        raise GeratFehler("Zweck ist Pflicht.")

    heute = jetzt_wie_im_entwicklungsmodus().date()
    if rueckgabe_bis is None or rueckgabe_bis <= heute:
        raise GeratFehler("Das Rückgabedatum muss nach heute liegen.")

    if _gerat_ist_reserviert(gerat, heute, rueckgabe_bis):
        raise GeratFehler("Gerät ist in diesem Zeitraum reserviert und kann nicht verliehen werden.")

    # A-0128: Zweiter Verleih abgelehnt, solange ein Protokoll
    # auf "bearbeiter-offen" steht (F-30, F-33).
    if _ausgabe_entwurf(gerat) is not None:
        raise GeratFehler(
            "Für dieses Gerät steht bereits ein offenes Protokoll. "
            "Ein weiterer Verleih ist solange nicht möglich."
        )

    im_tool = unterschrift == "tool"
    with transaction.atomic():
        # A-0128: Leihe zuerst anlegen, dann Protokoll mit Bezug.
        leihe = Leihe.objects.create(
            nr=_naechste_leihnummer(),
            gerat=gerat,
            person=person,
            kat=gerat.kategorie,
            beginn=heute,
            ende=rueckgabe_bis,
            rueckgabe_bis=rueckgabe_bis,
            zweck=zweck.strip(),
            status=Leihe.STATUS_GENEHMIGT if im_tool else Leihe.STATUS_AUSGEGEBEN,
            genehmigt=im_tool,
            zeitpunkt=jetzt_wie_im_entwicklungsmodus(),
            erzeugt_von=ausgefuehrt_von,
        )
        protokoll = _protokoll_erstellen(
            person=person,
            gerat=gerat,
            art=Protokoll.ART_AUSGABE,
            bearbeiter=(
                ausgefuehrt_von.bezeichnung() if ausgefuehrt_von is not None else ""
            ),
            erzeugt_von=ausgefuehrt_von,
            stand=(
                Protokoll.STAND_BEARBEITER_OFFEN if im_tool
                else Protokoll.STAND_SCAN_OFFEN
            ),
            unterschrift_art="tool" if im_tool else "papier",
            leihe=leihe,
            positionen=[position_aus_gerat(
                gerat,
                zustand_ausgabe=int(zustand) if zustand else None,
                zubehoer_komplett=zubehoer_komplett,
                bemerkung=(anmerkung or "").strip(),
            )],
        )
        if im_tool:
            _reservierung_nachziehen(gerat)
        else:
            _leihe_ausgabe_buchen(leihe, ausgefuehrt_von, protokoll)

    return leihe


def _leihe_ausgabe_buchen(leihe: Leihe, ausgefuehrt_von: Konto | None, protokoll: Protokoll | None = None) -> None:
    """Der eine Zeitpunkt der Ausgabe (F-30, F-33, Zeitpunkt wie in F-21).

    Gerät „Verliehen" bei der Person, Leihe „ausgegeben", Vorgang „Ausgabe",
    die Reservierung durch diese Leihe endet. Läuft in der Transaktion des
    Aufrufers: beim Papierweg mit dem Speichern, sonst mit der Signatur.
    """
    gerat = leihe.gerat
    position = (protokoll.positionen or [{}])[0] if protokoll is not None else {}
    gerat.status = Gerat.STATUS_VERLIEHEN
    gerat.person = leihe.person
    gerat.ort = None
    gerat.altbestand_ohne_protokoll = False
    if position.get("zustand_ausgabe"):
        gerat.zustand = int(position["zustand_ausgabe"])
    gerat.save(update_fields=["status", "person", "ort", "altbestand_ohne_protokoll", "zustand"])

    leihe.status = Leihe.STATUS_AUSGEGEBEN
    leihe.save(update_fields=["status"])

    teile = [leihe.zweck or "Leihgerät ausgegeben."]
    if protokoll is not None:
        teile.append(_ausgabe_notiz(protokoll.nr, position))

    Vorgang.objects.create(
        gerat=gerat,
        typ=Vorgang.TYP_AUSGABE,
        zeitpunkt=jetzt_wie_im_entwicklungsmodus(),
        erzeugt_von=ausgefuehrt_von,
        leihgabe_an=leihe.person,
        zurueck_am=leihe.rueckgabe_bis,
        notiz=", ".join(teile),
        protokoll=protokoll,
        abschliesst=False,
    )
    _reservierung_nachziehen(gerat)


def _belegende_leihen(
    gerat: Gerat, von: date, bis: date, ohne: Leihe | None = None
) -> list[Leihe]:
    """Leihen desselben Geräts, die den Zeitraum belegen (F-34, F-35).

    Genehmigte und ausgegebene Leihen zählen, die Ausgabe beendet den Schutz
    nicht. Eine überfällige Leihe belegt das Gerät bis heute, es ist ja noch
    draußen. Beide Grenztage gehören zum Zeitraum.
    """
    heute = jetzt_wie_im_entwicklungsmodus().date()
    leihen = Leihe.objects.filter(
        gerat=gerat, status__in=[Leihe.STATUS_GENEHMIGT, Leihe.STATUS_AUSGEGEBEN]
    ).select_related("person").order_by("beginn", "id")
    if ohne is not None:
        leihen = leihen.exclude(pk=ohne.pk)
    treffer = []
    for leihe in leihen:
        ende = heute if leihe.ist_ueberfaellig else (leihe.rueckgabe_bis or leihe.ende)
        if leihe.beginn is not None and leihe.beginn > bis:
            continue
        if ende is not None and ende < von:
            continue
        treffer.append(leihe)
    return treffer


def _gerat_ist_reserviert(
    gerat: Gerat,
    beginn: date | None = None,
    ende: date | None = None,
    ohne: Leihe | None = None,
) -> bool:
    """Ist das Gerät reserviert? (F-20, Kapitel 4, F-34)

    Ohne Zeitraum: es gibt eine genehmigte Leihe, die noch nicht vorbei ist. Mit
    Zeitraum: Überschneidung mit einer genehmigten oder ausgegebenen Leihe
    desselben Geräts – ein Gerät gehört in einem Zeitraum nur zu einer
    Leihe (F-34, O-12).
    """
    if beginn is not None and ende is not None:
        return bool(_belegende_leihen(gerat, beginn, ende, ohne=ohne))
    heute = jetzt_wie_im_entwicklungsmodus().date()
    return Leihe.objects.filter(
        Q(ende__isnull=True) | Q(ende__gte=heute),
        gerat=gerat, genehmigt=True, status=Leihe.STATUS_GENEHMIGT,
    ).exists()


def _leihgeraet_einsetzbar(gerat: Gerat) -> bool:
    """Kommt das Gerät für eine Leihe in Frage? (F-31, F-32, Kapitel 4)

    Nicht ausgemustert, nicht in Reparatur und nicht fest ausgegeben. Ein
    verliehenes Gerät zählt, wenn seine Leihe ein Ende hat; ob der Zeitraum
    passt, entscheidet dann die Überschneidung (F-34).
    """
    if gerat.status == Gerat.STATUS_AUF_LAGER:
        return True
    if gerat.status == Gerat.STATUS_VERLIEHEN:
        return Leihe.objects.filter(
            gerat=gerat, status=Leihe.STATUS_AUSGEGEBEN
        ).exists()
    return False


def leihgeraet_bezeichnung(gerat: Gerat) -> str:
    """Eintrag in Auswahllisten: Nummer, Hersteller, Modell (F-31)."""
    return f"{gerat.inventarnummer}, {gerat.hersteller} {gerat.modell}".strip()


def leihe_verfuegbarkeit(
    kategorie: Kategorie,
    von: date | None = None,
    bis: date | None = None,
    ohne: Leihe | None = None,
) -> dict:
    """F-31: Wie viele Leihpool-Geräte der Kategorie sind im Zeitraum frei?

    ``einsetzbar`` sind die Geräte, die für eine Leihe in Frage kommen; davon
    sind im Zeitraum ``frei`` und ``belegt``. ``gesamt`` zählt den Leihpool der
    Kategorie ohne ausgemusterte Geräte, wie im Prototyp. Ohne Zeitraum gibt
    es keinen Text.
    """
    pool = list(
        Gerat.objects.filter(kategorie=kategorie, leihpool=True)
        .exclude(status=Gerat.STATUS_AUSGEMUSTERT)
        .order_by("inventarnummer")
    )
    einsetzbar = [g for g in pool if _leihgeraet_einsetzbar(g)]
    ergebnis = {
        "einsetzbar": einsetzbar,
        "frei": [],
        "belegt": [],
        "gesamt": len(pool),
        "text": "",
        "art": "info",
    }
    if von is None or bis is None:
        return ergebnis
    frei = [g for g in einsetzbar if not _belegende_leihen(g, von, bis, ohne=ohne)]
    belegt = [g for g in einsetzbar if g not in frei]
    if frei:
        verb = "ist" if len(frei) == 1 else "sind"
        wort = "Leihgerät" if len(pool) == 1 else "Leihgeräten"
        text = f"Im Zeitraum {verb} {len(frei)} von {len(pool)} {wort} der Kategorie {kategorie.name} frei."
        art = "info"
    else:
        text = (
            f"Im Zeitraum ist kein Leihgerät der Kategorie {kategorie.name} frei. "
            "Sie können trotzdem anfragen, die IT meldet sich."
        )
        art = "warning"
    ergebnis.update(frei=frei, belegt=belegt, text=text, art=art)
    return ergebnis


def _leihen_beenden(gerat: Gerat, verloren: bool = False) -> None:
    """Ausgegebene Leihen abschließen, wenn das Gerät zurück oder verloren ist.

    Rückgabe und Verlust laufen über das Gerät (F-50, F-52, F-57). Die Leihe
    endet mit ihnen, sonst liefen Erinnerungen und „überfällig“ weiter (F-92).
    Bei Verlust steht sie auf „verloren“, nicht auf „zurückgegeben“.
    """
    Leihe.objects.filter(gerat=gerat, status=Leihe.STATUS_AUSGEGEBEN).update(
        status=Leihe.STATUS_VERLOREN if verloren else Leihe.STATUS_ZURUECKGEGEBEN,
        genehmigt=False,
        verlaengerung_bis=None,
    )


def leihe_zurueckgeben(
    leihe: Leihe,
    ausgefuehrt_von: Konto,
) -> None:
    """Rückgabe eines verliehenen Geräts (F-133, Kapitel 8).

    Läuft über dieselbe Funktion wie die Rückgabe am Gerät (F-50): Gerät ins
    Lager, Rücknahmeprotokoll, Vorgang, Leihe „zurueckgegeben".
    """
    if leihe.status != Leihe.STATUS_AUSGEGEBEN:
        raise GeratFehler("Leihe ist nicht ausgegeben.")
    gerat_rueckgeben(
        leihe.gerat,
        zustand_rueckgabe=leihe.gerat.zustand,
        ausgefuehrt_von=ausgefuehrt_von,
    )
    leihe.refresh_from_db()


def leihe_entwurf_verworfen(leihe: Leihe) -> None:
    """Das offene Protokoll einer Leihe wurde verworfen (F-21, A-0128).

    Ein verworfener Entwurf ändert nichts: Der Direktverleih verschwindet
    wieder, eine genehmigte Anfrage bleibt genehmigt und reserviert.
    """
    gerat = leihe.gerat
    if leihe.status == Leihe.STATUS_GENEHMIGT and leihe.decided_at is None:
        leihe.delete()
    if gerat is not None:
        _reservierung_nachziehen(gerat)


# --- F-93, F-32: Mails bei Leihanfrage und Entscheidung (M7 Teil 2) -----------

def leihe_mail_empfaenger(person: Person | None) -> str:
    """F-96: Adresse für Mails zur Leihe, leer bei deaktiviertem Konto.

    Eine Person ohne Konto bekommt die Mail weiter an ihre Adresse.
    """
    if person is None:
        return ""
    konten = list(person.konten.all())
    if konten and not any(konto.aktiv for konto in konten):
        return ""
    return person.email or ""


def bekommt_mail(person: Person | None, schalter: bool) -> bool:
    """F-96: Geht eine Mail zur Leihe an diese Person hinaus?"""
    return bool(schalter and leihe_mail_empfaenger(person))


def _mail_anfrage_an_it(leihe: Leihe) -> None:
    """F-93: Neue Leihanfrage → sofort Mail an die IT.

    Abschaltbar über Einstellungen (F-96).
    """
    from django.core.mail import send_mail
    from konten.mail import aktive_empfaenger, link_ins_tool, mail_absender, mail_signatur

    einstellungen = Einstellungen.aktuelles()
    if not (einstellungen.mail_leihe_neu and einstellungen.mail_verleih_anfrage):
        return
    it_empfaenger = aktive_empfaenger([einstellungen.email_it])
    if not it_empfaenger:
        return
    kat_name = leihe.kat.name if leihe.kat else ""
    gerat_name = leihe.gerat.inventarnummer if leihe.gerat else "keines (Kategorie)"
    beginn = leihe.beginn.strftime("%d.%m.%Y") if leihe.beginn else ""
    ende = leihe.ende.strftime("%d.%m.%Y") if leihe.ende else ""
    send_mail(
        subject=f"Neue Leihanfrage – {leihe.person.vorname} {leihe.person.nachname}",
        message=(
            f"Neue Leihanfrage eingegangen.\n\n"
            f"Person: {leihe.person.vorname} {leihe.person.nachname}\n"
            f"Kategorie: {kat_name}\n"
            f"Gerät: {gerat_name}\n"
            f"Zeitraum: {beginn} bis {ende}\n"
            f"Zweck: {leihe.zweck}\n\n"
            f"Entscheidung: {link_ins_tool('/verleih/')}\n\n"
            f"{mail_signatur()}"
        ),
        from_email=mail_absender(),
        recipient_list=it_empfaenger,
        fail_silently=True,
    )


def _mail_entscheidung_an_person(
    leihe: Leihe, genehmigt: bool, begruendung: str = "", reservierung: bool = False,
) -> None:
    """F-32: Entscheidung über Leihanfrage → sofort Mail an die Person.

    Abschaltbar über Einstellungen (F-96).
    """
    from django.core.mail import send_mail
    from konten.mail import aktive_empfaenger, link_ins_tool, mail_absender, mail_signatur

    einstellungen = Einstellungen.aktuelles()
    if genehmigt:
        if not einstellungen.mail_verleih_genehmigung:
            return
    else:
        if not einstellungen.mail_verleih_ablehnung:
            return
    # F-96: keine Mail an deaktivierte Konten.
    empfaenger = aktive_empfaenger([leihe.person.email])
    if not empfaenger:
        return
    # F-96: Der Link muss für den Mitarbeiter erreichbar sein; /verleih/ ist nur Admin.
    link = link_ins_tool("/meine-geraete/")
    if genehmigt:
        gerat_name = leihe.gerat.inventarnummer if leihe.gerat else ""
        beginn = leihe.beginn.strftime("%d.%m.%Y") if leihe.beginn else ""
        ende = leihe.ende.strftime("%d.%m.%Y") if leihe.ende else ""
        betrag = (
            f"Ihre Leihanfrage {leihe.nr} wurde genehmigt.\n\n"
            f"Gerät: {gerat_name}\n"
            f"Zeitraum: {beginn} bis {ende}\n\n"
            f"Details: {link}\n\n"
            f"{mail_signatur()}"
        )
        subject = f"Leihanfrage genehmigt – {gerat_name}"
    else:
        was = f"Ihre Reservierung {leihe.nr} wurde aufgehoben." if reservierung \
            else f"Ihre Leihanfrage {leihe.nr} wurde abgelehnt."
        betrag = (
            f"{was}\n\n"
            f"Begründung: {begruendung}\n\n"
            f"Details: {link}\n\n"
            f"{mail_signatur()}"
        )
        subject = "Reservierung aufgehoben" if reservierung else "Leihanfrage abgelehnt"
    send_mail(
        subject=subject,
        message=betrag,
        from_email=mail_absender(),
        recipient_list=empfaenger,
        fail_silently=True,
    )


def _mail_verlaengerung_an_it(leihe: Leihe) -> None:
    """F-35: Verlängerung angefragt → Mail an die IT, wie die Anfrage selbst (F-93)."""
    from django.core.mail import send_mail
    from django.conf import settings as _settings

    einstellungen = Einstellungen.aktuelles()
    if not (einstellungen.mail_leihe_neu and einstellungen.mail_verleih_anfrage):
        return
    if not einstellungen.email_it:
        return
    basis = _settings.BASIS_URL.rstrip("/") if _settings.BASIS_URL else "http://127.0.0.1:8000"
    send_mail(
        subject=f"Verlängerung angefragt – {leihe.gerat.inventarnummer}",
        message=(
            f"{leihe.person.vorname} {leihe.person.nachname} fragt eine Verlängerung an.\n\n"
            f"Leihe: {leihe.nr}\n"
            f"Gerät: {leihe.gerat.inventarnummer}\n"
            f"Rückgabe bis: {leihe.rueckgabe_bis.strftime('%d.%m.%Y')}\n"
            f"Gewünscht bis: {leihe.verlaengerung_bis.strftime('%d.%m.%Y')}\n\n"
            f"Entscheidung: {basis}/verleih/\n\n"
            f"{einstellungen.absenderzeile or 'Wamocon GmbH · IT'}"
        ),
        from_email=_settings.DEFAULT_FROM_EMAIL or "inventar@beispiel.test",
        recipient_list=[einstellungen.email_it],
        fail_silently=True,
    )


def _mail_verlaengerung_an_person(leihe: Leihe) -> None:
    """F-35: Verlängerung gewährt → Mail an die Person (F-93, F-96)."""
    from django.core.mail import send_mail
    from django.conf import settings as _settings

    einstellungen = Einstellungen.aktuelles()
    if not einstellungen.mail_verleih_genehmigung:
        return
    empfaenger = leihe_mail_empfaenger(leihe.person)
    if not empfaenger:
        return
    basis = _settings.BASIS_URL.rstrip("/") if _settings.BASIS_URL else "http://127.0.0.1:8000"
    send_mail(
        subject=f"Leihe verlängert – {leihe.gerat.inventarnummer}",
        message=(
            f"Ihre Leihe {leihe.nr} wurde verlängert.\n\n"
            f"Gerät: {leihe.gerat.inventarnummer}\n"
            f"Neues Rückgabedatum: {leihe.rueckgabe_bis.strftime('%d.%m.%Y')}\n\n"
            f"Details: {basis}/meine-geraete/\n\n"
            f"{einstellungen.absenderzeile or 'Wamocon GmbH · IT'}"
        ),
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
        raise GeratFehler("Zweck ist Pflicht.")
    if beginn > ende:
        raise GeratFehler("Das Enddatum muss am oder nach dem Startdatum liegen.")
    if beginn < jetzt_wie_im_entwicklungsmodus().date():
        raise GeratFehler("Das Startdatum darf nicht in der Vergangenheit liegen.")
    if gerat is not None:
        if gerat.kategorie_id != kat.id:
            raise GeratFehler("Das gewählte Gerät steht nicht in dieser Kategorie.")
        if not gerat.leihpool:
            raise GeratFehler("Das gewählte Gerät steht nicht im Leihpool.")
        if not _leihgeraet_einsetzbar(gerat):
            raise GeratFehler("Das gewählte Gerät ist nicht verfügbar.")
        if _gerat_ist_reserviert(gerat, beginn, ende):
            raise GeratFehler(
                "Das Gerät ist in diesem Zeitraum bereits für eine "
                "Leihe reserviert."
            )
    with transaction.atomic():
        # Der Wunsch reserviert noch nichts, das tut erst die Genehmigung (Kapitel 4).
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
            zeitpunkt=jetzt_wie_im_entwicklungsmodus(),
            erzeugt_von=erzeugt_von,
        )
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
    if not _leihgeraet_einsetzbar(gerat):
        raise GeratFehler(
            f"Das Gerät steht auf „{gerat.status_anzeige}“ und kann nicht "
            "zugewiesen werden."
        )
    if _gerat_ist_reserviert(gerat, leihe.beginn, leihe.ende, ohne=leihe):
        raise GeratFehler(
            "Das Gerät ist in diesem Zeitraum bereits für eine "
            "Leihe reserviert."
        )
    _ohne_ausgabe_entwurf(gerat)
    with transaction.atomic():
        leihe.gerat = gerat
        leihe.genehmigt = True
        leihe.status = Leihe.STATUS_GENEHMIGT
        leihe.decided_at = jetzt_wie_im_entwicklungsmodus()
        leihe.save(
            update_fields=["gerat", "genehmigt", "status", "decided_at"]
        )
        _reservierung_nachziehen(gerat)
        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_AENDERUNG,
            zeitpunkt=jetzt_wie_im_entwicklungsmodus(),
            erzeugt_von=ausgefuehrt_von,
            notiz="Leihe genehmigt und Gerät reserviert.",
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

    if leihe.status not in (Leihe.STATUS_ANGEFRAGT, Leihe.STATUS_GENEHMIGT):
        raise GeratFehler("Diese Leihe ist weder angefragt noch genehmigt.")
    if not begruendung or not begruendung.strip():
        raise GeratFehler("Begründung ist Pflicht.")
    reservierung = leihe.status == Leihe.STATUS_GENEHMIGT
    with transaction.atomic():
        leihe.protokolle.filter(stand=Protokoll.STAND_BEARBEITER_OFFEN).delete()
        leihe.abgelehnt = True
        leihe.abgelehnt_bis = begruendung.strip()
        leihe.abgelehnt_von = ausgefuehrt_von
        leihe.genehmigt = False
        leihe.status = Leihe.STATUS_ABGELEHNT
        leihe.decided_at = jetzt_wie_im_entwicklungsmodus()
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
                zeitpunkt=jetzt_wie_im_entwicklungsmodus(),
                erzeugt_von=ausgefuehrt_von,
                notiz="Reservierung aufgehoben." if reservierung else "Leihe abgelehnt.",
                abschliesst=False,
            )
            _reservierung_nachziehen(leihe.gerat)
        # F-32: Mail an die Person
        _mail_entscheidung_an_person(
            leihe, genehmigt=False, begruendung=begruendung.strip(), reservierung=reservierung,
        )
        return leihe


def leihe_zurueckziehen(
    leihe: Leihe,
    ausgefuehrt_von: Konto,
) -> Leihe:
    """M5 Teil 2 (F-37): Mitarbeiter zieht die Leihe zurück.

    Solange die Leihe nicht ausgegeben ist, endet damit auch ihre
    Reservierung und ein noch nicht signierter Protokollentwurf.
    """
    from .models import Vorgang

    if not leihe.ist_zurueckziehbar():
        raise GeratFehler("Diese Leihe lässt sich nicht mehr zurückziehen.")
    with transaction.atomic():
        leihe.status = Leihe.STATUS_ZURUECKGEZOGEN
        leihe.genehmigt = False
        leihe.decided_at = jetzt_wie_im_entwicklungsmodus()
        leihe.save(update_fields=["status", "genehmigt", "decided_at"])
        leihe.protokolle.filter(stand=Protokoll.STAND_BEARBEITER_OFFEN).delete()
        if leihe.gerat_id is not None:
            gerat = leihe.gerat
            _reservierung_nachziehen(gerat)
            Vorgang.objects.create(
                gerat=gerat,
                typ=Vorgang.TYP_AENDERUNG,
                zeitpunkt=jetzt_wie_im_entwicklungsmodus(),
                erzeugt_von=ausgefuehrt_von,
                notiz="Leihe zurückgezogen, Reservierung aufgehoben.",
                abschliesst=False,
            )
        return leihe


def _reservierung_nachziehen(gerat: Gerat) -> None:
    """Reservierung nach den genehmigten Leihen des Geräts setzen (F-20, Kapitel 4).

    reserviert_bis ist das Maximum aller genehmigten Leihen (O-12). Endet eine
    Leihe, bleibt die Reservierung für die anderen bestehen.
    """
    ende = Leihe.objects.filter(
        gerat=gerat, genehmigt=True, status=Leihe.STATUS_GENEHMIGT
    ).aggregate(Max("ende"))["ende__max"]
    gerat.reserviert = Leihe.objects.filter(
        gerat=gerat, genehmigt=True, status=Leihe.STATUS_GENEHMIGT
    ).exists()
    gerat.reserviert_von = None
    gerat.reserviert_bis = ende
    gerat.save(update_fields=["reserviert", "reserviert_von", "reserviert_bis"])


def leihe_ausgeben(
    leihe: Leihe,
    ausgefuehrt_von: Konto,
    unterschrift: str = "papier",
    zustand: int | None = None,
    zubehoer_komplett: bool = True,
    anmerkung: str = "",
) -> Leihe:
    """M5 Teil 4 (F-33, F-21, F-22): IT gibt eine genehmigte Leihe aus.

    Voraussetzungen (F-33):
    - Leihe ist genehmigt
    - Gerät ist auf Lager und im Leihpool
    - Keine andere genehmigte Leihe überschneidet sich (F-34)
    - Kein offenes Protokoll für das Gerät

    Ergebnis auf dem Papierweg (F-22):
    - Gerät: Status "Verliehen", Person gesetzt
    - Leihe: Status "ausgegeben"
    - Protokoll: Stand "scan-offen" (F-21, F-22)
    - Vorgang: Typ "ausgabe", leihgabe_an, zurueck_am
    - Die Reservierung durch diese Leihe endet

    Bei „tool" entsteht nur das Protokoll auf „bearbeiter-offen". Gerät und
    Leihe bleiben, wie sie sind; alles andere kommt mit der Signatur (F-33:
    Zeitpunkt wie in F-21). Ein verworfener Entwurf ändert nichts.
    """
    from django.db import transaction

    if leihe.status != Leihe.STATUS_GENEHMIGT:
        raise GeratFehler("Diese Leihe ist nicht genehmigt.")

    if leihe.gerat_id is None:
        raise GeratFehler("Die Leihe hat kein Gerät zugewiesen.")

    gerat = leihe.gerat
    if gerat.status != Gerat.STATUS_AUF_LAGER:
        raise GeratFehler(f"Gerät ist nicht auf Lager (Status: {gerat.status}).")

    if not gerat.leihpool:
        raise GeratFehler("Gerät steht nicht im Leihpool.")

    rueckgabe_bis = leihe.rueckgabe_bis
    if rueckgabe_bis is None:
        raise GeratFehler("Rückgabedatum fehlt.")

    if rueckgabe_bis < jetzt_wie_im_entwicklungsmodus().date():
        raise GeratFehler(
            "Das Rückgabedatum liegt in der Vergangenheit; die Leihe wäre "
            "sofort überfällig."
        )

    # Eine andere Leihe im Zeitraum (F-20, F-34); spätere Reservierungen stören nicht.
    if _gerat_ist_reserviert(gerat, leihe.beginn or rueckgabe_bis, rueckgabe_bis, ohne=leihe):
        raise GeratFehler("Gerät ist für eine andere Leihe reserviert und kann nicht ausgegeben werden.")

    if _ausgabe_entwurf(gerat) is not None:
        raise GeratFehler(
            "Für dieses Gerät steht bereits ein offenes Protokoll. "
            "Die Ausgabe ist solange nicht möglich."
        )

    person = leihe.person
    if person is None:
        raise GeratFehler("Die Leihe hat keine Person.")

    im_tool = unterschrift == "tool"
    with transaction.atomic():
        # A-0123 (M6 Teil 1): F-21, F-22, F-130 — Protokoll in der
        # Service-Schicht bei Verleih, mit Bezug auf die Leihe.
        protokoll = _protokoll_erstellen(
            person=person,
            gerat=gerat,
            art=Protokoll.ART_AUSGABE,
            bearbeiter=(
                ausgefuehrt_von.bezeichnung() if ausgefuehrt_von is not None else ""
            ),
            erzeugt_von=ausgefuehrt_von,
            stand=(
                Protokoll.STAND_BEARBEITER_OFFEN if im_tool
                else Protokoll.STAND_SCAN_OFFEN
            ),
            unterschrift_art="tool" if im_tool else "papier",
            leihe=leihe,
            positionen=[position_aus_gerat(
                gerat,
                zustand_ausgabe=int(zustand) if zustand else None,
                zubehoer_komplett=zubehoer_komplett,
                bemerkung=(anmerkung or "").strip(),
            )],
        )
        if not im_tool:
            _leihe_ausgabe_buchen(leihe, ausgefuehrt_von, protokoll)

    return leihe


def leihe_verlaengerung_anfragen(
    leihe: Leihe,
    rueckgabe_bis_neu: date,
) -> Leihe:
    """F-35, F-111: Der Mitarbeiter fragt eine Verlängerung an, die IT gewährt.

    Das Rückgabedatum bleibt, bis die IT entschieden hat. Die Mail an die IT
    geht sofort, wie bei der Anfrage selbst (F-93).
    """
    if leihe.status != Leihe.STATUS_AUSGEGEBEN:
        raise GeratFehler("Eine Verlängerung gibt es nur für ausgegebene Leihen.")
    if leihe.verlaengerung_bis is not None:
        raise GeratFehler("Für diese Leihe ist schon eine Verlängerung angefragt.")
    if rueckgabe_bis_neu <= leihe.rueckgabe_bis:
        raise GeratFehler("Neues Rückgabedatum muss nach dem alten liegen.")
    if rueckgabe_bis_neu <= jetzt_wie_im_entwicklungsmodus().date():
        raise GeratFehler("Das Datum muss nach heute liegen.")
    leihe.verlaengerung_bis = rueckgabe_bis_neu
    leihe.save(update_fields=["verlaengerung_bis"])
    _mail_verlaengerung_an_it(leihe)
    return leihe


def leihe_verlaengern(
    leihe: Leihe,
    rueckgabe_bis_neu: date,
    ausgefuehrt_von: Konto,
) -> Leihe:
    """M5 Teil 4 (F-35): IT gewährt eine Verlängerung.

    Voraussetzungen (F-35):
    - Leihe ist ausgegeben
    - Das neue Rückgabedatum liegt nach dem alten und nach heute

    Ablehnung:
    - Eine andere Leihe des Geräts fällt in die Zeit bis zum neuen
      Rückgabedatum (Folgereservierung, F-35, F-34)

    Ergebnis bei Erfolg:
    - Leihe: rueckgabe_bis wird verschoben, eine Anfrage ist erledigt
    - Vorgang "Änderung" wird angelegt
    - Mail an die Person
    """
    from .models import Vorgang
    from django.db import transaction

    if leihe.status != Leihe.STATUS_AUSGEGEBEN:
        raise GeratFehler("Diese Leihe ist nicht ausgegeben.")

    gerat = leihe.gerat
    if gerat is None:
        raise GeratFehler("Die Leihe hat kein Gerät zugewiesen.")

    altes_rueckgabe_bis = leihe.rueckgabe_bis
    if rueckgabe_bis_neu <= altes_rueckgabe_bis:
        raise GeratFehler("Neues Rückgabedatum muss nach dem alten liegen.")

    if rueckgabe_bis_neu <= jetzt_wie_im_entwicklungsmodus().date():
        raise GeratFehler("Das Datum muss nach heute liegen.")

    # Die ganze hinzukommende Zeit muss frei sein, nicht nur der Zieltag (F-35).
    folge = _belegende_leihen(
        gerat, altes_rueckgabe_bis + timedelta(days=1), rueckgabe_bis_neu, ohne=leihe
    )
    if folge:
        beginn = folge[0].beginn.strftime("%d.%m.%Y") if folge[0].beginn else "sofort"
        raise GeratFehler(
            f"Verlängerung abgelehnt: Ab {beginn} ist das Gerät für "
            f"{folge[0].person.voller_name()} reserviert."
        )

    with transaction.atomic():
        leihe.rueckgabe_bis = rueckgabe_bis_neu
        if leihe.ende is None or rueckgabe_bis_neu > leihe.ende:
            leihe.ende = rueckgabe_bis_neu
        leihe.verlaengerung_bis = None
        leihe.save(update_fields=["rueckgabe_bis", "ende", "verlaengerung_bis"])

        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_AENDERUNG,
            zeitpunkt=jetzt_wie_im_entwicklungsmodus(),
            erzeugt_von=ausgefuehrt_von,
            aenderung_feld="rueckgabe_bis",
            aenderung_alter_wert=altes_rueckgabe_bis.strftime("%d.%m.%Y"),
            aenderung_neuer_wert=rueckgabe_bis_neu.strftime("%d.%m.%Y"),
            notiz="Verlängerung der Leihe.",
            abschliesst=False,
        )
        _mail_verlaengerung_an_person(leihe)

    return leihe


def leihe_verlaengerung_ablehnen(leihe: Leihe, ausgefuehrt_von: Konto) -> Leihe:
    """F-35: Die IT lehnt eine angefragte Verlängerung ab. Die Leihe läuft zur alten Frist weiter."""
    from django.core.mail import send_mail

    if leihe.status != Leihe.STATUS_AUSGEGEBEN or leihe.verlaengerung_bis is None:
        raise GeratFehler("Für diese Leihe ist keine Verlängerung angefragt.")
    leihe.verlaengerung_bis = None
    leihe.save(update_fields=["verlaengerung_bis"])
    Vorgang.objects.create(
        gerat=leihe.gerat, typ=Vorgang.TYP_AENDERUNG, zeitpunkt=jetzt_wie_im_entwicklungsmodus(),
        erzeugt_von=ausgefuehrt_von, notiz=f"Verlängerung der Leihe {leihe.nr} abgelehnt.", abschliesst=False,
    )
    empfaenger = leihe_mail_empfaenger(leihe.person)
    if empfaenger and Einstellungen.aktuelles().mail_verleih_ablehnung:
        frist = leihe.rueckgabe_bis.strftime("%d.%m.%Y") if leihe.rueckgabe_bis else ""
        send_mail(
            f"Verlängerung abgelehnt: Leihe {leihe.nr}",
            f"Ihre angefragte Verlängerung der Leihe {leihe.nr} wurde abgelehnt. "
            f"Die Rückgabe bleibt am {frist}.\n\nDetails: {link_ins_tool('/meine-geraete/')}\n\n{mail_signatur()}",
            mail_absender(),
            [empfaenger],
            fail_silently=True,
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
    """IP-Adresse für das Prüfprotokoll (F-137).

    Ein Kopf ``X-Forwarded-For`` zählt nur hinter dem eigenen Reverse Proxy
    (``INVENTAR_PROXY=1``), und dann nur der letzte Eintrag: den setzt der Proxy,
    alle davor kann der Absender selbst schreiben.
    """
    if os.environ.get("INVENTAR_PROXY") == "1":
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if xff:
            return xff.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "127.0.0.1")


def _nachweisnummer(jetzt) -> str:
    """Nachweisnummer je Signatur: SIG-JJJJ-NNNN (F-137)."""
    from .models import SignaturAufzeichnung
    jahr = jetzt.year
    laufend = SignaturAufzeichnung.objects.filter(nachweisnummer__startswith=f"SIG-{jahr}-").count() + 1
    return f"SIG-{jahr}-{laufend:04d}"


def _senden(betreff: str, inhalt: str, empfaenger: list) -> bool:
    """Mail senden. Scheitert der Versand, bleibt der Vorgang gültig und der Aufrufer meldet es."""
    from django.core.mail import send_mail
    from smtplib import SMTPException

    try:
        send_mail(betreff, inhalt, mail_absender(), empfaenger)
    except (SMTPException, OSError):
        return False
    return True


def _link_gegenzeichnung(token: str) -> str:
    """Voller Link, damit der Empfänger ihn öffnen kann (F-136)."""
    from django.conf import settings
    return f"{settings.BASIS_URL}/signieren/{token}/"


def _pdf_hash(pdf_bytes: bytes) -> str:
    """SHA-256-Hash des PDFs (F-137)."""
    import hashlib
    return hashlib.sha256(pdf_bytes).hexdigest()


@transaction.atomic
def protokoll_bearbeiter_signieren(
    protokoll: Protokoll,
    password: str,
    request=None,
    konto: Konto | None = None,
) -> tuple[Protokoll, bool]:
    """F-135: Der Bearbeiter signiert das Protokoll mit erneuter Passwortabfrage.

    Geprüft wird das Passwort des angemeldeten Kontos; ohne Anfrage das des
    Erstellers. Danach ist der Inhalt gesperrt, das Protokoll wartet auf die
    Gegenzeichnung und die Person bekommt den Link (F-136). Das Prüfprotokoll
    bekommt einen Eintrag (F-137). Das Passwort wird nirgends gespeichert.
    """
    from konten.zeit import jetzt_wie_im_entwicklungsmodus
    from .models import SignaturAufzeichnung

    now = jetzt_wie_im_entwicklungsmodus()
    ip = _client_ip(request) if request else "127.0.0.1"

    if konto is None and request is not None and getattr(request.user, "is_authenticated", False):
        konto = request.user
    if konto is None:
        konto = protokoll.erzeugt_von
    if konto is None:
        return protokoll, False
    if protokoll.stand != Protokoll.STAND_BEARBEITER_OFFEN:
        return protokoll, False
    # F-01: Die Sperre nach Fehlversuchen gilt auch hier.
    if konto.ist_gesperrt(jetzt=now):
        return protokoll, False
    if not konto.check_password(password):
        konto.registriere_fehlversuch(jetzt=now)
        return protokoll, False

    # F-21: Inzwischen anderswo gelandet? Dann überschreibt die Signatur nichts.
    if protokoll.art == Protokoll.ART_AUSGABE and protokoll.unterschrift_art == "tool" and not protokoll.ist_korrektur:
        for gerat in protokoll.geraete_liste():
            if gerat.status != Gerat.STATUS_AUF_LAGER:
                raise GeratFehler(
                    f"{gerat.inventarnummer} steht nicht mehr auf Lager ({gerat.status_anzeige}). "
                    "Bitte den Entwurf verwerfen."
                )

    # F-132: Signatur wird abgelehnt, solange die Checkliste noch offen ist.
    from . import pdf as pdf_modul
    if pdf_modul._offene_punkte(protokoll):
        return protokoll, False

    # F-135: Inhalt einfrieren; der Hash steht im Prüfprotokoll (F-137).
    protokoll.bearbeiter = konto.bezeichnung()
    html, pdf_hash = pdf_modul.inhalt_einfrieren(protokoll)
    protokoll.html_eingefroren = html
    protokoll.bearbeiter_signiert_am = now
    protokoll.bearbeiter_signiert_von = konto
    protokoll.bearbeiter_ip = ip
    protokoll.pdf_hash_bearbeiter = pdf_hash

    SignaturAufzeichnung.objects.create(
        protokoll=protokoll,
        art=SignaturAufzeichnung.KIND_BEARBEITER,
        name=konto.bezeichnung(),
        email=konto.email,
        zeitpunkt=now,
        nachweisnummer=_nachweisnummer(now),
        identifikationsmerkmal="Anmeldung und erneute Passwortabfrage",
        ip_adresse=ip,
        hashwert=pdf_hash,
    )

    # F-21: Status und Verbleib gelten ab der Signatur des Bearbeiters.
    # Eine Korrektur ändert am Gerät nichts mehr, das Original hat das schon getan.
    # Bei Verleih (F-30, F-33): Status Verliehen, Leihe „ausgegeben“, Vorgang.
    if protokoll.art == Protokoll.ART_AUSGABE and protokoll.unterschrift_art == "tool" and not protokoll.ist_korrektur:
        if protokoll.leihe is None:
            _ausgabe_wirksam_machen(protokoll, konto, now)
        elif protokoll.leihe.status == Leihe.STATUS_GENEHMIGT:
            _leihe_ausgabe_buchen(protokoll.leihe, konto, protokoll)

    # F-136: Token für die Gegenzeichnung (14 Tage gültig).
    import secrets
    token = secrets.token_hex(32)
    empfaenger = protokoll.gegenzeichnung_empfaenger or protokoll.person.email or ""
    protokoll.gegenzeichnung_token = token
    protokoll.gegenzeichnung_token_erstellt = now
    protokoll.gegenzeichnung_empfaenger = empfaenger
    protokoll.stand = Protokoll.STAND_GEGENZEICHNUNG_OFFEN
    protokoll.save()

    protokoll.mail_ging_nicht = not _mail_gegenzeichnen_link(
        protokoll, token, empfaenger, bearbeiter_name=konto.bezeichnung()
    )
    return protokoll, True


def _ausgabe_wirksam_machen(protokoll: Protokoll, konto: Konto, now) -> None:
    """F-21, F-30: Status, Person, Ort und Vorgang mit der Signatur des Bearbeiters."""
    werte = {p.get("inventarnummer"): p for p in protokoll.positionen or []}
    for gerat in protokoll.geraete_liste():
        p = werte.get(gerat.inventarnummer, {})
        if p.get("zustand_ausgabe"):
            gerat.zustand = int(p["zustand_ausgabe"])
        gerat.person = protokoll.person
        gerat.altbestand_ohne_protokoll = False
        gerat.status = Gerat.STATUS_IN_BENUTZUNG
        gerat.ort = protokoll.ort_ziel
        Vorgang.objects.create(
            gerat=gerat,
            typ=Vorgang.TYP_AUSGABE,
            zeitpunkt=now,
            erzeugt_von=konto,
            leihgabe_an=protokoll.person,
            notiz=_ausgabe_notiz(protokoll.nr, p),
            protokoll=protokoll,
            abschliesst=True,
        )
        gerat.save()


def _anrede_mail(person) -> str:
    anrede = str(getattr(person, "anrede", "") or "").lower()
    if anrede.startswith("f"):
        return f"Sehr geehrte Frau {person.nachname}"
    if anrede.startswith("h"):
        return f"Sehr geehrter Herr {person.nachname}"
    return f"Guten Tag {person.vorname} {person.nachname}".strip()


def _mail_gegenzeichnen_link(
    protokoll: Protokoll,
    token: str,
    empfaenger: str,
    bearbeiter_name: str = "",
    erzwingen: bool = False,
) -> bool:
    """Mail mit persönlichem Link (F-136), 14 Tage gültig. Liefert, ob der Versand klappte."""
    from django.core.mail import send_mail
    from konten.mail import link_ins_tool, mail_absender, mail_signatur

    if not empfaenger:
        return True
    # F-96: Mailart abschaltbar; „Link neu senden“ ist ein ausdrücklicher Auftrag und geht immer.
    if not erzwingen and not Einstellungen.aktuelles().mail_protokoll_gesendet:
        return False
    inhalt = (
        f"{_anrede_mail(protokoll.person)},\n\n"
        f"das Protokoll {protokoll.nr} steht zur Gegenzeichnung bereit.\n"
        "Öffnen Sie den folgenden Link, sehen Sie das PDF an und signieren Sie "
        "mit einem Einmalcode, den Sie dort per Mail anfordern:\n\n"
        f"Link: {_link_gegenzeichnung(token)}\n\n"
        "Der Link ist 14 Tage gültig.\n\n"
        f"Mit freundlichen Grüßen\n{bearbeiter_name or mail_signatur()}"
    )
    return _senden(f"Gegenzeichnung: Protokoll {protokoll.nr}", inhalt, [empfaenger])


def protokoll_code_senden(
    protokoll: Protokoll,
    empfaenger: str | None = None,
    request=None,
) -> tuple[bool, str]:
    """F-136: Einmalcode erzeugen und per Mail senden (N-05).

    6-stellig, 10 Minuten gültig, höchstens 5 Versuche. Die Adresse kann die IT
    im Dialog ändern (F-141, Rückgabe per Post); sie steht dann im Prüfprotokoll.
    """
    from konten.mail import mail_absender, mail_signatur
    from .models import SignaturCode
    import secrets
    from datetime import timedelta

    if protokoll.stand != Protokoll.STAND_GEGENZEICHNUNG_OFFEN:
        return False, "Dieses Protokoll wartet nicht auf eine Gegenzeichnung."
    now = jetzt_wie_im_entwicklungsmodus()
    empfaenger = (empfaenger or "").strip() or protokoll.gegenzeichnung_empfaenger or protokoll.person.email or ""
    if not empfaenger:
        return False, "Für diese Person ist keine E-Mail-Adresse hinterlegt. Bitte eine Adresse eintragen."

    # N-05: Höchstens 5 Codes je Stunde, sonst wären die 5 Versuche je Code wertlos.
    if SignaturCode.objects.filter(protokoll=protokoll, erstellt_am__gt=now - timedelta(hours=1)).count() >= 5:
        return False, "Zu viele Codes angefordert. Bitte versuchen Sie es in einer Stunde erneut."
    SignaturCode.objects.filter(protokoll=protokoll, gueltig=True).update(gueltig=False)
    code = f"{secrets.randbelow(10**6):06d}"
    SignaturCode.objects.create(
        protokoll=protokoll, code=code, erstellt_am=now, gueltig_bis=now + timedelta(minutes=10),
    )
    if empfaenger != protokoll.gegenzeichnung_empfaenger:
        protokoll.gegenzeichnung_empfaenger = empfaenger
        protokoll.save(update_fields=["gegenzeichnung_empfaenger"])
    inhalt = (
        f"{_anrede_mail(protokoll.person)},\n\n"
        f"Ihr Einmalcode für die Gegenzeichnung des Protokolls {protokoll.nr}:\n\n"
        f"Einmalcode: {code}\n\n"
        "Der Code ist 10 Minuten gültig, Sie haben höchstens 5 Versuche.\n\n"
        f"Zur Gegenzeichnung: {_link_gegenzeichnung(protokoll.gegenzeichnung_token)}\n\n"
        f"Mit freundlichen Grüßen\n{mail_signatur()}"
    )
    if not _senden(f"Einmalcode für Protokoll {protokoll.nr}", inhalt, [empfaenger]):
        return False, "Die Mail ließ sich nicht senden. Bitte wenden Sie sich an die IT."
    return True, "Code gesendet."


def _ablage_mit_anhang(
    protokoll: Protokoll,
    pdf_bytes: bytes,
    dateiname: str,
    typ: str = "application/pdf",
) -> bool:
    """F-139: Das fertige PDF geht an Person und Bearbeiter, je eine Ausfertigung.

    Abgelegt ist es im Protokoll selbst, und von dort kommt es am Gerät, an der Person
    und im Self-Service. Liefert, ob alles hinausging; sonst sendet die IT erneut.
    """
    gesendet = True
    person_email = protokoll.gegenzeichnung_empfaenger or protokoll.person.email or ""
    if person_email:
        gesendet &= _mail_anhang(protokoll, pdf_bytes, dateiname, person_email, "/meine-geraete/", typ)
    bearbeiter = protokoll.bearbeiter_signiert_von or protokoll.erzeugt_von
    bearbeiter_email = bearbeiter.email if bearbeiter is not None else ""
    if bearbeiter_email and bearbeiter_email != person_email:
        gesendet &= _mail_anhang(protokoll, pdf_bytes, dateiname, bearbeiter_email, f"/protokolle/{protokoll.nr}/", typ)
    return gesendet


def _mail_anhang(
    protokoll: Protokoll,
    pdf_bytes: bytes,
    dateiname: str,
    empfaenger: str,
    pfad: str = "/meine-geraete/",
    typ: str = "application/pdf",
) -> bool:
    """F-139: Mail mit dem fertigen Protokoll als Anhang an einen Empfänger."""
    from django.core.mail import EmailMessage
    from smtplib import SMTPException

    # F-96: Mailart abschaltbar.
    if not Einstellungen.aktuelles().mail_protokoll_unterzeichnet:
        return True
    msg = EmailMessage(
        subject=f"Protokoll {protokoll.nr}: abgeschlossen",
        body=(
            f"Das Protokoll {protokoll.nr} ist von beiden Seiten unterschrieben.\n\n"
            f"Anbei erhalten Sie das Protokoll ({dateiname}).\n\n"
            f"Im Tool: {link_ins_tool(pfad)}\n\n"
            f"{mail_signatur()}"
        ),
        from_email=mail_absender(),
        to=[empfaenger],
    )
    msg.attach(dateiname, pdf_bytes, typ)
    try:
        msg.send()
    except (SMTPException, OSError):
        return False
    return True


def protokoll_pdf_senden(protokoll: Protokoll) -> bool:
    """F-139: Das fertige Protokoll erneut senden, nachdem der Versand gescheitert ist."""
    from . import pdf as pdf_modul
    from .protokoll import _typ_am_inhalt

    if protokoll.stand != Protokoll.STAND_ABGESCHLOSSEN:
        raise GeratFehler("Das Protokoll ist noch nicht abgeschlossen.")
    if protokoll.scan_datei:
        with protokoll.scan_datei.open("rb") as handle:
            roh = handle.read()
        typ = _typ_am_inhalt(roh) or "application/pdf"
    else:
        roh, typ = bytes(protokoll.pdf_siegel), "application/pdf"
    gesendet = _ablage_mit_anhang(protokoll, roh, pdf_modul.dateiname_protokoll(protokoll, typ), typ)
    protokoll.pdf_versand_offen = not gesendet
    protokoll.save(update_fields=["pdf_versand_offen"])
    return gesendet


@transaction.atomic
def protokoll_link_neu_senden(
    protokoll: Protokoll,
    empfaenger: str | None = None,
) -> tuple[Protokoll, bool, str]:
    """F-140, F-141: Neuer Link, neue Frist; der alte Link gilt nicht mehr.

    Den Einmalcode fordert die Person auf der Seite an, er steht nie in dieser Mail.
    """
    import secrets
    from konten.zeit import jetzt_wie_im_entwicklungsmodus
    from .models import SignaturCode

    if protokoll.stand != Protokoll.STAND_GEGENZEICHNUNG_OFFEN:
        return protokoll, False, "Dieses Protokoll wartet nicht auf eine Gegenzeichnung."
    now = jetzt_wie_im_entwicklungsmodus()
    empfaenger = (empfaenger or "").strip() or protokoll.gegenzeichnung_empfaenger or protokoll.person.email or ""
    if not empfaenger:
        return protokoll, False, "Für diese Person ist keine E-Mail-Adresse hinterlegt. Bitte eine Adresse eintragen."

    SignaturCode.objects.filter(protokoll=protokoll, gueltig=True).update(gueltig=False)
    protokoll.gegenzeichnung_token = secrets.token_hex(32)
    protokoll.gegenzeichnung_token_erstellt = now
    protokoll.gegenzeichnung_erinnerung_gesendet = None
    protokoll.gegenzeichnung_empfaenger = empfaenger
    protokoll.link_neu_gesendet_am = now
    protokoll.save()
    bearbeiter = protokoll.bearbeiter_signiert_von
    gesendet = _mail_gegenzeichnen_link(
        protokoll, protokoll.gegenzeichnung_token, empfaenger,
        bearbeiter_name=bearbeiter.bezeichnung() if bearbeiter is not None else "",
        erzwingen=True,
    )
    if not gesendet:
        return protokoll, False, "Der Link ist neu, die Mail ließ sich aber nicht senden."
    return protokoll, True, f"Neuer Link gesendet an {empfaenger}."


@transaction.atomic
def protokoll_gegenzeichnen(
    token: str,
    code: str,
    request=None,
) -> tuple[Protokoll | None, bool, str]:
    """F-136: Die Person signiert per Link mit Einmalcode (N-05).

    Der Zähler der Versuche steht in der Datenbank. Nach der letzten Signatur
    wird versiegelt und verschickt (F-138, F-139). Geht das Siegel nicht, bleibt das
    Protokoll offen: Einen Abschluss ohne Siegel gibt es nicht.

    Liefert (protokoll, erfolg, meldung).
    """
    import hmac
    from konten.zeit import jetzt_wie_im_entwicklungsmodus
    from .models import SignaturAufzeichnung, SignaturCode

    protokoll = Protokoll.objects.filter(gegenzeichnung_token=token).select_related("person", "geraet").first()
    if protokoll is None or not token:
        return None, False, "Unbekannter Link."
    if protokoll.stand != Protokoll.STAND_GEGENZEICHNUNG_OFFEN:
        return protokoll, False, "Dieses Protokoll wartet nicht auf eine Gegenzeichnung."
    if protokoll.gegenzeichnung_abgelaufen:
        return protokoll, False, "Der Link ist abgelaufen."
    if protokoll.bearbeiter_signiert_am is None:
        return protokoll, False, "Der Bearbeiter hat noch nicht signiert."

    aktiver = SignaturCode.objects.filter(protokoll=protokoll, gueltig=True).order_by("-erstellt_am").first()
    if aktiver is None:
        return protokoll, False, "Bitte fordern Sie zuerst einen Code an."
    if not aktiver.ist_gueltig():
        return protokoll, False, "Der Code ist abgelaufen. Bitte fordern Sie einen neuen an."
    if not hmac.compare_digest(aktiver.code, str(code or "")):
        aktiver.versucht_anzahl += 1
        if aktiver.versucht_anzahl >= 5:
            aktiver.gueltig = False
        aktiver.save()
        if not aktiver.gueltig:
            return protokoll, False, "Zu viele Fehlversuche. Der Code ist nicht mehr gültig, bitte fordern Sie einen neuen an."
        return protokoll, False, "Code ungültig."

    now = jetzt_wie_im_entwicklungsmodus()
    ip = _client_ip(request) if request else "127.0.0.1"
    empfaenger = protokoll.gegenzeichnung_empfaenger or protokoll.person.email or ""

    aktiver.verifiziert_am = now
    aktiver.verifiziert_von_ip = ip
    aktiver.gueltig = False
    aktiver.save()
    # Die Person bestätigt denselben Inhalt wie der Bearbeiter, deshalb derselbe Hash.
    pdf_hash = protokoll.pdf_hash_bearbeiter
    SignaturAufzeichnung.objects.create(
        protokoll=protokoll,
        art=SignaturAufzeichnung.KIND_GEGENZEICHNUNG,
        name=f"{protokoll.person.vorname} {protokoll.person.nachname}",
        email=empfaenger,
        zeitpunkt=now,
        nachweisnummer=_nachweisnummer(now),
        identifikationsmerkmal=f"Einmalcode an {empfaenger}",
        ip_adresse=ip,
        hashwert=pdf_hash,
    )
    protokoll.gegenzeichnung_signiert_am = now
    protokoll.gegenzeichnung_ip = ip
    protokoll.pdf_hash_gegenzeichnung = pdf_hash

    from . import pdf as pdf_modul
    try:
        pdf_bytes = pdf_modul.pdf_fertig_bauen(protokoll, versiegeln=True)
    except GeratFehler as fehler:
        transaction.set_rollback(True)
        return protokoll, False, str(fehler)

    protokoll.stand = Protokoll.STAND_ABGESCHLOSSEN
    if protokoll.art == Protokoll.ART_RUECKNAHME:
        protokoll.ruecknahme_geraet_im_lager = True
    dateiname = pdf_modul.dateiname_protokoll(protokoll)
    protokoll.pdf_siegel = pdf_bytes
    protokoll.pdf_dateiname = dateiname
    protokoll.pdf_versand_offen = not _ablage_mit_anhang(protokoll, pdf_bytes, dateiname)
    protokoll.save()
    return protokoll, True, "Gegenzeichnung abgeschlossen."


@transaction.atomic
def protokoll_korrigieren(
    protokoll: Protokoll,
    bearbeiter_konto=None,
) -> tuple[Protokoll, bool]:
    """F-135: Eine Korrektur erzeugt eine neue Fassung mit neuer Nummer.

    Das alte Protokoll ist danach ersetzt, sein Link gilt nicht mehr. Die neue
    Fassung ist wieder bearbeitbar und wird neu signiert.
    """
    from .models import SignaturCode

    if protokoll.bearbeiter_signiert_am is None or protokoll.stand == Protokoll.STAND_ERSETZT:
        return protokoll, False

    neue = Protokoll.objects.create(
        nr=_naechste_protokollnummer(),
        person=protokoll.person,
        geraet=protokoll.geraet,
        datum=protokoll.datum,
        stand=Protokoll.STAND_BEARBEITER_OFFEN,
        erzeugt_von=bearbeiter_konto or protokoll.erzeugt_von,
        fotos=protokoll.fotos,
        art=protokoll.art,
        fassung=protokoll.fassung,
        formularnummer=protokoll.formularnummer,
        absenderzeile=protokoll.absenderzeile,
        empfaenger_anschrift=protokoll.empfaenger_anschrift,
        bearbeiter=protokoll.bearbeiter,
        checkliste=dict(protokoll.checkliste or {}),
        checkliste_bemerkung=dict(protokoll.checkliste_bemerkung or {}),
        offboarding=dict(protokoll.offboarding or {}),
        positionen=list(protokoll.positionen or []),
        texte=dict(protokoll.texte or {}),
        anhaenge=list(protokoll.anhaenge or []),
        rueckgabe_zu_protokoll=protokoll.rueckgabe_zu_protokoll,
        ist_korrektur=True,
        korrigiert_zu_protokoll=protokoll,
        unterschrift_art="tool",
        leihe=protokoll.leihe,
        ort_ziel=protokoll.ort_ziel,
        gegenzeichnung_empfaenger=protokoll.gegenzeichnung_empfaenger,
    )
    neue.weitere_geraete.set(protokoll.weitere_geraete.all())
    SignaturCode.objects.filter(protokoll=protokoll, gueltig=True).update(gueltig=False)
    protokoll.stand = Protokoll.STAND_ERSETZT
    protokoll.gegenzeichnung_token = ""
    protokoll.save(update_fields=["stand", "gegenzeichnung_token"])
    return neue, True
