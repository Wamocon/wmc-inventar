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
    email = models.EmailField("E-Mail", unique=True)
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
