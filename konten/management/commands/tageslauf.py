"""Tageslauf (M7 Teil 2, A-0906).

TESTSCHNITTSTELLE 1: ``python manage.py tageslauf [--stichtag JJJJ-MM-TT]``

Erledigt für den Stichtag:
  F-91  Leihe endet morgen  → Mail an die Person
  F-92  Leihe überfällig    → Mail an Person und IT, einmal täglich
  F-94  Garantie endet in 30 Tagen → Sammelmail an die IT, nur Montag
  F-95  Unterschriften seit mehr als 3 Tagen offen → in derselben Sammelmail
  F-140 Erinnerung an die Gegenzeichnung am dritten Tag nach dem Versand des Links
  F-101 Zählerstand für das Delta
  F-53  Deaktivierung von Konten am Tag nach dem Austritt

Ein Tageslauf für denselben Stichtag verschickt nichts doppelt:
Der Versand wird in Mailversand (stammdaten) protokolliert.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

from geraete.kennzahlen import _ueberfaellige_leihen, arbeitsplaetze_vollstaendig_zahl
from konten.mail import aktive_empfaenger, link_ins_tool, mail_absender, mail_signatur
from konten.zeit import jetzt_aware, jetzt_wie_im_entwicklungsmodus
from stammdaten.models import Einstellungen, Mailversand, Ort, Person, Zaehlerstand
from geraete.models import Gerat, Leihe, Protokoll
from geraete.services import leihe_mail_empfaenger


def _it_email() -> str:
    einstellungen = Einstellungen.aktuelles()
    return einstellungen.email_it or mail_absender()


def _datums_text(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _bereits_gesendet(stichtag: date, mailtyp: str) -> bool:
    """True, wenn für den Stichtag und den Mailtyp bereits eine Mail versendet wurde."""
    return Mailversand.objects.filter(stichtag=stichtag, mailtyp=mailtyp).exists()


def _erstellt_datum(v) -> date:
    """Normalisiert ein Datum oder DateTime auf ein Datum (Europe/Berlin).

    Naive Datetimes werden in der Anzeigezeitzone interpretiert;
    aware Datetimes werden konvertiert.
    """
    if v is None:
        raise ValueError("erstellt=None")
    if hasattr(v, "hour"):
        # DateTime → Datum
        try:
            from django.utils import timezone as _tz
            return _tz.localdate(v)
        except Exception:
            return v.date()
    return v


def _versand_melden(stichtag: date, mailtyp: str, anzahl: int) -> None:
    """Versand protokollieren (F-96 Deduplizierung)."""
    if anzahl > 0:
        Mailversand.objects.create(
            stichtag=stichtag,
            mailtyp=mailtyp,
            anzahl=anzahl,
            erzeugt_am=jetzt_aware(),
        )


def _mail_leihe_endet_morgen(stichtag: date) -> int:
    """F-91: Leihe endet morgen → Mail an die Person (Frist aus den Einstellungen)."""
    einstellungen = Einstellungen.aktuelles()
    if not einstellungen.mail_leihe_endet_morgen:
        return 0
    if _bereits_gesendet(stichtag, Mailversand.MAILTYP_F91):
        return 0
    frist = einstellungen.frist_leihe_tage
    wann = {0: "heute", 1: "morgen"}.get(frist, f"in {frist} Tagen")
    morgen = stichtag + timedelta(days=frist)
    leihen = (
        Leihe.objects.filter(
            rueckgabe_bis=morgen,
            status=Leihe.STATUS_AUSGEGEBEN,
        )
        .select_related("person", "gerat")
        .order_by("id")
    )
    anzahl = 0
    for leihe in leihen:
        # F-96: keine Mail an deaktivierte Konten.
        empfaenger = aktive_empfaenger([leihe.person.email if leihe.person else ""])
        if not empfaenger:
            continue
        gerat_name = leihe.gerat.inventarnummer if leihe.gerat else ""
        send_mail(
            subject=f"Leihe endet {wann} – {gerat_name}",
            message=(
                f"Ihre Leihe {gerat_name} endet {wann} ({_datums_text(morgen)}). "
                f"Bitte geben Sie das Gerät bis dahin zurück.\n\n"
                f"Details: {link_ins_tool('/meine-geraete/')}\n\n"
                f"{mail_signatur()}"
            ),
            from_email=mail_absender(),
            recipient_list=empfaenger,
            fail_silently=True,
        )
        anzahl += 1
    _versand_melden(stichtag, Mailversand.MAILTYP_F91, anzahl)
    return anzahl


def _mail_leihe_ueberfaellig(stichtag: date) -> int:
    """F-92: Leihe überfällig → Mail an Person und IT, einmal täglich."""
    einstellungen = Einstellungen.aktuelles()
    if not einstellungen.mail_leihe_ueberfaellig:
        return 0
    if _bereits_gesendet(stichtag, Mailversand.MAILTYP_F92):
        return 0
    leihen = (
        Leihe.objects.filter(
            rueckgabe_bis__lt=stichtag,
            status=Leihe.STATUS_AUSGEGEBEN,
        )
        .select_related("person", "gerat")
        .order_by("id")
    )
    anzahl = 0
    it_email = _it_email()
    for leihe in leihen:
        empfaenger_person = leihe_mail_empfaenger(leihe.person)
        gerat_name = leihe.gerat.inventarnummer if leihe.gerat else ""
        frist = _datums_text(leihe.rueckgabe_bis)
        text = (
            f"Die Leihe {gerat_name} ist überfällig.\n"
            f"Person: {leihe.person.voller_name() if leihe.person else '–'}\n"
            f"Die Rückgabefrist ({frist}) ist überschritten.\n"
            f"Bitte geben Sie das Gerät unverzüglich zurück.\n\n"
            # F-96: Der Mitarbeiter darf /verleih/ nicht öffnen, die IT braucht es.
            f"Ihre Leihen: {link_ins_tool('/meine-geraete/')}\n"
            f"Für die IT: {link_ins_tool('/verleih/')}\n\n"
            f"{mail_signatur()}"
        )
        # F-96: keine Mail an deaktivierte Konten; die IT bleibt informiert.
        empfaenger_liste = aktive_empfaenger(
            [empfaenger_person, it_email if it_email != empfaenger_person else ""]
        )
        if not empfaenger_liste:
            continue
        send_mail(
            subject=f"Leihe überfällig – {gerat_name}",
            message=text,
            from_email=mail_absender(),
            recipient_list=empfaenger_liste,
            fail_silently=True,
        )
        anzahl += 1
    _versand_melden(stichtag, Mailversand.MAILTYP_F92, anzahl)
    return anzahl


def _mail_sammelmail(stichtag: date) -> int:
    """F-94 + F-95: Sammelmail an die IT, nur Montag.

    F-94: Garantie endet in 30 Tagen.
    F-95: Unterschriften seit mehr als 3 Tagen offen, in jedem offenen Stand:
    Bearbeiter, Gegenzeichnung oder Scan. Fristen aus den Einstellungen.
    """
    einstellungen = Einstellungen.aktuelles()
    if not einstellungen.mail_garantie_sammelmail and not einstellungen.mail_unterzeichen_sammelmail:
        return 0
    if _bereits_gesendet(stichtag, Mailversand.MAILTYP_F94):
        return 0
    if _bereits_gesendet(stichtag, Mailversand.MAILTYP_F95):
        return 0
    # Nur Montag
    if stichtag.weekday() != 0:
        return 0
    it_empfaenger = aktive_empfaenger([_it_email()])
    if not it_empfaenger:
        return 0
    sektionen = []

    # F-94: Garantie endet in 30 Tagen
    if einstellungen.mail_garantie_sammelmail:
        grenze = stichtag + timedelta(days=einstellungen.frist_garantie_tage)
        geraete = (
            Gerat.objects.filter(
                garantie_bis__gte=stichtag,
                garantie_bis__lte=grenze,
            )
            .exclude(status=Gerat.STATUS_AUSGEMUSTERT)
            .order_by("garantie_bis", "id")
        )
        if geraete.exists():
            zeilen = [
                f"- {g.inventarnummer} {g.hersteller} {g.modell} – Garantie bis {_datums_text(g.garantie_bis)}"
                for g in geraete
            ]
            sektionen.append(
                f"Geräte, deren Garantie in den nächsten {einstellungen.frist_garantie_tage} Tagen endet ({len(geraete)}):\n"
                + "\n".join(zeilen)
            )

    # F-95: Unterschriften seit mehr als 3 Tagen offen
    if einstellungen.mail_unterzeichen_sammelmail:
        tage = einstellungen.frist_unterschrift_tage
        grenze_tage = stichtag - timedelta(days=tage)
        protokolle = (
            Protokoll.objects.filter(
                stand__in=(
                    Protokoll.STAND_BEARBEITER_OFFEN,
                    Protokoll.STAND_GEGENZEICHNUNG_OFFEN,
                    Protokoll.STAND_SCAN_OFFEN,
                ),
            )
            .select_related("person")
            .order_by("datum", "id")
        )
        offene = []
        for p in protokolle:
            person_name = f"{p.person.vorname} {p.person.nachname}" if p.person else ""
            if p.stand == Protokoll.STAND_GEGENZEICHNUNG_OFFEN and p.gegenzeichnung_token_erstellt:
                seit = _erstellt_datum(p.gegenzeichnung_token_erstellt)
                zusatz = f"Link verschickt am {_datums_text(seit)}"
            else:
                seit = p.datum
                fehlt = "Bearbeiter" if p.stand == Protokoll.STAND_BEARBEITER_OFFEN else "Scan fehlt"
                zusatz = f"{fehlt}, offen seit {_datums_text(seit)}"
            if seit < grenze_tage:
                offene.append(f"- Protokoll {p.nr} ({person_name}) – {zusatz}")
        if offene:
            sektionen.append(
                f"Unterschriften, die seit mehr als {tage} Tagen offen sind ({len(offene)}):\n"
                + "\n".join(offene)
            )

    if not sektionen:
        return 0
    inhalt = "\n\n".join(
        [
            f"Wöchentliche Sammelmail vom {_datums_text(stichtag)}:",
            "",
        ]
        + sektionen
        + [
            "",
            f"Details: {link_ins_tool('/')}",
            "",
            mail_signatur(),
        ]
    )
    send_mail(
        subject=f"Wöchentliche Sammelmail – {_datums_text(stichtag)}",
        message=inhalt,
        from_email=mail_absender(),
        recipient_list=it_empfaenger,
        fail_silently=True,
    )
    # Beide Typen als gesendet markieren (eine Sammelmail deckt beide ab)
    if einstellungen.mail_garantie_sammelmail:
        _versand_melden(stichtag, Mailversand.MAILTYP_F94, 1)
    if einstellungen.mail_unterzeichen_sammelmail:
        _versand_melden(stichtag, Mailversand.MAILTYP_F95, 1)
    return 1


def _mail_gegenzeichnung_erinnerung(stichtag: date) -> int:
    """F-140: Erinnerung an die Gegenzeichnung am dritten Tag nach dem Versand.

    Link am 02.11. → Erinnerung am 05.11. (Stichtag = Versanddatum + 3 Tage).
    Genau ein Stichtag trifft je Protokoll: der dritte Tag nach dem Versand.
    Eine bereits gesendete Erinnerung wird nicht wiederholt.
    """
    einstellungen = Einstellungen.aktuelles()
    if not einstellungen.mail_gegenzeichnung_erinnerung:
        return 0
    if _bereits_gesendet(stichtag, Mailversand.MAILTYP_F140):
        return 0
    versanddatum = stichtag - timedelta(days=einstellungen.frist_gegenzeichnung_tage)
    protokolle = (
        Protokoll.objects.filter(
            stand=Protokoll.STAND_GEGENZEICHNUNG_OFFEN,
            gegenzeichnung_token_erstellt__isnull=False,
        )
        .select_related("person")
        .order_by("id")
    )
    anzahl = 0
    for p in protokolle:
        erstellt = p.gegenzeichnung_token_erstellt
        if erstellt is None:
            continue
        erstellt_datum = _erstellt_datum(erstellt)
        # F-140: exakt am dritten Tag nach dem Versand
        if erstellt_datum != versanddatum:
            continue
        empfaenger = p.gegenzeichnung_empfaenger or (p.person.email if p.person else "")
        if not empfaenger:
            continue
        # F-96: Der Link zur Gegenzeichnung geht auch an deaktivierte Konten.
        link = link_ins_tool(f"/signieren/{p.gegenzeichnung_token}/")
        send_mail(
            subject=f"Erinnerung: Gegenzeichnung Protokoll {p.nr}",
            message=(
                f"Sie haben am {_datums_text(versanddatum)} einen Link zur Gegenzeichnung "
                f"des Protokolls {p.nr} erhalten.\n\n"
                f"Bitte zeichnen Sie gegen: {link}\n\n"
                f"{mail_signatur()}"
            ),
            from_email=mail_absender(),
            recipient_list=[empfaenger],
            fail_silently=True,
        )
        p.gegenzeichnung_erinnerung_gesendet = jetzt_aware()
        p.save(update_fields=["gegenzeichnung_erinnerung_gesendet"])
        anzahl += 1
    _versand_melden(stichtag, Mailversand.MAILTYP_F140, anzahl)
    return anzahl


def _personen_austreten(stichtag: date) -> int:
    """F-53: Person wird am Austrittstag inaktiv, vorher ist sie wählbar."""
    return Person.objects.filter(austritt__lte=stichtag, aktiv=True).update(aktiv=False)


def _konten_deaktivieren(stichtag: date) -> int:
    """F-53: Konto am Tag nach dem Austrittsdatum deaktivieren.

    Austritt am 02.11. → deaktiviert am 03.11.
    """
    from konten.models import Konto

    grenze = stichtag - timedelta(days=1)
    konten = Konto.objects.filter(
        person__austritt__isnull=False,
        person__austritt__lte=grenze,
        aktiv=True,
    ).select_related("person")
    anzahl = 0
    for konto in konten:
        konto.aktiv = False
        konto.save(update_fields=["aktiv"])
        anzahl += 1
    return anzahl


def _zaehlerstand_anlegen(stichtag: date) -> dict:
    """F-101: Zählerstand für das Delta."""
    aktive = Gerat.objects.exclude(status=Gerat.STATUS_AUSGEMUSTERT)
    in_benutzung = aktive.filter(status=Gerat.STATUS_IN_BENUTZUNG).count()
    aktive_gesamt = aktive.count()
    verliehen = aktive.filter(status=Gerat.STATUS_VERLIEHEN).count()
    leihpool_gesamt = aktive.filter(leihpool=True).count()

    # F-100: dieselben Zählungen wie die Übersicht, sonst stimmt das Delta nicht.
    ueberfaellig = _ueberfaellige_leihen(stichtag).count()

    anfragen_offen = Leihe.objects.filter(status=Leihe.STATUS_ANGEFRAGT).count()

    grenze_30 = stichtag + timedelta(days=30)
    garantie_30 = aktive.filter(
        garantie_bis__gte=stichtag,
        garantie_bis__lte=grenze_30,
    ).count()

    unterschriften_offen = Protokoll.objects.filter(
        stand__in=(
            Protokoll.STAND_BEARBEITER_OFFEN,
            Protokoll.STAND_GEGENZEICHNUNG_OFFEN,
            Protokoll.STAND_SCAN_OFFEN,
        )
    ).count()

    arbeitsplaetze = Ort.objects.filter(typ=Ort.TYP_ARBEITSPLATZ)
    ap_gesamt = arbeitsplaetze.count()
    ap_vollstaendig = arbeitsplaetze_vollstaendig_zahl()

    geprueft = aktive.filter(zuletzt_geprueft_am__isnull=False).count()

    kennzahlen = {
        "in-benutzung": {"ist": in_benutzung, "gesamt": aktive_gesamt},
        "arbeitsplaetze-vollstaendig": {"ist": ap_vollstaendig, "gesamt": ap_gesamt},
        "verliehen": {"ist": verliehen, "gesamt": leihpool_gesamt},
        "geprueft": {"ist": geprueft, "gesamt": aktive_gesamt},
        "ueberfaellig": {"ist": ueberfaellig},
        "anfragen-offen": {"ist": anfragen_offen},
        "garantie-30-tage": {"ist": garantie_30},
        "unterschriften-offen": {"ist": unterschriften_offen},
    }
    Zaehlerstand.objects.update_or_create(
        stichtag=stichtag,
        defaults={"kennzahlen": kennzahlen, "erzeugt_am": jetzt_aware()},
    )
    return kennzahlen


def delta_zum_vortag(stichtag: date) -> dict | None:
    """F-101: Delta zum Vortag aus den Zählerständen."""
    vortag = stichtag - timedelta(days=1)
    alt = Zaehlerstand.objects.filter(stichtag=vortag).first()
    neu = Zaehlerstand.objects.filter(stichtag=stichtag).first()
    if alt is None or neu is None:
        return None
    delta = {}
    for key, wert in neu.kennzahlen.items():
        alt_wert = alt.kennzahlen.get(key, {})
        ist_neu = wert.get("ist")
        ist_alt = alt_wert.get("ist")
        if ist_neu is not None and ist_alt is not None:
            delta[key] = ist_neu - ist_alt
    return delta


class Command(BaseCommand):
    help = "Tageslauf: Mails, Konten-Deaktivierung und Zählerstand (F-91 bis F-96, F-140, F-53, F-101)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--stichtag",
            type=str,
            default=None,
            help="Stichtag im Format JJJJ-MM-TT. Ohne Angabe: heute.",
        )

    def handle(self, *args, **options):
        stichtag_str = options.get("stichtag")
        if stichtag_str:
            try:
                stichtag = date.fromisoformat(stichtag_str)
            except ValueError:
                raise CommandError(f"Ungültiger Stichtag: {stichtag_str}. Erwartet: JJJJ-MM-TT.")
        else:
            # TESTSCHNITTSTELLE 1.2: „heute“ ist die Zeit der Anwendung.
            stichtag = jetzt_wie_im_entwicklungsmodus().date()

        self.stdout.write(f"Tageslauf für {stichtag:%d.%m.%Y}")

        # F-53: Personen und Konten nach dem Austritt (vor den Mails)
        self.stdout.write(f"  F-53  Personen inaktiv: {_personen_austreten(stichtag)}")
        deaktiviert = _konten_deaktivieren(stichtag)
        self.stdout.write(f"  F-53  Konten deaktiviert: {deaktiviert}")

        # F-91: Leihe endet morgen
        anzahl_f91 = _mail_leihe_endet_morgen(stichtag)
        self.stdout.write(f"  F-91  Mails Leihe endet morgen: {anzahl_f91}")

        # F-92: Leihe überfällig
        anzahl_f92 = _mail_leihe_ueberfaellig(stichtag)
        self.stdout.write(f"  F-92  Mails Leihe ueberfaellig: {anzahl_f92}")

        # F-94 + F-95: Sammelmail (nur Montag)
        anzahl_sammel = _mail_sammelmail(stichtag)
        self.stdout.write(f"  F-94/F-95  Sammelmail (nur Montag): {anzahl_sammel}")

        # F-140: Erinnerung Gegenzeichnung
        anzahl_f140 = _mail_gegenzeichnung_erinnerung(stichtag)
        self.stdout.write(f"  F-140  Erinnerungen Gegenzeichnung: {anzahl_f140}")

        # F-101: Zählerstand
        kennzahlen = _zaehlerstand_anlegen(stichtag)
        self.stdout.write(f"  F-101  Zählerstand angelegt: {len(kennzahlen)} Kennzahlen")

        # F-93/F-32: Leihanfrage-Mails sind sofort (in den Services),
        # nicht Teil des Tageslaufs.

        self.stdout.write(self.style.SUCCESS("Tageslauf abgeschlossen."))
