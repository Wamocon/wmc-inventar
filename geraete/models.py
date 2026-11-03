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
    # M5: Reserviert (F-20, Kapitel 4) – bleibt „Auf Lager" mit Zusatz „reserviert"
    reserviert = models.BooleanField("Reserviert", default=False)
    reserviert_von = models.ForeignKey(
        "stammdaten.Person", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reservierte_geraete", verbose_name="Reserviert von",
    )
    reserviert_bis = models.DateField("Reserviert bis", null=True, blank=True)

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
    # A-0097: Ziel des Abschließens („bisherige Zuordnung“ oder „Lager“), F-42.
    reparatur_ziel = models.CharField("Reparaturziel", max_length=32, blank=True, default="")
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


# --- M5 Verleih (Kapitel 3.2, F-30, F-36, F-133) ------------------------------

class Protokoll(models.Model):
    """Ein Ausgabeprotokoll (F-21, F-22, F-130, F-133).

    Stand: scan-offen (F-22, M3), danach abgeschlossen (M6/M7).
    Nummer: UP-JJJJ-NNNN (F-131).
    """

    STAND_SCAN_OFFEN = "scan-offen"
    STAND_ABGESCHLOSSEN = "abgeschlossen"
    # A-0125 M6 Teil 2: Stände für die Signatur-Kette (F-135, F-136).
    STAND_BEARBEITER_OFFEN = "bearbeiter-offen"
    STAND_GEGENZEICHNUNG_OFFEN = "gegenzeichnung-offen"
    STAENDE = [
        (STAND_SCAN_OFFEN, "Unterschrift offen: Scan fehlt"),
        (STAND_BEARBEITER_OFFEN, "Bearbeiter-Signatur offen (F-135)"),
        (STAND_GEGENZEICHNUNG_OFFEN, "Gegenzeichnung offen (F-136)"),
        (STAND_ABGESCHLOSSEN, "Abgeschlossen"),
    ]

    nr = models.CharField("Protokollnummer", max_length=24, blank=True, default="")
    person = models.ForeignKey(
        "stammdaten.Person", on_delete=models.CASCADE,
        related_name="protokolle", verbose_name="Person",
    )
    geraet = models.ForeignKey(
        Gerat, on_delete=models.CASCADE, related_name="protokolle"
    )
    datum = models.DateField("Datum")
    stand = models.CharField("Stand", max_length=24, choices=STAENDE,
                             default=STAND_SCAN_OFFEN)
    erzeugt_von = models.ForeignKey(
        "konten.Konto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="erzeugte_protokolle", verbose_name="Erzeugt von",
    )
    fotos = models.PositiveIntegerField("Fotos", default=0)

    # --- A-0123 M6 Teil 1: Wortlaut der Vorlage (F-130, F-132, F-133, F-134, F-22) ---
    ART_AUSGABE = "ausgabe"
    ART_RUECKNAHME = "ruecknahme"
    ARTEN = [
        (ART_AUSGABE, "Ausgabe (FRM-001)"),
        (ART_RUECKNAHME, "Rücknahme (FRM-002)"),
    ]
    art = models.CharField(
        "Art", max_length=16, choices=ARTEN, default=ART_AUSGABE
    )
    fassung = models.CharField("Fassung", max_length=8, default="1.0")
    formularnummer = models.CharField(
        "Formularnummer (Fußzeile)", max_length=24, default="FRM-001"
    )
    absenderzeile = models.CharField(
        "Absenderzeile", max_length=240, default="Wamocon GmbH · IT"
    )
    empfaenger_anschrift = models.TextField(
        "Empfängeranschrift (Briefkopf)", blank=True, default=""
    )
    bearbeiter = models.CharField(
        "Bearbeiter", max_length=120, blank=True, default=""
    )
    # F-132: Checkliste Zugänge, sechs Punkte, ja/nein (1/0).
    # Das PDF entsteht erst, wenn jeder Punkt beantwortet ist.
    checkliste = models.JSONField(
        "Checkliste Zugänge", default=dict, blank=True
    )

    # --- A-0125 M6 Teil 2: Signatur, Gegenzeichnung (F-135, F-136, F-137, F-141) ---
    # F-135: Signatur des Bearbeiters (Passwort, Zeitpunkt, IP).
    bearbeiter_signatur = models.CharField(
        "Bearbeiter-Signatur (Passwort-Code)", max_length=6, blank=True, default=""
    )
    bearbeiter_signiert_am = models.DateTimeField(
        "Bearbeiter signierte am", null=True, blank=True
    )
    bearbeiter_signiert_von = models.ForeignKey(
        "konten.Konto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="protokolle_signiert", verbose_name="Bearbeiter signiert von",
    )
    bearbeiter_ip = models.CharField(
        "Bearbeiter IP-Adresse", max_length=45, blank=True, default=""
    )
    # F-136: Gegenzeichnung per Mail-Link (Token, 14 Tage gültig).
    gegenzeichnung_token = models.CharField(
        "Gegenzeichnung-Token", max_length=64, blank=True, default=""
    )
    gegenzeichnung_token_erstellt = models.DateTimeField(
        "Token erstellt am", null=True, blank=True
    )
    gegenzeichnung_empfaenger = models.CharField(
        "Gegenzeichnung-Empfänger (E-Mail)", max_length=254, blank=True, default=""
    )
    gegenzeichnung_signiert_am = models.DateTimeField(
        "Gegenzeichnung signierte am", null=True, blank=True
    )
    gegenzeichnung_ip = models.CharField(
        "Gegenzeichnung IP-Adresse", max_length=45, blank=True, default=""
    )
    # F-141: Rücknahme – Geräte sofort im Lager, aber Protokoll erst mit
    # Gegenzeichnung abgeschlossen.
    ruecknahme_geraet_im_lager = models.BooleanField(
        "Gerät sofort im Lager (F-141)", default=False
    )
    # F-137: Hashwert des PDFs zum Zeitpunkt der Signatur.
    pdf_hash_bearbeiter = models.CharField(
        "PDF-Hash (Bearbeiter-Signatur)", max_length=128, blank=True, default=""
    )
    pdf_hash_gegenzeichnung = models.CharField(
        "PDF-Hash (Gegenzeichnung)", max_length=128, blank=True, default=""
    )
    # F-135: Korrekturen erzeugen eine neue Fassung mit neuer Nummer.
    korrigiert_zu_protokoll = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="korrekturen", verbose_name="Korrigiert zu Protokoll",
    )
    ist_korrektur = models.BooleanField(
        "Ist Korrektur (neue Fassung)", default=False
    )
    # F-133: Prüfpunkte IT-Offboarding, 13 Punkte, nur bei Rücknahme.
    offboarding = models.JSONField(
        "Prüfpunkte IT-Offboarding", default=dict, blank=True
    )
    # F-22: hochgeladener Scan des unterzeichneten Protokolls.
    scan_datei = models.FileField(
        "Scan des Protokolls",
        upload_to="protokolle/scans/",
        blank=True,
        default="",
    )
    scan_am = models.DateTimeField("Scan hochgeladen am", null=True, blank=True)
    scan_von = models.ForeignKey(
        "konten.Konto",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scans_hochgeladen",
        verbose_name="Scan hochgeladen von",
    )
    # F-134: Fotos je Gerät bei Ausgabe und Rücknahme, verkleinert als
    # Anlage hinter dem Protokoll. Jeder Eintrag: {"pfad": str, "name": str,
    # "groesse": int, "hochgeladen_am": str}
    anhaenge = models.JSONField("Anhänge (Fotos)", default=list, blank=True)
    # Rücknahme-FRM-002: Bezug auf das Ausgabeprotokoll (Kapitel 5).
    rueckgabe_zu_protokoll = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rueckgaben",
        verbose_name="Rücknahme zu Protokoll",
    )
    # --- A-0126 M6 Teil 3: Siegel (PAdES) und Versand (F-138, F-139, F-140) ---
    # F-138: Versiegeltes PDF (PAdES mit pyhanko), nach der Gegenzeichnung.
    pdf_siegel = models.BinaryField(
        "Versiegeltes PDF (PAdES)", null=True, blank=True,
    )
    # F-139: Dateiname nach F-139 (WMC_Ausgabeprotokoll_Nachname_Vorname_TT.MM.JJJJ.pdf).
    pdf_dateiname = models.CharField(
        "PDF-Dateiname (F-139)", max_length=256, blank=True, default=""
    )
    # F-140: Link neu gesendet (Zeitpunkt der letzten Neusendung).
    link_neu_gesendet_am = models.DateTimeField(
        "Link neu gesendet am (F-140)", null=True, blank=True
    )

    class Meta:
        verbose_name = "Protokoll"
        verbose_name_plural = "Protokolle"
        ordering = ["-datum"]

    def __str__(self):
        return f"Protokoll {self.nr or self.pk}: {self.person.nachname}"

    @property
    def stand_anzeige(self) -> str:
        return dict(self.STAENDE).get(self.stand, self.stand) or self.stand

    @property
    def stand_class(self) -> str:
        """CSS-Klasse für die Statusanzeige (Kapitel 4: data-stand)."""
        return "stand-ok" if self.stand == self.STAND_ABGESCHLOSSEN else "stand-offen"

    @property
    def art_anzeige(self) -> str:
        return dict(self.ARTEN).get(self.art, self.art) or self.art

    # --- A-0125 M6 Teil 2: Signatur-Status (F-135, F-136, F-141) ---------------
    @property
    def ist_signiert(self) -> bool:
        """F-135/F-136: True, wenn Bearbeiter und Gegenzeichnung vorliegen."""
        return (
            self.bearbeiter_signiert_am is not None
            and self.gegenzeichnung_signiert_am is not None
        )

    @property
    def ist_gesperrt(self) -> bool:
        """F-135: Inhalt gesperrt, wenn Bearbeiter signiert hat."""
        return self.bearbeiter_signiert_am is not None

    @property
    def gegenzeichnung_abgelaufen(self) -> bool:
        """F-136: Token abgelaufen nach 14 Tagen (TESTSCHNITTSTELLE 3)."""
        from datetime import timedelta
        from konten.zeit import jetzt_wie_im_entwicklungsmodus
        if self.gegenzeichnung_token_erstellt is None:
            return False
        return (
            jetzt_wie_im_entwicklungsmodus()
            - self.gegenzeichnung_token_erstellt
            > timedelta(days=14)
        )

    def aufzeichnungen_liste(self) -> list:
        """F-137: Signatur-Aufzeichnungen, chronologisch."""
        return list(self.aufzeichnungen.order_by("zeitpunkt"))

    def aktiver_code(self):
        """F-136: Der aktuell gültigste Code, falls vorhanden."""
        from .models import SignaturCode
        return SignaturCode.objects.filter(
            protokoll=self, gueltig=True
        ).order_by("-erstellt_am").first()

    # --- F-132: Checkliste Zugänge (sechs Punkte) ------------------------------
    # Wortlaut aus docs/vorlagen/FRM-001.md Abschnitt 3, Vorbelegung
    # (F-132). Reihenfolge und Bezeichnung sind fest.
    CHECKLISTE_PUNKTE = (
        ("m365", "Benutzerkonto Microsoft 365, Erstkennwort persönlich übergeben"),
        ("mfa", "Mehrfaktor-Authentifizierung eingerichtet"),
        ("passwortmanager", "Zugang Passwortmanager"),
        ("vpn", "VPN-Zugang, Zertifikat oder Schlüssel"),
        ("projektsysteme", "Zugriff Confluence, Jira und weitere Projektsysteme"),
        ("zugangskarte", "Zugangskarte, Schlüssel, Transponder"),
        # TODO: A-0126 (M6 Teil 3) ersetzt die letzten zwei Punkte durch
        # „Zugänge entzogen" und „Daten gelöscht".
    )

    def checkliste_unbeantwortet(self) -> list[str]:
        """F-132: Punkte, die noch nicht ja/nein beantwortet sind."""
        werte = self.checkliste or {}
        offene = []
        for schluessel, _text in self.CHECKLISTE_PUNKTE:
            if werte.get(schluessel) not in (0, 1):
                offene.append(schluessel)
        return offene

    # --- F-133: Prüfpunkte IT-Offboarding (13 Punkte) --------------------------
    # Wortlaut aus docs/vorlagen/FRM-002.md Abschnitt 3, Vorbelegung
    # (F-133). Reihenfolge und Bezeichnung sind fest.
    OFFBOARDING_PUNKTE = (
        ("werkseinstellung", "Gerät auf Werkseinstellungen zurückgesetzt, Datenträger sicher gelöscht"),
        ("daten_gesichert", "Lokale Daten des Nutzers gesichert oder zur Löschung freigegeben"),
        ("geraeteverwaltung", "Gerät aus der Geräteverwaltung und aus dem Inventar ausgetragen"),
        ("benutzerkonten", "Benutzerkonten deaktiviert (Microsoft 365, Confluence, Jira, weitere)"),
        ("mfa_entkoppelt", "Mehrfaktor-Authentifizierung und Authenticator vom Gerät entkoppelt"),
        ("ssh_api", "SSH-Schlüssel und API-Token widerrufen"),
        ("vpn_zertifikate", "VPN-Zugang und Zertifikate widerrufen"),
        ("passwortmanager", "Zugriffe im Passwortmanager entzogen"),
        ("gemeinsame_kennworter", "Gemeinsam genutzte Kennwörter geändert"),
        ("softwarelizenzen", "Softwarelizenzen zurückgeführt oder neu zugewiesen (Microsoft 365)"),
        ("zugangskarte", "Zugangskarte, Schlüssel und Transponder zurückgegeben"),
        ("private_geraete", "Geschäftliche Daten von privaten Geräten und Cloud-Speichern entfernt"),
        ("inventar_dokumentiert", "Rückgabe im Hardware-Inventar dokumentiert"),
        # TODO: A-0126 (M6 Teil 3) ersetzt die letzten zwei Punkte durch
        # „Backup" und „Archiv" mit geprüften Namen.
    )

    def offboarding_unbeantwortet(self) -> list[str]:
        """F-133: Prüfpunkte, die noch nicht abgehackt sind."""
        werte = self.offboarding or {}
        return [
            schluessel
            for schluessel, _text in self.OFFBOARDING_PUNKTE
            if not werte.get(schluessel)
        ]

    def anhaenge_liste(self) -> list[dict]:
        return list(self.anhaenge or [])


class Leihe(models.Model):
    """Eine Leihe eines Geräts an eine Person (Kapitel 3.2, F-30, F-36).

    Stände: ausgegeben, zurueckgegeben, ueberfaellig (F-36).
    Genehmigt: Reservierung – das Gerät bleibt „Auf Lager" mit dem
    Zusatz „reserviert" (F-20, Kapitel 4). Genehmigt wird erst in Teil 2.
    """
    STATUS_ANGEFRAGT = "angefragt"
    STATUS_GENEHMIGT = "genehmigt"
    STATUS_ABGELEHNT = "abgelehnt"
    STATUS_AUSGEGEBEN = "ausgegeben"
    STATUS_ZURUECKGEGEBEN = "zurueckgegeben"
    STATUS_ZURUECKGEZOGEN = "zurueckgezogen"
    STATUSES = [
        (STATUS_ANGEFRAGT, "angefragt"),
        (STATUS_GENEHMIGT, "genehmigt"),
        (STATUS_ABGELEHNT, "abgelehnt"),
        (STATUS_AUSGEGEBEN, "ausgegeben"),
        (STATUS_ZURUECKGEGEBEN, "zurückgegeben"),
        (STATUS_ZURUECKGEZOGEN, "zurückgezogen"),
    ]
    # A-0118: Anzeigetext des Stands für die Leihliste (TESTSCHNITTSTELLE 5).
    STAND_ANZEIGE = {
        STATUS_ANGEFRAGT: "angefragt",
        STATUS_GENEHMIGT: "genehmigt",
        STATUS_ABGELEHNT: "abgelehnt",
        STATUS_AUSGEGEBEN: "ausgegeben",
        STATUS_ZURUECKGEGEBEN: "zurückgegeben",
        STATUS_ZURUECKGEZOGEN: "zurückgezogen",
    }
    # A-0118 (F-37): Aus diesen Zuständen darf die Leihe zurückgezogen werden.
    ZURUECKZIEHBAR = (STATUS_ANGEFRAGT, STATUS_GENEHMIGT)

    @property
    def stand_anzeige(self) -> str:
        """Anzeigetext des Stands (TESTSCHNITTSTELLE 5).

        Eine ausgegebene Leihe zeigt nach Ablauf der Frist „überfällig“
        (F-36), sonst den Stand.
        """
        if self.status == self.STATUS_AUSGEGEBEN and getattr(self, "ueberfaellig", False):
            return "überfällig"
        return self.STAND_ANZEIGE.get(self.status, self.status)

    def ist_zurueckziehbar(self) -> bool:
        """F-37: Rückziehbar, solange die Leihe nicht ausgegeben ist."""
        return self.status in self.ZURUECKZIEHBAR

    nr = models.CharField("Leihnummer", max_length=16, blank=True, default="")
    gerat = models.ForeignKey(
        Gerat, on_delete=models.CASCADE, null=True, blank=True,
        related_name="leihen",
    )
    person = models.ForeignKey(
        "stammdaten.Person", on_delete=models.CASCADE,
        related_name="leihen", verbose_name="Person",
    )
    kat = models.ForeignKey(
        "stammdaten.Kategorie", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="leihen", verbose_name="Kategorie",
    )
    beginn = models.DateField("Leihbeginn", null=True, blank=True)
    ende = models.DateField("Leihende", null=True, blank=True)
    rueckgabe_bis = models.DateField("Rückgabe bis", null=True, blank=True)
    zweck = models.CharField("Zweck", max_length=240, blank=True, default="")
    status = models.CharField("Status", max_length=24, choices=STATUSES,
                              default=STATUS_AUSGEGEBEN)
    genehmigt = models.BooleanField("Genehmigt (Reservierung)", default=False)
    abgelehnt = models.BooleanField("Abgelehnt", default=False)
    abgelehnt_bis = models.CharField("Ablehnungsbegründung", max_length=240, blank=True, default="")
    abgelehnt_von = models.ForeignKey(
        "konten.Konto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="abgelehnte_leihen", verbose_name="Abgelehnt von",
    )
    decided_at = models.DateTimeField("Entschieden am", null=True, blank=True)
    zeitpunkt = models.DateTimeField("Zeitpunkt", default=timezone.now)
    erzeugt_von = models.ForeignKey(
        "konten.Konto", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="erzeugte_leihen", verbose_name="Erzeugt von",
    )

    class Meta:
        verbose_name = "Leihe"
        verbose_name_plural = "Leihen"
        ordering = ["-zeitpunkt"]

    def __str__(self):
        return f"Leihe {self.gerat.inventarnummer} → {self.person.nachname}"

    def stand_aktuell(self) -> str:
        """Aktueller Stand: ausgegeben, zurueckgegeben oder ueberfaellig (F-36)."""
        if self.status == self.STATUS_ZURUECKGEGEBEN:
            return "zurueckgegeben"
        if self.rueckgabe_bis is not None:
            from datetime import date
            from konten.zeit import jetzt_wie_im_entwicklungsmodus
            return "ueberfaellig" if self.rueckgabe_bis < jetzt_wie_im_entwicklungsmodus().date() else "ausgegeben"
        return "ausgegeben"

    @property
    def status_anzeige(self) -> str:
        """Anzeigetext des Stands für die Leihliste (TESTSCHNITTSTELLE 5)."""
        return self.STAND_ANZEIGE.get(self.status, self.status)

    @property
    def status_class(self) -> str:
        """CSS-Klasse für den Status-Pill in der Leihliste."""
        mapping = {
            self.STATUS_ANGEFRAGT: "warn",
            self.STATUS_GENEHMIGT: "ok",
            self.STATUS_ABGELEHNT: "err",
            self.STATUS_AUSGEGEBEN: "ok",
            self.STATUS_ZURUECKGEGEBEN: "muted",
            self.STATUS_ZURUECKGEZOGEN: "muted",
        }
        return mapping.get(self.status, "muted")


# --- A-0125 M6 Teil 2: Signatur und Gegenzeichnung (F-135, F-136, F-137) ------

class SignaturCode(models.Model):
    """Einmalcode für die Gegenzeichnung (F-136).

    6 Stellen, 10 Minuten gültig, höchstens 5 Versuche.
    Zähler in der Datenbank (N-05).
    """
    protokoll = models.ForeignKey(
        Protokoll, on_delete=models.CASCADE, related_name="codes"
    )
    code = models.CharField("Code", max_length=6, unique=True)
    erstellt_am = models.DateTimeField("Erstellt am", default=timezone.now)
    gueltig_bis = models.DateTimeField("Gültig bis")
    versucht_anzahl = models.PositiveIntegerField("Versucht (Anzahl)", default=0)
    gueltig = models.BooleanField("Gültig", default=True)
    verifiziert_am = models.DateTimeField(
        "Verifiziert am", null=True, blank=True
    )
    verifiziert_von_ip = models.CharField(
        "Verifiziert von IP", max_length=45, blank=True, default=""
    )

    class Meta:
        verbose_name = "Einmalcode"
        verbose_name_plural = "Einmalcodes"
        ordering = ["-erstellt_am"]

    def __str__(self):
        return f"Code für Protokoll {self.protokoll_id}: {self.code[:2]}… ({self.gueltig})"

    def ist_gueltig(self) -> bool:
        """F-136: Code gültig, wenn noch in der Gültigkeitszeit und < 5 Versuche."""
        from konten.zeit import jetzt_wie_im_entwicklungsmodus
        if not self.gueltig:
            return False
        if self.verifiziert_am is not None:
            return False
        if self.versucht_anzahl >= 5:
            return False
        return jetzt_wie_im_entwicklungsmodus() < self.gueltig_bis

    def ist_gesperrt(self) -> bool:
        """F-136/N-05: Nach 5 Fehlversuchen ist der Code endgültig gesperrt."""
        return self.versucht_anzahl >= 5


class SignaturAufzeichnung(models.Model):
    """Prüfprotokoll: Name, E-Mail, Zeitpunkt, Nachweisnummer,
    Identifizierungsmerkmal, IP-Adresse, Hashwert (F-137).

    Wird als letzte Seite an das PDF angehängt.
    """
    KIND_BEARBEITER = "bearbeiter"
    KIND_GEGENZEICHNUNG = "gegenzeichnung"
    ARTEN = [
        (KIND_BEARBEITER, "Bearbeiter-Signatur"),
        (KIND_GEGENZEICHNUNG, "Gegenzeichnung"),
    ]
    protokoll = models.ForeignKey(
        Protokoll, on_delete=models.CASCADE, related_name="aufzeichnungen"
    )
    art = models.CharField("Art", max_length=24, choices=ARTEN)
    name = models.CharField("Name", max_length=120)
    email = models.CharField("E-Mail", max_length=254)
    zeitpunkt = models.DateTimeField("Zeitpunkt")
    nachweisnummer = models.CharField(
        "Nachweisnummer", max_length=24, blank=True, default=""
    )
    identifikationsmerkmal = models.CharField(
        "Identifizierungsmerkmal", max_length=240, blank=True, default=""
    )
    ip_adresse = models.CharField("IP-Adresse", max_length=45, blank=True, default="")
    hashwert = models.CharField("Hashwert", max_length=128, blank=True, default="")

    class Meta:
        verbose_name = "Signatur-Aufzeichnung"
        verbose_name_plural = "Signatur-Aufzeichnungen"
        ordering = ["-zeitpunkt"]

    def __str__(self):
        return f"{self.art_anzeige}: {self.name} ({self.zeitpunkt:%d.%m.%Y %H:%M})"

    @property
    def art_anzeige(self) -> str:
        return dict(self.ARTEN).get(self.art, self.art) or self.art
