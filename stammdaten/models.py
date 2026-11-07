"""Stammdaten-Modelle.

Kapitel 3 der Anforderungen (Datenmodell), F-60, F-120, F-121.
"""
from __future__ import annotations

from django.db import models


class Kategorie(models.Model):
    """Kategorie eines Geräts (F-120).

    Vorbelegung nach der Bestandsliste (Kapitel 3.2), je mit:
      - hat Datenträger (ja/nein)
      - Seriennummer Pflicht (ja/nein)
    Kategorien mit Geräten sind nicht löschbar (F-120).
    """

    name = models.CharField("Name", max_length=120, unique=True)
    hat_datentraeger = models.BooleanField("hat Datenträger", default=False)
    seriennummer_pflicht = models.BooleanField("Seriennummer Pflicht", default=False)

    class Meta:
        verbose_name = "Kategorie"
        verbose_name_plural = "Kategorien"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Plan(models.Model):
    """Grundriss eines Standorts und einer Etage (F-65, F-67).

    Positionen der Plätze und Räume (``Ort``) stehen in Prozent von Breite
    und Höhe dieses Grundrisses, gemessen am Mittelpunkt
    (TESTSCHNITTSTELLE 2). Der Grundriss selbst ist eine SVG-Datei, die bei
    ``beispieldaten`` aus ``docs/vorlagen/`` in die DATEIABLAGE kopiert wird.
    """

    standort = models.CharField("Standort", max_length=120)
    etage = models.CharField("Etage", max_length=40)
    name = models.CharField("Name", max_length=120, blank=True, default="")
    # F-67: Grundriss als Datei in der DATEIABLAGE; die Positionen bleiben
    # beim Austausch erhalten, weil sie pro Ort in Prozent gespeichert sind.
    grundriss = models.FileField(
        "Grundriss (Datei in der DATEIABLAGE)",
        upload_to="grundrisse/",
        blank=True,
        default="",
        null=True,
    )
    erzeugt_am = models.DateTimeField("Erzeugt am", auto_now_add=True)

    class Meta:
        verbose_name = "Plan"
        verbose_name_plural = "Pläne"
        ordering = ["standort", "etage"]

    def __str__(self):
        return f"{self.standort}, {self.etage}"


class Person(models.Model):
    """Person (F-121, Kapitel 3.2).

    N-04: Personendaten auf Name, E-Mail, Abteilung, Ein-/Austritt und Anschrift beschränkt.
    Personen gibt es auch ohne Konto (Kapitel 3.2).
    """

    ANREDE_HERR = "h"
    ANREDE_FRAU = "f"
    ANREDEN = [
        (ANREDE_HERR, "Herr"),
        (ANREDE_FRAU, "Frau"),
    ]

    anrede = models.CharField("Anrede", max_length=1, choices=ANREDEN, default=ANREDE_HERR)
    vorname = models.CharField("Vorname", max_length=120)
    nachname = models.CharField("Nachname", max_length=120)
    email = models.EmailField("E-Mail", null=True, blank=True, unique=True)
    abteilung = models.CharField("Abteilung", max_length=120, blank=True)
    eintritt = models.DateField("Eintritt", null=True, blank=True)
    austritt = models.DateField("Austritt", null=True, blank=True)
    anschrift = models.TextField("Anschrift (Briefkopf)", blank=True, default="")
    aktiv = models.BooleanField("aktiv", default=True)

    # F-121: Kürzel aus Anfangsbuchstaben von Vor- und Nachname (TESTSCHNITTSTELLE 2)
    @property
    def kuerzel(self) -> str:
        if not (self.vorname and self.nachname):
            return ""
        return (self.vorname[0] + self.nachname[0]).upper()

    class Meta:
        verbose_name = "Person"
        verbose_name_plural = "Personen"
        ordering = ["nachname", "vorname"]

    def __str__(self):
        return f"{self.vorname} {self.nachname}"

    def voller_name(self) -> str:
        return f"{self.vorname} {self.nachname}"


class Ort(models.Model):
    """Ort (F-60): Arbeitsplatz, Raum oder Lager.

    Kapitel 3.2: Kennung eindeutig (z. B. WMC-WP-01), Standort, Raum,
    Raumplan und Position darauf (x, y in Prozent des Bildes), Notiz.
    Nur Arbeitsplätze haben Profil und feste Person.
    Typ „Raum“ für Geräte ohne festen Platz (Studiotechnik, Serverraum).
    """

    TYP_ARBEITSPLATZ = "arbeitsplatz"
    TYP_RAUM = "raum"
    TYP_LAGER = "lager"
    TYPEN = [
        (TYP_ARBEITSPLATZ, "Arbeitsplatz"),
        (TYP_RAUM, "Raum"),
        (TYP_LAGER, "Lager"),
    ]

    typ = models.CharField("Typ", max_length=16, choices=TYPEN, default=TYP_ARBEITSPLATZ)
    kennung = models.CharField("Kennung", max_length=64, unique=True)
    name = models.CharField("Name", max_length=160, blank=True, default="")
    standort = models.CharField("Standort", max_length=160, default="Eschborn")
    raum = models.CharField("Raum", max_length=160, blank=True, default="")
    notiz = models.TextField("Notiz", blank=True, default="")
    plan_id = models.IntegerField("Plan-ID", null=True, blank=True)
    position_x = models.FloatField("Position x (%)", null=True, blank=True)
    position_y = models.FloatField("Position y (%)", null=True, blank=True)
    # M4: Zeitstempel der letzten Änderung; Basis für den Fortschritt
    # „geprüft / alle“ bei der Erstinventur (F-89, AUFTRAG M4).
    aktualisiert_am = models.DateTimeField(null=True, blank=True)

    # Nur Arbeitsplätze (Kapitel 3.2)
    feste_person = models.ForeignKey(
        Person,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feste_plaetze",
    )
    profil = models.ForeignKey(
        "stammdaten.Ausstattungsprofil",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="plaetze",
    )

    class Meta:
        verbose_name = "Ort"
        verbose_name_plural = "Orte"
        ordering = ["kennung"]

    def __str__(self):
        return self.kennung

    @property
    def ist_arbeitsplatz(self) -> bool:
        return self.typ == self.TYP_ARBEITSPLATZ

    @property
    def ist_raum(self) -> bool:
        return self.typ == self.TYP_RAUM

    @property
    def ist_lager(self) -> bool:
        return self.typ == self.TYP_LAGER

    @property
    def hat_position(self) -> bool:
        return self.position_x is not None and self.position_y is not None


class Checklistenpunkt(models.Model):
    """Ein Punkt der Checkliste Zugänge oder der Prüfpunkte IT-Offboarding (Kapitel 3.2)."""

    LISTEN = [("zugaenge", "Zugänge"), ("offboarding", "IT-Offboarding")]

    liste = models.CharField("Liste", max_length=20, choices=LISTEN)
    schluessel = models.CharField("Schlüssel", max_length=40)
    text = models.CharField("Text", max_length=200)
    reihenfolge = models.PositiveIntegerField("Reihenfolge", default=0)
    aktiv = models.BooleanField("aktiv", default=True)

    class Meta:
        verbose_name = "Checklistenpunkt"
        verbose_name_plural = "Checklistenpunkte"
        ordering = ["liste", "reihenfolge", "id"]
        constraints = [models.UniqueConstraint(fields=("liste", "schluessel"), name="checklistenpunkt_eindeutig")]

    def __str__(self):
        return self.text


class Einstellungen(models.Model):
    """M7 Teil 1 (A-0905): Einstellungen (F-122, F-90, F-96, F-130, N-02).

    Singleton-Modell: genau eine Zeile (pk=1). ``beispieldaten`` legt die
    Platzhalterwerte aus TESTSCHNITTSTELLE.md Abschnitt 2 an.

    F-122: Firmenname, Absenderzeile, Telefon und E-Mail der IT.
    N-02:  Logo als PNG oder SVG; SVG wird nur als Bild eingebunden
           (``<img src=...>``), nie als Inline-SVG.
    F-130: Protokolltexte (Nutzungsbedingungen, Erklärungen,
           Elektronische Unterzeichnung) mit Versionsnummer.
           Eine neue Version gilt nur für neue Protokolle.
    F-90:  SMTP-Zugang; „Testmail senden“ erzeugt eine Mail in der Mailablage.
    F-96:  Schalter je Mailart; abgeschaltete Mailart erzeugt keine Mail.
    """

    # --- Firma / Absender (F-122) ---
    firmenname = models.CharField(
        max_length=200, default="",
        verbose_name="Firmenname",
    )
    absenderzeile = models.CharField(
        max_length=255, default="",
        verbose_name="Absenderzeile",
    )
    telefon = models.CharField(
        max_length=50, default="",
        verbose_name="Telefon der IT",
    )
    email_it = models.EmailField(
        blank=True, default="",
        verbose_name="E-Mail der IT",
    )

    # --- Logo (N-02) ---
    logo = models.FileField(
        upload_to="logo/",
        blank=True, default="",
        verbose_name="Logo (PNG oder SVG)",
    )

    # --- Protokolltexte mit Versionsnummer (F-130) ---
    nutzungsbedingungen_ausgabe = models.TextField(
        blank=True, default="",
        verbose_name="Nutzungsbedingungen (Ausgabeprotokoll)",
    )
    nutzungsbedingungen_version = models.CharField(
        max_length=20, default="1",
        verbose_name="Version Nutzungsbedingungen",
    )
    erklaerungen_ausgabe = models.TextField(
        blank=True, default="",
        verbose_name="Erklärungen (Ausgabeprotokoll)",
    )
    erklaerungen_version = models.CharField(
        max_length=20, default="1",
        verbose_name="Version Erklärungen",
    )
    unterzeichnung_ausgabe = models.TextField(
        blank=True, default="",
        verbose_name="Elektronische Unterzeichnung (Ausgabeprotokoll)",
    )
    unterzeichnung_version = models.CharField(
        max_length=20, default="1",
        verbose_name="Version Elektronische Unterzeichnung",
    )
    erklaerungen_ruecknahme = models.TextField(
        blank=True, default="",
        verbose_name="Erklärungen (Rücknahmeprotokoll)",
    )
    erklaerungen_ruecknahme_version = models.CharField(
        max_length=20, default="1",
        verbose_name="Version Erklärungen (Rücknahme)",
    )
    unterzeichnung_ruecknahme = models.TextField(
        blank=True, default="",
        verbose_name="Elektronische Unterzeichnung (Rücknahmeprotokoll)",
    )
    unterzeichnung_ruecknahme_version = models.CharField(
        max_length=20, default="1",
        verbose_name="Version Elektronische Unterzeichnung (Rücknahme)",
    )

    # --- Etiketten ---
    # F-14: Höchste je vergebene Nummer, damit ein gelöschtes Gerät seine nicht weitergibt.
    inventar_zaehler = models.PositiveIntegerField("Höchste vergebene Inventarnummer", default=0)
    etikettenformat = models.CharField(
        max_length=20, default="a4",
        choices=[("a4", "A4-Bogen, 24 Etiketten, 70 × 37 mm"), ("a5", "A5-Bogen, 10 Etiketten, 74 × 42 mm")],
        verbose_name="Etikettenformat",
    )

    # --- Erinnerungsfristen (F-122); Vorgabe nach F-91, F-94, F-95, F-140 ---
    frist_leihe_tage = models.PositiveIntegerField(
        default=1,
        verbose_name="Leihe endet: Erinnerung (Tage vorher)",
    )
    frist_garantie_tage = models.PositiveIntegerField(
        default=30,
        verbose_name="Garantie endet: Sammelmail (Tage vorher)",
    )
    frist_unterschrift_tage = models.PositiveIntegerField(
        default=3,
        verbose_name="Unterschrift offen: Sammelmail (mehr als Tage)",
    )
    frist_gegenzeichnung_tage = models.PositiveIntegerField(
        default=3,
        verbose_name="Gegenzeichnung: Erinnerung (Tage nach dem Versand)",
    )

    # --- SMTP (F-90) ---
    smtp_server = models.CharField(
        max_length=255, default="",
        verbose_name="SMTP-Server",
    )
    smtp_port = models.PositiveIntegerField(
        default=587,
        verbose_name="SMTP-Port",
    )
    smtp_tls = models.BooleanField(
        default=True,
        verbose_name="TLS",
    )
    smtp_absender = models.EmailField(
        blank=True, default="",
        verbose_name="SMTP-Absender",
    )
    smtp_benutzer = models.CharField(
        max_length=255, default="",
        verbose_name="SMTP-Benutzer",
    )
    smtp_passwort = models.CharField(
        max_length=255, default="",
        verbose_name="SMTP-Passwort",
    )

    # --- Mailtypen (F-96) ---
    mail_verleih_anfrage = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Verleihanfrage",
    )
    mail_verleih_ablehnung = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Verleih-Ablehnung",
    )
    mail_verleih_genehmigung = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Verleih-Genehmigung",
    )
    mail_verleih_zuruecknahme = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Verleih-Zurücknahme",
    )
    mail_protokoll_gesendet = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Protokoll gesendet",
    )
    mail_protokoll_unterzeichnet = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Protokoll unterzeichnet",
    )
    # --- Mailtypen Tageslauf (F-96, M7 Teil 2) ---
    mail_leihe_endet_morgen = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Leihe endet morgen",
    )
    mail_leihe_ueberfaellig = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Leihe überfällig",
    )
    mail_leihe_neu = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Leihanfrage an die IT",
    )
    mail_garantie_sammelmail = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Sammelmail Garantie",
    )
    mail_unterzeichen_sammelmail = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Sammelmail Unterschriften",
    )
    mail_gegenzeichnung_erinnerung = models.BooleanField(
        default=True,
        verbose_name="E-Mail: Erinnerung Gegenzeichnung",
    )

    # --- Zeitstempel ---
    aktualisiert_am = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Einstellungen"
        verbose_name_plural = "Einstellungen"

    @classmethod
    def aktuelles(cls) -> "Einstellungen":
        """Einzige Zeile lesen oder anlegen (Singleton)."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs) -> None:
        # Singleton: pk immer 1
        if self.pk is None:
            self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Einstellungen (pk={self.pk})"


class Zaehlerstand(models.Model):
    """F-101 (M7 Teil 2): Zählerstand des Tageslaufs.

    Ein Eintrag je Stichtag. Das Delta einer Kennzahl ist die
    Differenz zum Vortag; ohne Vortag fehlt das Delta (TESTSCHNITTSTELLE 4).
    """

    stichtag = models.DateField("Stichtag", unique=True)
    kennzahlen = models.JSONField(
        "Kennzahlen (Werte je Kennzahl)", default=dict, blank=True
    )
    erzeugt_am = models.DateTimeField("Erzeugt am", null=True, blank=True)

    class Meta:
        verbose_name = "Zählerstand"
        verbose_name_plural = "Zählerstände"
        ordering = ["-stichtag"]

    def __str__(self) -> str:
        return f"Zählerstand {self.stichtag:%d.%m.%Y}"


class Mailversand(models.Model):
    """F-96 / M7 Teil 2: Versand-Log für den Tageslauf.

    Ein Eintrag je Stichtag + Mailtyp. Damit verschickt ein zweiter
    Lauf für denselben Stichtag nichts doppelt.
    """

    MAILTYP_F91 = "f91_leihe_endet_morgen"
    MAILTYP_F92 = "f92_leihe_ueberfaellig"
    MAILTYP_F94 = "f94_garantie_sammelmail"
    MAILTYP_F95 = "f95_unterzeichen_sammelmail"
    MAILTYP_F140 = "f140_gegenzeichnung_erinnerung"

    stichtag = models.DateField("Stichtag")
    mailtyp = models.CharField("Mailtyp", max_length=48)
    anzahl = models.PositiveIntegerField("Anzahl Mails", default=0)
    erzeugt_am = models.DateTimeField("Erzeugt am", null=True, blank=True)

    class Meta:
        verbose_name = "Mailversand"
        verbose_name_plural = "Mailversände"
        constraints = [
            models.UniqueConstraint(
                fields=["stichtag", "mailtyp"],
                name="unique_stichtag_mailtyp",
            )
        ]

    def __str__(self) -> str:
        return f"Mailversand {self.stichtag:%d.%m.%Y} {self.mailtyp} ({self.anzahl})"


class Ausstattungsprofil(models.Model):
    """Ausstattungsprofil (F-61, Kapitel 3.2).

    Beispiel „Standard“: 2 × Monitor, 1 × Dockingstation, 1 × Tastatur, 1 × Maus, 1 × Headset.
    """

    name = models.CharField("Name", max_length=120, unique=True)

    class Meta:
        verbose_name = "Ausstattungsprofil"
        verbose_name_plural = "Ausstattungsprofile"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Profilposition(models.Model):
    """Eine Position im Ausstattungsprofil: Kategorie und Anzahl (F-61)."""

    profil = models.ForeignKey(
        Ausstattungsprofil,
        on_delete=models.CASCADE,
        related_name="positionen",
    )
    kategorie = models.ForeignKey(
        Kategorie,
        on_delete=models.PROTECT,
        related_name="profilpositionen",
    )
    anzahl = models.PositiveIntegerField("Anzahl", default=1)

    class Meta:
        verbose_name = "Profilposition"
        verbose_name_plural = "Profilpositionen"
        unique_together = [("profil", "kategorie")]

    def __str__(self):
        return f"{self.profil.name}: {self.anzahl} × {self.kategorie.name}"
