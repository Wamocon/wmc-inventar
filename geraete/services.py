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


def ausgabe_sperrgrund(gerat: Gerat) -> str:
    """Warum dieses Gerät nicht ausgegeben werden kann (F-20, F-21); leer, wenn es geht."""
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        return "Ausgemusterte Geräte können nicht ausgegeben werden."
    if gerat.status == Gerat.STATUS_IN_REPARATUR:
        return "Geräte in Reparatur können nicht ausgegeben werden."
    # Kapitel 4: Nur „Auf Lager“; ein Personenwechsel läuft über die Rückgabe.
    if gerat.status != Gerat.STATUS_AUF_LAGER:
        return "Nur Geräte „Auf Lager“ können ausgegeben werden. Bitte zuerst zurücknehmen."
    if gerat.alle_protokolle().filter(stand=Protokoll.STAND_BEARBEITER_OFFEN).exists():
        return (
            "Für dieses Gerät steht bereits ein offenes Protokoll. "
            "Eine weitere Ausgabe ist solange nicht möglich (F-21)."
        )
    if _gerat_ist_reserviert(gerat):
        return "Gerät ist reserviert und kann nicht ausgegeben werden (F-20)."
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
        zustand = werte.get("zustand")
        positionen.append(position_aus_gerat(
            gerat,
            zustand_ausgabe=int(zustand) if zustand else None,
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
            zeitpunkt=timezone.now(),
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
        datum=timezone.now().date(),
        stand=stand,
        art=art,
        fassung="1.1",
        formularnummer=(
            "FRM-002" if art == Protokoll.ART_RUECKNAHME else "FRM-001"
        ),
        absenderzeile=_absenderzeile(),
        positionen=positionen if positionen is not None else [position_aus_gerat(gerat)],
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
            raise GeratFehler("Art der Löschung muss angegeben werden (F-56).")
        if not loeschung_nachweis and not loeschung_datei:
            raise GeratFehler("Nachweis der Löschung muss angegeben werden (F-56).")
    if verloren and not bestaetigt_gemeldt:
        raise GeratFehler("Pflichtbestätigung, dass der Vorfall gemeldet wurde (F-57).")

    teile = []
    if not verloren and loeschung_art:
        teile.append("Löschung: " + LOESCHUNG_ARTEN.get(loeschung_art, loeschung_art))
    if not verloren and loeschung_nachweis:
        teile.append("Nachweis: " + loeschung_nachweis)
    if verloren:
        teile.append("Vorfall an Datenschutz bzw. Informationssicherheit gemeldet")

    _leihe_schliessen(gerat)
    gerat.status = Gerat.STATUS_AUSGEMUSTERT
    gerat.person = None
    gerat.ort = None
    vorgang = Vorgang(
        gerat=gerat,
        typ=Vorgang.TYP_AUSMUSTERUNG,
        zeitpunkt=timezone.now(),
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


def _nachweis_pruefen(datei) -> tuple:
    """Anhang: PDF, JPG oder PNG bis 10 MB, am Inhalt geprüft (Kapitel 3.1, N-02)."""
    from django.core.files.base import ContentFile
    from .protokoll import _typ_am_inhalt

    roh = datei.read(_ANHANG_GROESSE + 1)
    if len(roh) > _ANHANG_GROESSE:
        raise GeratFehler("Der Nachweis ist größer als 10 MB.")
    endung = _ANHANG_ENDUNGEN.get(_typ_am_inhalt(roh) or "")
    if endung is None:
        raise GeratFehler("Nachweis nicht erlaubt: PDF, JPG oder PNG bis 10 MB.")
    return f"nachweis-{timezone.now():%Y%m%d-%H%M%S}{endung}", ContentFile(roh)


def standard_lager() -> Ort | None:
    """Der Lagerort, wenn der Dialog keinen nennt (Kapitel 4: Auf Lager heißt Lagerort)."""
    return Ort.objects.filter(typ=Ort.TYP_LAGER).order_by("kennung").first()


def _leihe_schliessen(gerat: Gerat) -> None:
    """Das Gerät ist zurück oder weg: Seine ausgegebene Leihe ist damit zu Ende (F-35)."""
    Leihe.objects.filter(gerat=gerat, status=Leihe.STATUS_AUSGEGEBEN).update(
        status=Leihe.STATUS_ZURUECKGEGEBEN, genehmigt=False,
    )


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
            zustand_rueckgabe=int(eintrag["zustand_rueckgabe"]),
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
        )
        protokoll.weitere_geraete.set([e["gerat"] for e in posten[1:]])
        if empfaenger.strip():
            protokoll.gegenzeichnung_empfaenger = empfaenger.strip()
            protokoll.save(update_fields=["gegenzeichnung_empfaenger"])

    for eintrag, position in zip(posten, positionen):
        gerat = eintrag["gerat"]
        gerat.zustand = position["zustand_rueckgabe"]
        _leihe_schliessen(gerat)
        if gerat.status == Gerat.STATUS_IN_REPARATUR:
            # Bleibt beim Dienstleister, die gemerkte Zuordnung endet hier.
            gerat.ort = None
        elif eintrag.get("ziel") == "reparatur":
            gerat.status = Gerat.STATUS_IN_REPARATUR
            gerat.ort = None
        else:
            gerat.status = Gerat.STATUS_AUF_LAGER
            gerat.ort = eintrag.get("lagerort") or standard_lager()
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
            zeitpunkt=timezone.now(),
            erzeugt_von=ausgefuehrt_von,
            notiz=", ".join(teile),
            protokoll=protokoll,
            abschliesst=True,
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
        raise GeratFehler("Ein fehlendes Gerät läuft über den Dialog Ausmustern mit Grund „verloren“ (F-50).")
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
    schluessel = [k for k, _text in Protokoll.OFFBOARDING_PUNKTE]
    erledigt = {
        "status": "erledigt",
        "datum": timezone.now().strftime("%d.%m.%Y"),
        "kuerzel": _bearbeiter_kuerzel(konto),
        "bemerkung": "",
    }
    if getattr(person, "austritt", None):
        return {schluessel[-1]: erledigt}
    vorbelegung = {
        k: {"status": "nicht_zutreffend", "datum": "", "kuerzel": "", "bemerkung": ""}
        for k in schluessel
    }
    vorbelegung[schluessel[0]] = dict(erledigt)
    vorbelegung[schluessel[-1]] = dict(erledigt)
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
    lagerort: Ort | None = None,
) -> Gerat:
    """Reparatur abschließen (F-42, M3).

    Abschluss mit neuem Zustand und Ziel „bisherige Zuordnung" oder „Lager".
    """
    if gerat.status != Gerat.STATUS_IN_REPARATUR:
        raise GeratFehler("Nur Geräte in Reparatur können repariert werden.")

    gerat.zustand = zustand

    if ziel == "zuordnung":
        # F-42: Ziel „Bisherige Zuordnung" – Gerät geht zurück zu Person/Ort.
        # Ein Gerät, das vor der Reparatur im Lager stand, ist danach wieder „Auf Lager“.
        if gerat.person is None and (gerat.ort is None or gerat.ort.typ == Ort.TYP_LAGER):
            gerat.status = Gerat.STATUS_AUF_LAGER
            gerat.ort = gerat.ort or standard_lager()
        else:
            gerat.status = Gerat.STATUS_IN_BENUTZUNG
    else:
        # F-42: Ziel „Lager"
        gerat.status = Gerat.STATUS_AUF_LAGER
        gerat.person = None
        gerat.ort = lagerort or standard_lager()

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
        "leihpool", "geraetename", "standardzuehoer",
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
    if gerat.status == Gerat.STATUS_AUSGEMUSTERT:
        raise GeratFehler("Ausgemusterte Geräte sind nicht mehr änderbar.")
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


def _mail_absender() -> str:
    from django.conf import settings
    return settings.DEFAULT_FROM_EMAIL


def _firmenname() -> str:
    from stammdaten.models import Einstellungen
    return Einstellungen.aktuelles().firmenname


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

    # F-132: Signatur wird abgelehnt, solange die Checkliste noch offen ist.
    from . import pdf as pdf_modul
    if pdf_modul._offene_punkte(protokoll):
        return protokoll, False

    # F-135: Inhalt einfrieren; der Hash steht im Prüfprotokoll (F-137).
    html, pdf_hash = pdf_modul.inhalt_einfrieren(protokoll)
    protokoll.html_eingefroren = html
    protokoll.bearbeiter_signiert_am = now
    protokoll.bearbeiter_signiert_von = konto
    protokoll.bearbeiter_ip = ip
    protokoll.pdf_hash_bearbeiter = pdf_hash
    protokoll.bearbeiter = konto.bezeichnung()

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
    if protokoll.art == Protokoll.ART_AUSGABE and protokoll.unterschrift_art == "tool" and not protokoll.ist_korrektur:
        _ausgabe_wirksam_machen(protokoll, konto, now)

    # F-136: Token für die Gegenzeichnung (14 Tage gültig).
    import secrets
    token = secrets.token_hex(32)
    empfaenger = protokoll.gegenzeichnung_empfaenger or protokoll.person.email or ""
    protokoll.gegenzeichnung_token = token
    protokoll.gegenzeichnung_token_erstellt = now
    protokoll.gegenzeichnung_empfaenger = empfaenger
    protokoll.stand = Protokoll.STAND_GEGENZEICHNUNG_OFFEN
    protokoll.save()

    _mail_gegenzeichnen_link(protokoll, token, empfaenger, bearbeiter_name=konto.bezeichnung())
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
        if protokoll.leihe_id:
            # Verleih: Status Verliehen, Person gesetzt, Ort leer (F-30).
            gerat.status = Gerat.STATUS_VERLIEHEN
            gerat.ort = None
            if protokoll.leihe.status != Leihe.STATUS_AUSGEGEBEN:
                protokoll.leihe.status = Leihe.STATUS_AUSGEGEBEN
                protokoll.leihe.save()
        else:
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
    return f"Sehr geehrter Herr {person.nachname}"


def _mail_gegenzeichnen_link(
    protokoll: Protokoll,
    token: str,
    empfaenger: str,
    bearbeiter_name: str = "",
) -> None:
    """Mail mit persönlichem Link (F-136), 14 Tage gültig."""
    from django.core.mail import send_mail

    if not empfaenger:
        return
    inhalt = (
        f"{_anrede_mail(protokoll.person)},\n\n"
        f"das Protokoll {protokoll.nr} steht zur Gegenzeichnung bereit.\n"
        "Öffnen Sie den folgenden Link, sehen Sie das PDF an und signieren Sie "
        "mit einem Einmalcode, den Sie dort per Mail anfordern:\n\n"
        f"Link: {_link_gegenzeichnung(token)}\n\n"
        "Der Link ist 14 Tage gültig.\n\n"
        f"Mit freundlichen Grüßen\n{bearbeiter_name or _firmenname()}"
    )
    send_mail(f"Gegenzeichnung: Protokoll {protokoll.nr}", inhalt, _mail_absender(), [empfaenger])


def protokoll_code_senden(
    protokoll: Protokoll,
    empfaenger: str | None = None,
    request=None,
) -> tuple[bool, str]:
    """F-136: Einmalcode erzeugen und per Mail senden (N-05).

    6-stellig, 10 Minuten gültig, höchstens 5 Versuche. Die Adresse kann die IT
    im Dialog ändern (F-141, Rückgabe per Post); sie steht dann im Prüfprotokoll.
    """
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
        f"Mit freundlichen Grüßen\n{_firmenname()}"
    )
    from django.core.mail import send_mail
    send_mail(f"Einmalcode für Protokoll {protokoll.nr}", inhalt, _mail_absender(), [empfaenger])
    return True, "Code gesendet."


def _ablage_mit_anhang(
    protokoll: Protokoll,
    pdf_bytes: bytes,
    dateiname: str,
) -> None:
    """F-139: Das fertige PDF geht an Person und Bearbeiter, je eine Ausfertigung.

    Abgelegt ist es im Protokoll selbst (``pdf_siegel``), und von dort kommt es am
    Gerät, an der Person und im Self-Service.
    """
    person_email = protokoll.gegenzeichnung_empfaenger or protokoll.person.email or ""
    if person_email:
        _mail_anhang(protokoll, pdf_bytes, dateiname, person_email)
    bearbeiter = protokoll.bearbeiter_signiert_von or protokoll.erzeugt_von
    bearbeiter_email = bearbeiter.email if bearbeiter is not None else ""
    if bearbeiter_email and bearbeiter_email != person_email:
        _mail_anhang(protokoll, pdf_bytes, dateiname, bearbeiter_email)


def _mail_anhang(
    protokoll: Protokoll,
    pdf_bytes: bytes,
    dateiname: str,
    empfaenger: str,
) -> None:
    """F-139: Mail mit dem versiegelten PDF als Anhang an einen Empfänger."""
    from django.core.mail import EmailMessage

    msg = EmailMessage(
        subject=f"Protokoll {protokoll.nr}: abgeschlossen",
        body=(
            f"Das Protokoll {protokoll.nr} ist von beiden Seiten signiert.\n\n"
            f"Anbei erhalten Sie das versiegelte PDF ({dateiname}).\n\n"
            f"{_firmenname()}"
        ),
        from_email=_mail_absender(),
        to=[empfaenger],
    )
    msg.attach(dateiname, pdf_bytes, "application/pdf")
    msg.send()


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
    _mail_gegenzeichnen_link(
        protokoll, protokoll.gegenzeichnung_token, empfaenger,
        bearbeiter_name=bearbeiter.bezeichnung() if bearbeiter is not None else "",
    )
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
    protokoll.save()
    _ablage_mit_anhang(protokoll, pdf_bytes, dateiname)
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
        anhaenge=list(protokoll.anhaenge or []),
        rueckgabe_zu_protokoll=protokoll.rueckgabe_zu_protokoll,
        ist_korrektur=True,
        korrigiert_zu_protokoll=protokoll,
        unterschrift_art="tool",
        leihe=protokoll.leihe,
        ort_ziel=protokoll.ort_ziel,
    )
    SignaturCode.objects.filter(protokoll=protokoll, gueltig=True).update(gueltig=False)
    protokoll.stand = Protokoll.STAND_ERSETZT
    protokoll.gegenzeichnung_token = ""
    protokoll.save(update_fields=["stand", "gegenzeichnung_token"])
    return neue, True
