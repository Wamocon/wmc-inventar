"""Formulare für Geräte (M2 Bestand).

F-11, F-13 (Pflichtfelder), F-14 (Seriennummer je Kategorie),
F-15 (Bearbeiten), F-20 bis F-23 (Ausgabe), F-41 (Umzug), F-42 (Reparatur),
F-50 bis F-53 (Rückgabe, Austritt), F-55 bis F-58 (Ausmusterung, Archiv).
Validierung über die Service-Schicht (Fehlermeldung aus services.GeratFehler).
"""
from __future__ import annotations

from django import forms

from stammdaten.models import Kategorie, Person

from . import services
from .models import Gerat, Leihe

STATUS_WAHL = [
    ("", "Status wählen …"),
    (Gerat.STATUS_AUF_LAGER, "Auf Lager"),
    (Gerat.STATUS_IN_BENUTZUNG, "In Benutzung"),
    (Gerat.STATUS_IN_REPARATUR, "In Reparatur"),
    (Gerat.STATUS_AUSGEMUSTERT, "Ausgemustert"),
]


class GeratForm(forms.ModelForm):
    """Neues Gerät (F-11 bis F-14) oder bestehendes (F-15).

    A-0112 (F-11): Das zusätzliche Feld ``seriennummern`` trägt zeilenweise
    Seriennummern. Es entsteht je Zeile ein Gerät. Fehlt das Feld oder ist
    es leer, greift das Einzel-Feld ``seriennummer``.
    A-0112 (F-13): Die Stammdaten werden per ``?vorlage=`` vorbelegt;
    die Seriennummer bleibt leer.
    """

    status = forms.CharField(
        required=False,
        widget=forms.Select(choices=STATUS_WAHL),
        label="Status",
    )
    person = forms.ModelChoiceField(
        queryset=Person.objects.all(),
        required=False,
        label="Zuweisende Person",
        widget=forms.Select(attrs={"data-test": "person-wahl"}),
        help_text="Person aus dem Verzeichnis oder später beim Verliehen.",
    )
    # F-11 (A-0112): zeilenweise Seriennummern für die Mehrfacherfassung.
    seriennummern = forms.CharField(
        required=False,
        label="Seriennummern (eine pro Zeile)",
        widget=forms.Textarea(
            attrs={"rows": 4, "data-test": "seriennummern"},
        ),
        help_text="Eine Seriennummer pro Zeile. Leere Zeilen werden verworfen.",
    )
    # F-12: "Speichern und Etikett drucken" — kein Formularfeld, sondern
    # ein Button im Formular, der im POST als data-Button durchkommt.
    # Wir prüfen den Button-Namen im View.


    class Meta:
        model = Gerat
        fields = [
            "kategorie", "hersteller", "modell", "seriennummer",
            "zustand", "leihpool", "person", "ort", "geraetename",
            "standardzuehoer", "technische_daten",
            "kaufdatum", "kaufpreis_netto", "lieferant", "rechnungsnummer",
            "garantie_bis", "notiz",
        ]
        widgets = {
            "kategorie": forms.Select,
            "zustand": forms.Select,
            "standardzuehoer": forms.Textarea(attrs={"rows": 3}),
            "technische_daten": forms.Textarea(attrs={"rows": 4}),
            "notiz": forms.Textarea(attrs={"rows": 3}),
            "kaufpreis_netto": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kategorie"].label = "Kategorie"
        self.fields["zustand"].label = "Zustand"
        self.fields["leihpool"].label = "Leihpool"
        self.fields["person"].label = "Zuweisende Person (optional)"
        self.fields["ort"].label = "Ort (optional)"
        if not kwargs.get("instance", None):
            self.fields["status"].widget.attrs.pop("data-ke-status", None)
        else:
            # A-0112 (F-11): Das Feld seriennummern gilt nur fürs Anlegen.
            del self.fields["seriennummern"]

    def clean(self) -> dict:
        daten = super().clean()
        kategorie = daten.get("kategorie")
        seriennummer = (daten.get("seriennummer") or "").strip()
        # F-11 (A-0112): Das Textfeld seriennummern trägt zeilenweise Werte.
        # Wenn es ausgefüllt ist, genügt das (Seriennummer pro Gerät).
        seriennummern_ruh = (daten.get("seriennummern") or "").strip()
        hat_seriennummern = bool(seriennummern_ruh)
        # F-14: Seriennummer nur Pflicht, wenn die Kategorie es verlangt
        # und keine zeilenweise Liste vorliegt.
        if (
            kategorie is not None
            and kategorie.seriennummer_pflicht
            and not seriennummer
            and not hat_seriennummern
        ):
            self.add_error(
                "seriennummer", "Diese Kategorie verlangt eine Seriennummer."
            )
        person = daten.get("person")
        ort = daten.get("ort")
        if person and ort and not (self.instance and self.instance.pk):
            # Neu anlegen: Person UND Ort ist kein gültiger Anfangszustand.
            self.add_error(
                None, "Ein Gerät steht bei einer Person oder an einem Ort, nicht beides."
            )
        return daten


class GeratBearbeitungsForm(GeratForm):
    """Ändern eines vorhandenen Geräts (F-15). Inventarnummer bleibt (F-12)."""

    class Meta(GeratForm.Meta):
        # Status nicht per Formular änderbar: Statuswechsel sind Vorgänge
        # (Kapitel 4), hier nur Stammdaten.
        fields = [
            "kategorie", "hersteller", "modell", "seriennummer",
            "zustand", "leihpool", "person", "ort", "geraetename",
            "standardzuehoer", "technische_daten",
            "kaufdatum", "kaufpreis_netto", "lieferant", "rechnungsnummer",
            "garantie_bis", "notiz",
        ]


# --- M3 Lebenszyklus ---------------------------------------------------------

class GeratAusgabeForm(forms.Form):
    """Gerät ausgeben (F-20 bis F-23, F-131).

    A-0098 (F-131): der Dialog trägt je Gerät „Zustand“ (die vier Stufen
    von ``Gerat.ZUSTAENDE``, voreingestellt mit dem Zustand des Geräts),
    „Zubehör komplett“ (Ja, Nein) und „Bemerkung“. Protokoll und Signatur
    bleiben M6, das Protokoll-PDF folgt mit F-130.
    """

    ZUBEOER = [("ja", "Ja"), ("nein", "Nein")]

    ziel_person = forms.ModelChoiceField(
        queryset=Person.objects.all(),
        required=False,
        label="Person",
        widget=forms.Select(attrs={"data-test": "ausgabe-person"}),
    )
    ziel_ort = forms.ModelChoiceField(
        queryset=None,  # Wird in __init__ gesetzt
        required=False,
        label="Arbeitsplatz",
        widget=forms.Select(attrs={"data-test": "ausgabe-ort"}),
    )
    zustand = forms.ChoiceField(
        choices=Gerat.ZUSTAENDE,
        required=True,
        label="Zustand",
        widget=forms.Select(attrs={"data-test": "ausgabe-zustand"}),
    )
    zubehoer_komplett = forms.ChoiceField(
        choices=ZUBEOER,
        required=True,
        initial="ja",
        label="Zubehör komplett",
        widget=forms.Select(attrs={"data-test": "zubehoer-komplett"}),
    )
    anmerkung = forms.CharField(
        required=False,
        label="Bemerkung",
        widget=forms.Textarea(attrs={"rows": 2, "data-test": "anmerkung"}),
    )

    def __init__(self, *args, gerat: Gerat | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        from stammdaten.models import Ort
        self.fields["ziel_ort"].queryset = Ort.objects.all().order_by("kennung")
        if gerat is not None:
            self.fields["zustand"].initial = gerat.zustand

    def clean(self) -> dict:
        daten = super().clean()
        person = daten.get("ziel_person")
        ort = daten.get("ziel_ort")
        if not person and not ort:
            self.add_error(None, "Ziel muss eine Person oder ein Ort sein.")
        return daten


class GeratRueckgabeForm(forms.Form):
    """Gerät zurückgeben (F-50, M3).

    A-0097: „Zubehör komplett“ ist eine Auswahl Ja/Nein (Ja vorbelegt),
    „Danach“ eine Auswahl mit „ins Lager“, „in Reparatur“ und
    „fehlt, Ausmusterung starten“. Das Kästchen „Fehlt“ entfällt.
    """

    ZUBEOER = [("ja", "Ja"), ("nein", "Nein")]
    DANACH = [
        ("lager", "ins Lager"),
        ("reparatur", "in Reparatur"),
        ("fehlend", "fehlt, Ausmusterung starten"),
    ]

    zustand_rueckgabe = forms.ChoiceField(
        choices=Gerat.ZUSTAENDE,
        required=True,
        label="Zustand bei Rückgabe",
        widget=forms.Select(attrs={"data-test": "zustand-rueckgabe"}),
    )
    zubehoer_komplett = forms.ChoiceField(
        choices=ZUBEOER,
        required=True,
        initial="ja",
        label="Zubehör komplett",
        widget=forms.Select(attrs={"data-test": "zubehoer-komplett"}),
    )
    maengel = forms.CharField(
        required=False,
        label="Bemerkung, Mängel",
        widget=forms.Textarea(attrs={"rows": 2, "data-test": "maengel"}),
    )
    ziel = forms.ChoiceField(
        choices=DANACH,
        required=True,
        label="Danach",
        widget=forms.Select(attrs={"data-test": "danach"}),
    )

    def clean(self) -> dict:
        daten = super().clean()
        daten["fehlend"] = daten.get("ziel") == "fehlend"
        return daten


class GeratUmzugForm(forms.Form):
    """Gerät umziehen (F-41, M3)."""

    ziel_ort = forms.ModelChoiceField(
        queryset=None,  # Wird in __init__ gesetzt
        required=True,
        label="Neuer Arbeitsplatz",
        widget=forms.Select(attrs={"data-test": "umzug-ort"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from stammdaten.models import Ort
        self.fields["ziel_ort"].queryset = Ort.objects.all().order_by("kennung")


class GeratReparaturStartForm(forms.Form):
    """Reparatur starten (F-42, M3)."""

    dienstleister = forms.CharField(
        required=True,
        label="Dienstleister",
        widget=forms.TextInput(attrs={"data-test": "dienstleister"}),
    )
    vorgangsnummer = forms.CharField(
        required=True,
        label="Vorgangsnummer",
        widget=forms.TextInput(attrs={"data-test": "vorgangsnummer"}),
    )
    notiz = forms.CharField(
        required=True,
        label="Fehlerbeschreibung",
        widget=forms.Textarea(attrs={"rows": 2, "data-test": "reparatur-notiz"}),
    )


class GeratReparaturFertigForm(forms.Form):
    """Reparatur abschließen (F-42, M3).

    A-0097: „Ziel“ sind zwei Optionsfelder mit eigenen Beschriftungen,
    „Bisherige Zuordnung“ (voreingestellt) und „Ins Lager“.
    """

    ZIEL = [("zuordnung", "Bisherige Zuordnung"), ("lager", "Ins Lager")]

    zustand = forms.ChoiceField(
        choices=Gerat.ZUSTAENDE,
        required=True,
        label="Zustand jetzt",
        widget=forms.Select(attrs={"data-test": "reparatur-zustand"}),
    )
    ziel = forms.ChoiceField(
        choices=ZIEL,
        required=True,
        initial="zuordnung",
        label="Ziel",
        widget=forms.RadioSelect(attrs={"data-test": "reparatur-ziel"}),
    )
    kosten = forms.DecimalField(
        required=False,
        label="Kosten (EUR)",
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0", "data-test": "kosten"}),
    )
    beleg = forms.CharField(
        required=False,
        label="Beleg",
        widget=forms.TextInput(attrs={"data-test": "beleg"}),
    )


class GeratAusmusterungForm(forms.Form):
    """Gerät ausmustern (F-55 bis F-58, M3).

    A-0097 nach dem Prototyp (Dialog „Gerät ausmustern“):
    „Grund“ beginnt mit „Bitte wählen“; „Datum“ ist Pflicht;
    „Verbleib“ ist Pflicht, außer bei verloren/gestohlen;
    bei Verlust/Diebstahl: Bestätigung „Der Vorfall ist an Datenschutz
    bzw. Informationssicherheit gemeldet.“;
    bei Datenträgern und nicht bei Verlust: zwei Optionsfelder für die
    Löschung plus Zertifikats- oder Protokollnummer.
    """

    GRUENDE = [
        ("", "Bitte wählen"),
        ("defekt", "Defekt"),
        ("veraltet", "Veraltet"),
        ("verkauft", "Verkauft"),
        ("verloren", "Verloren"),
        ("gestohlen", "Gestohlen"),
    ]
    LOESCHUNG = [
        ("nist", "Gelöscht durch die IT nach NIST SP 800-88"),
        ("zerstoert", "Physisch zerstört durch Dienstleister"),
    ]
    VERLOREN = ("verloren", "gestohlen")

    def __init__(self, *args, gerat: Gerat | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._datentraeger = bool(gerat and gerat.kategorie and gerat.kategorie.hat_datentraeger)
        self._verloren = False

    grund = forms.ChoiceField(
        choices=GRUENDE,
        required=True,
        error_messages={"required": "Bitte einen Grund wählen."},
        label="Grund",
        widget=forms.Select(attrs={"data-test": "ausmusterung-grund"}),
    )
    datum = forms.DateField(
        required=True,
        label="Datum",
        widget=forms.DateInput(attrs={"type": "date", "data-test": "ausmusterung-datum"}),
    )
    disposition = forms.CharField(
        required=False,
        label="Verbleib",
        widget=forms.TextInput(attrs={"data-test": "ausmusterung-disposition"}),
    )
    loeschung_art = forms.ChoiceField(
        choices=LOESCHUNG,
        required=False,
        label="Datenlöschung",
        error_messages={"required": "Bitte die Art der Löschung wählen."},
        widget=forms.RadioSelect(attrs={"data-test": "loeschung-art"}),
    )
    loeschung_nachweis = forms.CharField(
        required=False,
        label="Zertifikats- oder Protokollnummer",
        widget=forms.TextInput(attrs={"data-test": "loeschung-nachweis"}),
    )
    loeschung_datei = forms.FileField(
        required=False,
        label="Nachweis (Datei hochladen)",
        widget=forms.ClearableFileInput(attrs={"data-test": "loeschung-datei"}),
    )
    bestaetigt_gemeldt = forms.BooleanField(
        required=False,
        label="Der Vorfall ist an Datenschutz bzw. Informationssicherheit gemeldet.",
        widget=forms.CheckboxInput(attrs={"data-test": "bestaetigt-gemeldet"}),
    )

    def clean(self) -> dict:
        daten = super().clean()
        grund = daten.get("grund") or ""
        daten["grund"] = grund
        verloren = grund in self.VERLOREN
        self._verloren = verloren
        # Verbleib: Pflicht außer bei verloren/gestohlen (dort entfällt das Feld).
        if not verloren and not daten.get("disposition"):
            self.add_error("disposition", "Verbleib muss angegeben werden.")
        # Bestätigung: Pflicht bei verloren/gestohlen.
        if verloren and not daten.get("bestaetigt_gemeldt"):
            self.add_error(
                "bestaetigt_gemeldt",
                "Der Vorfall ist an Datenschutz bzw. Informationssicherheit zu melden.",
            )
        # Datenlöschung: Pflicht bei Datenträger und nicht bei Verlust.
        if self._datentraeger and not verloren:
            if not daten.get("loeschung_art"):
                self.add_error("loeschung_art", "Bitte die Art der Löschung wählen.")
            if not daten.get("loeschung_nachweis") and not daten.get("loeschung_datei"):
                self.add_error(
                    "loeschung_nachweis",
                    "Zertifikats- oder Protokollnummer oder Nachweis angeben.",
                )
        return daten


def kategorie_wahl() -> forms.ChoiceField:
    auswahl = [("", "Kategorie wählen …")]
    for k in sorted(Kategorie.objects.all(), key=lambda k: k.name):
        auswahl.append((str(k.pk), k.name))
    return forms.ChoiceField(choices=auswahl, label="Kategorie")


class GeratNotizForm(forms.Form):
    """Notiz am Gerät eintragen (F-74, A-0111 Teil 4).

    Dialog ``data-name="notiz"`` mit ``speichern`` (TESTSCHNITTSTELLE
    Kapitel 4). Die Notiz steht danach am Gerät.
    """

    notiz = forms.CharField(
        required=False,
        label="Notiz",
        widget=forms.Textarea(attrs={"rows": 3, "data-test": "notiz-feld"}),
    )


# --- M5 Verleih (F-30) ---------------------------------------------------------

class VerleihForm(forms.Form):
    """Formular für den Verleih (F-30, TESTSCHNITTSTELLE 4).

    Person, Rückgabe bis (Pflicht), Zweck (Pflicht).
    """

    person = forms.ModelChoiceField(
        label="Person",
        required=True,
        queryset=Person.objects.filter(aktiv=True).order_by("nachname"),
        widget=forms.Select(attrs={"data-test": "person", "class": "req"}),
    )
    rueckgabe_bis = forms.DateField(
        label="Rückgabe bis",
        required=True,
        widget=forms.DateInput(attrs={"data-test": "rueckgabe-bis", "type": "date", "class": "req"}),
    )
    zweck = forms.CharField(
        label="Zweck",
        required=True,
        widget=forms.TextInput(attrs={"data-test": "zweck", "class": "req"}),
    )


# --- M5 Teil 2: Anfrage, Genehmigung, Ablehnung, Zurückziehen (A-0118) ----

class LeiheAnfrageForm(forms.ModelForm):
    """M5 Teil 2 (F-31): Mitarbeiter fragt ein Leihgerät an.

    Kategorie, Zeitraum und Zweck sind Pflicht; das konkrete Gerät ist
    optional und wird mit dem Genehmigen festgelegt (F-32).
    """

    class Meta:
        model = Leihe
        fields = ["kat", "beginn", "ende", "zweck", "gerat"]
        labels = {
            "kat": "Kategorie",
            "beginn": "Leihbeginn",
            "ende": "Leihende",
            "zweck": "Zweck",
            "gerat": "Konkretes Gerät (optional)",
        }
        widgets = {
            "kat": forms.Select(attrs={"data-test": "kategorie"}),
            "beginn": forms.DateInput(attrs={"data-test": "beginn", "type": "date"}),
            "ende": forms.DateInput(attrs={"data-test": "ende", "type": "date"}),
            "zweck": forms.Textarea(attrs={"data-test": "zweck", "rows": 3}),
            "gerat": forms.Select(attrs={"data-test": "gerat"}),
        }

    def __init__(self, *args, leihpool_geraete=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gerat"].required = False
        if leihpool_geraete is not None:
            self.fields["gerat"].queryset = leihpool_geraete
        self.fields["kat"].required = True
        self.fields["beginn"].required = True
        self.fields["ende"].required = True
        self.fields["zweck"].required = True

    def clean(self):
        data = super().clean()
        beginn = data.get("beginn")
        ende = data.get("ende")
        if beginn and ende and beginn > ende:
            self.add_error("ende", "Leihende ist vor dem Leihbeginn.")
        gerat = data.get("gerat")
        kat = data.get("kat")
        if gerat is not None and kat is not None and gerat.kategorie_id != kat.id:
            self.add_error("gerat", "Das Gerät steht nicht in der Kategorie.")
        return data


class LeiheGenehmigenForm(forms.Form):
    """M5 Teil 2 (F-32): IT genehmigt mit Zuweisung eines Leihpool-Geräts."""

    gerat = forms.ModelChoiceField(
        label="Gerät aus dem Leihpool",
        queryset=Gerat.objects.none(),
        widget=forms.Select(attrs={"data-test": "gerat"}),
    )

    def __init__(self, *args, leihpool_geraete=None, **kwargs):
        super().__init__(*args, **kwargs)
        if leihpool_geraete is not None:
            self.fields["gerat"].queryset = leihpool_geraete


class LeiheAblehnenForm(forms.Form):
    """M5 Teil 2 (F-32): IT lehnt mit Pflichtbegründung ab."""

    begruendung = forms.CharField(
        label="Begründung (Pflicht)",
        required=True,
        widget=forms.Textarea(
            attrs={"data-test": "begrundung", "rows": 2}
        ),
    )


class LeiheZurueckziehenForm(forms.Form):
    """M5 Teil 2 (F-37): Mitarbeiter zieht die Leihe zurück."""

    bestätigung = forms.BooleanField(
        label="Zurückziehen bestätigen",
        required=True,
        widget=forms.CheckboxInput(attrs={"data-test": "bestaetigung"}),
    )
