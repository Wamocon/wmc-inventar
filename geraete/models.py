"""Geräte-Modelle.

Kapitel 3.1 der Anforderungen (Datenmodell Gerät),
F-10 bis F-14 (Aufnahme), F-40 bis F-44 (Betrieb, Historie, Suche),
F-80 bis F-89 (Import, Erstinventur).

Statuswechsel laufen nur über die Service-Schicht (AGENTS.md):
eine Funktion je Vorgang, eine Transaktion.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stammdaten.models import Ort


class Gerat(models.Model):
    """Ein Gerät im Bestand (Kapitel 3.1).

    Inventarnummer automatisch, fortlaufend, Format WMC-00001 (O-03),
    danach unveränderlich. Status nur über Vorgänge änderbar (Kapitel 4).
    """

    STATUS_AUF_LAGER = "auf-lager"
    STATUS_IN_BENUTZUNG = "in-benutzung"
    STATUS_VERLIEHEN = "verliehen"
    STATUS_IN_REPARATUR = "in-reparatur"
    STATUS_AUSGEMUSTERT = "ausgemustert"
    STATUSES = [
        (STATUS_AUF_LAGER, "Auf Lager"),
        (STATUS_IN_BENUTZUNG, "In Benutzung"),
        (STATUS_VERLIEHEN, "Verliehen"),
        (STATUS_IN_REPARATUR, "In Reparatur"),
        (STATUS_AUSGEMUSTERT, "Ausgemustert"),
    ]

    ZUSTAND_NEUWERTIG = 1
    ZUSTAND_GUT = 2
    ZUSTAND_SPUREN = 3
    ZUSTAND_EINGESCHRAENKT = 4
    ZUSTAENDE = [
        (ZUSTAND_NEUWERTIG, "1 – neuwertig"),
        (ZUSTAND_GUT, "2 – gut, normale Gebrauchsspuren"),
        (ZUSTAND_SPUREN, "3 – deutliche Spuren, funktionsfähig"),
        (ZUSTAND_EINGESCHRAENKT, "4 – eingeschränkt nutzbar"),
    ]

    inventarnummer = models.CharField("Inventarnummer", max_length=16, unique=True, editable=False)
    kategorie = models.ForeignKey(
        "stammdaten.Kategorie", on_delete=models.PROTECT, related_name="geraete"
    )
    hersteller = models.CharField("Hersteller", max_length=160)
    modell = models.CharField("Modell", max_length=240)
    seriennummer = models.CharField("Seriennummer", max_length=160, blank=True, default="")
    status = models.CharField("Status", max_length=16, choices=STATUSES, default=STATUS_AUF_LAGER)
    zustand = models.PositiveSmallIntegerField("Zustand", default=ZUSTAND_GUT, choices=ZUSTAENDE)
    leihpool = models.BooleanField("Leihpool", default=False)
    person = models.ForeignKey(
        "stammdaten.Person", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="geraete",
    )
    ort = models.ForeignKey(
        "stammdaten.Ort", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="geraete",
    )
    geraetename = models.CharField("Gerätename", max_length=160, blank=True, default="")
    standardzuehoer = models.TextField("Standardzubehör", blank=True, default="")
    technische_daten = models.TextField("Technische Daten", blank=True, default="")
    kaufdatum = models.DateField("Kaufdatum", null=True, blank=True)
    kaufpreis_netto = models.DecimalField("Kaufpreis netto (EUR)", max_digits=12, decimal_places=2, null=True, blank=True)
    lieferant = models.CharField("Lieferant", max_length=160, blank=True, default="")
    rechnungsnummer = models.CharField("Rechnungsnummer", max_length=160, blank=True, default="")
    garantie_bis = models.DateField("Garantie bis", null=True, blank=True)
    notiz = models.TextField("Notiz", blank=True, default="")
    zuletzt_geprueft_am = models.DateTimeField("Zuletzt geprüft am", null=True, blank=True)
    zuletzt_geprueft_von = models.ForeignKey(
        "konten.Konto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="gepruefte_geraete", verbose_name="Zuletzt geprüft von",
    )

    # F-85: Altbestand ohne Protokoll (importiert, noch nicht bewegt)
    altbestand_ohne_protokoll = models.BooleanField(default=False)
    # F-85: Zustand „ungeprüft“ (Import, Stufe 2)
    zustand_ungeprueft = models.BooleanField(default=False)
    # F-88: Kaufdatum bzw. Garantie als „nicht ermittelbar“ markiert
    kaufdatum_nicht_ermittelbar = models.BooleanField(default=False)
    garantie_nicht_ermittelbar = models.BooleanField(default=False)

    erstellt_am = models.DateTimeField("Erstellt am")
    erstellt_von = models.ForeignKey(
        "konten.Konto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="erstellte_geraete", verbose_name="Erstellt von",
    )

    class Meta:
        verbose_name = "Gerät"
        verbose_name_plural = "Geräte"
        ordering = ["inventarnummer"]

    def __str__(self):
        return self.inventarnummer

    # --- M3 Lebenszyklus -----------------------------------------------------

    def vorgaenge(self) -> list["Vorgang"]:
        """Historie: alle Vorgänge des Geräts, neueste zuerst (F-56)."""
        return list(Vorgang.objects.filter(gerat=self).order_by("-zeitpunkt"))

    def offene_vorgaenge(self) -> list["Vorgang"]:
        """Offene Vorgänge (noch nicht abgeschlossen) (F-56)."""
        return [v for v in self.vorgaenge() if not v.abschliesst]

    def letzte_aenderung(self) -> "Vorgang | None":
        """Letzter Vorgang im Gerätedetail (F-56)."""
        v = self.vorgaenge()
        return v[0] if v else None

    def offener_vorgang_von_typ(self, typ: str) -> "Vorgang | None":
        """Offener Vorgang eines bestimmten Typs (F-51, F-53, F-55, F-57)."""
        for v in self.vorgaenge():
            if v.typ == typ and not v.abschliesst:
                return v
        return None

    @property
    def ist_verliehen(self) -> bool:
        return self.status == self.STATUS_VERLIEHEN

    @property
    def ist_in_reparatur(self) -> bool:
        return self.status == self.STATUS_IN_REPARATUR

    @property
    def ist_ausgemustert(self) -> bool:
        return self.status == self.STATUS_AUSGEMUSTERT

    def aktiver_ort(self) -> "Ort | None":
        """Aktueller Verbleib: Ort (F-50, F-56)."""
        return self.ort if self.ort else None

    # --- Status und Anzeige -------------------------------------------------
    @property
    def status_anzeige(self) -> str:
        return dict(self.STATUSES).get(self.status, self.status)

    def status_wert(self) -> str:
        """data-wert für die Oberfläche (TESTSCHNITTSTELLE 5)."""
        return self.status

    # --- F-88: Datenlücken ---------------------------------------------------
    def datenluecken(self) -> list[str]:
        """Fehlende Angaben, die das Gerät auf die Arbeitsliste setzen (F-88)."""
        luecken = []
        if self.kategorie.seriennummer_pflicht and not self.seriennummer:
            luecken.append("seriennummer")
        if not self.kaufdatum and not self.kaufdatum_nicht_ermittelbar:
            luecken.append("kaufdatum")
        if not self.garantie_bis and not self.garantie_nicht_ermittelbar:
            luecken.append("garantie")
        if not self.person and not self.ort:
            luecken.append("verbleib")
        if self.zustand_ungeprueft:
            luecken.append("zustand-ungeprueft")
        return luecken

    def ist_unvollstaendig(self) -> bool:
        return bool(self.datenluecken()) or GeratKonflikt.objects.filter(
            gerat=self, offen=True
        ).exists()

    # --- F-84: Hinweise auf doppelte Namen ----------------------------------
    def doppelte_namen(self) -> list["Gerat"]:
        """Geräte mit gleichem Gerätenamen (Hinweis im Detail, F-84)."""
        if not self.geraetename:
            return []
        return list(
            Gerat.objects.filter(geraetename__iexact=self.geraetename).exclude(pk=self.pk)
        )

    def doppelte_seriennummern(self) -> list["Gerat"]:
        """Geräte mit gleicher Seriennummer (Hinweis im Detail, F-84)."""
        if not self.seriennummer:
            return []
        return list(
            Gerat.objects.filter(
                seriennummer__iexact=self.seriennummer,
                hersteller__iexact=self.hersteller,
            ).exclude(pk=self.pk)
        )


class GeratKonflikt(models.Model):
    """Offener Importkonflikt (F-84, F-86, F-88).

    Abweichende Werte aus dem Import werden nicht überschrieben,
    sondern als Konflikt gemeldet. Wird nur angelegt, nie geändert oder
    gelöscht (außer: offen → False bei Auflösung).
    """

    gerat = models.ForeignKey(Gerat, on_delete=models.CASCADE, related_name="konflikte")
    feld = models.CharField("Feld", max_length=64)
    alter_wert = models.TextField("Alter Wert", blank=True, default="")
    neuer_wert = models.TextField("Neuer Wert", blank=True, default="")
    herkunft = models.CharField("Herkunft (Datei, Blatt, Zeile)", max_length=320, blank=True, default="")
    offen = models.BooleanField("offen", default=True)
    erzeugt_am = models.DateTimeField("Erzeugt am", default=timezone.now)

    class Meta:
        verbose_name = "Importkonflikt"
        verbose_name_plural = "Importkonflikte"
        ordering = ["erzeugt_am"]

    def __str__(self):
        return f"{self.gerat.inventarnummer}: {self.feld}"


class Importlauf(models.Model):
    """Ein Importlauf (F-86, F-87, F-80 bis F-83).

    Nachvollziehbarkeit: jeder importierte Vorgang trägt Dateiname,
    Blatt und Zeile (F-87).
    """

    dateiname = models.CharField("Dateiname", max_length=320)
    blatt = models.CharField("Blatt", max_length=160, blank=True, default="")
    format_art = models.CharField("Format", max_length=16, default="xlsx")
    anzahl_neu = models.PositiveIntegerField("Neu", default=0)
    anzahl_ergaenzt = models.PositiveIntegerField("Ergänzt", default=0)
    anzahl_konflikt = models.PositiveIntegerField("Konflikt", default=0)
    anzahl_uebersprungen = models.PositiveIntegerField("Übersprungen", default=0)
    erzeugt_am = models.DateTimeField("Erzeugt am", default=timezone.now)
    erzeugt_von = models.ForeignKey(
        "konten.Konto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="importlaeufe", verbose_name="Erzeugt von",
    )

    class Meta:
        verbose_name = "Importlauf"
        verbose_name_plural = "Importläufe"
        ordering = ["-erzeugt_am"]

    def __str__(self):
        return f"{self.dateiname} ({self.blatt or '-'})"


# --- M3 Lebenszyklus (Kapitel 3.2, F-50 bis F-58) -----------------------------

class Vorgang(models.Model):
    """Ein Lebenszyklus-Ereignis eines Geräts (Kapitel 3.2).

    Ein Vorgang ist eine Zeile in der Historie: Leihen, Rückgabe,
    Reparatur, Instandhaltung, Ausmusterung, Rückstellung, Umzug
    (F-50 bis F-58). Ein Vorgang ist abgeschlossen, wenn ``abschliesst``
    gesetzt ist; sonst ist er offen und der dazugehörige Status ist aktiv.
    """

    TYP_AUFNAHME = "aufnahme"
    TYP_IMPORT = "import"
    TYP_AUSGABE = "ausgabe"
    TYP_RUECKGABE = "rueckgabe"
    TYP_REPARATUR = "reparatur"
    TYP_AUSMUSTERUNG = "ausmusterung"
    TYP_UMZUG = "umzug"
    TYP_AENDERUNG = "aenderung"
    TYPEN = [
        (TYP_AUFNAHME, "Aufnahme"),
        (TYP_IMPORT, "Import"),
        (TYP_AUSGABE, "Ausgabe"),
        (TYP_RUECKGABE, "Rückgabe"),
        (TYP_REPARATUR, "Reparatur"),
        (TYP_AUSMUSTERUNG, "Ausmusterung"),
        (TYP_UMZUG, "Umzug"),
        (TYP_AENDERUNG, "Änderung"),
    ]

    gerat = models.ForeignKey(
        Gerat, on_delete=models.CASCADE, related_name="vorgaenge"
    )
    typ = models.CharField("Typ", max_length=24, choices=TYPEN)
    zeitpunkt = models.DateTimeField("Zeitpunkt", default=timezone.now)
    erzeugt_von = models.ForeignKey(
        "konten.Konto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="erzeugte_vorgaenge", verbose_name="Erzeugt von",
    )
    # --- Leihen (F-50, F-51, F-57) -------------------------------------------
    leihgabe_an = models.ForeignKey(
        "stammdaten.Person", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="geliehene_geraete", verbose_name="Leihgabe an",
    )
    zurueck_am = models.DateField("Zurück am", null=True, blank=True)
    # --- Reparatur (F-53, F-56) ----------------------------------------------
    reperatur_anleitung = models.TextField("Reparaturanleitung", blank=True, default="")
    reparatur_kosten = models.DecimalField(
        "Reparaturkosten (EUR)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    reparatur_beleg = models.CharField("Reparaturbeleg", max_length=320, blank=True, default="")
    # --- Instandhaltung (F-54, F-56) ------------------------------------------
    instandhaltung_art = models.CharField("Art", max_length=240, blank=True, default="")
    instandhaltung_kosten = models.DecimalField(
        "Kosten (EUR)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    # --- Ausmusterung (F-58) --------------------------------------------------
    ausmusterung_grund = models.CharField("Grund", max_length=240, blank=True, default="")
    ausmusterung_datum = models.DateField("Datum", null=True, blank=True)
    ausmusterung_disposition = models.CharField("Disposition", max_length=240, blank=True, default="")
    # --- Rückstellung (F-57) --------------------------------------------------
    rueckstellung_zu = models.CharField("Rückstellung zu", max_length=160, blank=True, default="")
    # --- Umzug (F-52) ---------------------------------------------------------
    umzug_ziel_ort = models.ForeignKey(
        "stammdaten.Ort", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="umzugsziele", verbose_name="Zielort",
    )
    # --- Änderung (F-43, F-44) -------------------------------------------------
    aenderung_feld = models.CharField("Feld", max_length=64, blank=True, default="")
    aenderung_alter_wert = models.TextField("Alter Wert", blank=True, default="")
    aenderung_neuer_wert = models.TextField("Neuer Wert", blank=True, default="")
    # --- Abschließend ---------------------------------------------------------
    abschliesst = models.BooleanField("Abschließend", default=False)
    notiz = models.TextField("Notiz", blank=True, default="")

    class Meta:
        verbose_name = "Vorgang"
        verbose_name_plural = "Vorgänge"
        ordering = ["-zeitpunkt"]

    def __str__(self):
        return f"{self.gerat.inventarnummer}: {dict(self.TYPEN).get(self.typ, self.typ)}"

    @property
    def ist_offen(self) -> bool:
        return not self.abschliesst
