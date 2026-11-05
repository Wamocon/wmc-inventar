"""Formulare für Geräte (M2 Bestand).

F-11, F-13 (Pflichtfelder), F-14 (Seriennummer je Kategorie),
F-15 (Bearbeiten), F-20 bis F-23 (Ausgabe), F-41 (Umzug), F-42 (Reparatur),
F-50 bis F-53 (Rückgabe, Austritt), F-55 bis F-58 (Ausmusterung, Archiv).
Validierung über die Service-Schicht (Fehlermeldung aus services.GeratFehler).
"""
from __future__ import annotations

from django import forms

from konten.zeit import jetzt_wie_im_entwicklungsmodus
from stammdaten.models import Kategorie, Ort, Person

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
            "zustand", "leihpool", "ort", "geraetename",
            "standardzuehoer", "technische_daten",
            "kaufdatum", "kaufdatum_nicht_ermittelbar",
            "kaufpreis_netto", "lieferant", "rechnungsnummer",
            "garantie_bis", "garantie_nicht_ermittelbar", "notiz",
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
        # F-88: „nicht ermittelbar“ markiert man an einem vorhandenen Gerät.
        self.fields["kaufdatum_nicht_ermittelbar"].label = "Kaufdatum nicht ermittelbar"
        self.fields["garantie_nicht_ermittelbar"].label = "Garantieende nicht ermittelbar"
        if kwargs.get("instance", None):
            # F-40: Beim Ändern bleiben Status, Person und Ort unberührt. Sie wechseln
            # nur über Ausgabe, Rückgabe und Umzug (Kapitel 4). seriennummern gilt nur fürs Anlegen.
            del self.fields["seriennummern"]
            del self.fields["ort"]
        else:
            # F-10, Kapitel 4: Ein neues Gerät steht auf Lager, an einem Lagerort.
            self.fields["ort"].label = "Lagerort (optional)"
            self.fields["ort"].queryset = Ort.objects.filter(typ=Ort.TYP_LAGER).order_by("kennung")
            del self.fields["kaufdatum_nicht_ermittelbar"]
            del self.fields["garantie_nicht_ermittelbar"]

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
        # F-83: Ein importiertes Gerät darf die Lücke behalten (Arbeitsliste F-88);
        # eine vorhandene Nummer löschen geht nicht.
        hat_luecke_aus_import = bool(self.instance.pk) and not self.instance.seriennummer
        if (
            kategorie is not None
            and kategorie.seriennummer_pflicht
            and not seriennummer
            and not hat_seriennummern
            and not hat_luecke_aus_import
        ):
            self.add_error(
                "seriennummer", "Diese Kategorie verlangt eine Seriennummer."
            )
        return daten


class GeratBearbeitungsForm(GeratForm):
    """Ändern eines vorhandenen Geräts (F-15). Inventarnummer bleibt (F-12)."""

    class Meta(GeratForm.Meta):
        # Status nicht per Formular änderbar: Statuswechsel sind Vorgänge
        # (Kapitel 4), hier nur Stammdaten.
        fields = [
            "kategorie", "hersteller", "modell", "seriennummer",
            "zustand", "leihpool", "geraetename",
            "standardzuehoer", "technische_daten",
            "kaufdatum", "kaufdatum_nicht_ermittelbar",
            "kaufpreis_netto", "lieferant", "rechnungsnummer",
            "garantie_bis", "garantie_nicht_ermittelbar", "notiz",
        ]


# --- M3 Lebenszyklus ---------------------------------------------------------

class GeratAusgabeForm(forms.Form):
    """Gerät ausgeben (F-20 bis F-23, F-131).

    A-0098 (F-131): der Dialog trägt je Gerät „Zustand“ (die vier Stufen
    von ``Gerat.ZUSTAENDE``, voreingestellt mit dem Zustand des Geräts),
    „Zubehör komplett“ (Ja, Nein) und „Bemerkung“. Protokoll und Signatur
    bleiben M6, das Protokoll-PDF folgt mit F-130.

    A-0127: Unterschrift (Signatur im Tool, Papier).
    """

    ZUBEOER = [("ja", "Ja"), ("nein", "Nein")]
    UNTERSCHRIFT = [
        ("tool", "Signatur im Tool"),
        ("papier", "Papier"),
    ]

    ziel_person = forms.ModelChoiceField(
        queryset=Person.objects.filter(aktiv=True),
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
    unterschrift = forms.ChoiceField(
        choices=UNTERSCHRIFT,
        required=True,
        initial="tool",
        label="Unterschrift",
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, gerat: Gerat | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        from stammdaten.models import Ort
        # F-20: Ziel ist ein Arbeitsplatz oder Raum, das Lager ist keins.
        self.fields["ziel_ort"].queryset = Ort.objects.filter(
            typ__in=[Ort.TYP_ARBEITSPLATZ, Ort.TYP_RAUM]
        ).order_by("kennung")
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
    lager_ort = forms.ModelChoiceField(
        queryset=None,
        required=False,
        empty_label=None,
        label="Lagerort",
        widget=forms.Select(attrs={"data-test": "lager-ort"}),
    )
    unterschrift = forms.ChoiceField(
        choices=GeratAusgabeForm.UNTERSCHRIFT,
        required=False,
        initial="tool",
        label="Unterschrift",
        widget=forms.RadioSelect,
    )
    empfaenger = forms.EmailField(
        required=False,
        label="Adresse für den Link, bei Rückgabe per Post",
        widget=forms.EmailInput(attrs={"data-test": "code-senden-empfaenger"}),
    )

    def __init__(self, *args, gerat: Gerat | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        from stammdaten.models import Ort
        self.fields["lager_ort"].queryset = Ort.objects.filter(typ=Ort.TYP_LAGER).order_by("kennung")
        if gerat is not None:
            from .services import zustand_bei_ausgabe
            self.zustand_bei_ausgabe = zustand_bei_ausgabe(gerat)
            # F-50: Vorgeschlagen ist der Zustand von damals, nicht „neuwertig“.
            self.fields["zustand_rueckgabe"].initial = self.zustand_bei_ausgabe or gerat.zustand

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
        # Kapitel 4: Umzug an einen Arbeitsplatz oder Raum; ins Lager führt die Rückgabe.
        self.fields["ziel_ort"].queryset = Ort.objects.exclude(typ=Ort.TYP_LAGER).order_by("kennung")


class ErstinventurForm(forms.Form):
    """Erstinventur am Gerät (F-89): alles freiwillig, „Geprüft“ gilt auch ohne Eingabe."""

    DATUM = ["%d.%m.%Y", "%Y-%m-%d"]

    seriennummer = forms.CharField(required=False, max_length=160)
    zustand = forms.TypedChoiceField(
        required=False, choices=Gerat.ZUSTAENDE, coerce=int, empty_value=None,
    )
    kaufdatum = forms.DateField(required=False, input_formats=DATUM, label="Kaufdatum")
    kaufdatum_nicht_ermittelbar = forms.BooleanField(required=False)
    garantie_bis = forms.DateField(required=False, input_formats=DATUM, label="Garantie bis")
    garantie_nicht_ermittelbar = forms.BooleanField(required=False)
    ziel_ort = forms.ModelChoiceField(queryset=None, required=False, label="Verbleib")

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

    def __init__(self, *args, gerat: Gerat | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if gerat is not None:
            self.fields["zustand"].initial = gerat.zustand

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
    lager_ort = forms.ModelChoiceField(
        queryset=Ort.objects.filter(typ=Ort.TYP_LAGER).order_by("kennung"),
        required=False,
        empty_label=None,
        label="Lagerort",
        widget=forms.Select(attrs={"data-test": "lager-ort"}),
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
    „Verbleib“ ist immer Pflicht (F-55);
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
        self.datentraeger = self._datentraeger
        heute = jetzt_wie_im_entwicklungsmodus().date()
        self.fields["datum"].initial = heute
        self.fields["datum"].widget.attrs["max"] = heute.isoformat()
        self._verloren = False
        # Kapitel 4: Aus „In Benutzung“ und „Verliehen“ nur verloren oder gestohlen.
        if gerat is not None and gerat.status not in (Gerat.STATUS_AUF_LAGER, Gerat.STATUS_IN_REPARATUR):
            self.fields["grund"].choices = [
                wahl for wahl in self.GRUENDE if wahl[0] in ("", *self.VERLOREN)
            ]

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
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "data-test": "ausmusterung-datum"}),
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
        if daten.get("datum") and daten["datum"] > jetzt_wie_im_entwicklungsmodus().date():
            self.add_error("datum", "Das Datum darf nicht in der Zukunft liegen.")
        verloren = grund in self.VERLOREN
        self._verloren = verloren
        # F-55: Verbleib ist immer Pflicht, auch bei verloren und gestohlen.
        if not (daten.get("disposition") or "").strip():
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

class _LeihAngabenForm(forms.Form):
    """Zustand, Zubehör und Bemerkung, wie bei der Ausgabe (F-30: „Protokoll wie F-21“)."""

    zustand = forms.ChoiceField(
        choices=Gerat.ZUSTAENDE,
        required=False,
        label="Zustand",
        widget=forms.Select(attrs={"data-test": "ausgabe-zustand"}),
    )
    zubehoer_komplett = forms.ChoiceField(
        choices=[("ja", "Ja"), ("nein", "Nein")],
        required=False,
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
        if gerat is not None:
            self.fields["zustand"].initial = gerat.zustand


class VerleihForm(_LeihAngabenForm):
    """Formular für den Verleih (F-30, TESTSCHNITTSTELLE 4).

    Person, Rückgabe bis (Pflicht), Zweck (Pflicht).
    A-0127: Unterschrift (Signatur im Tool, Papier).
    """

    UNTERSCHRIFT = [
        ("tool", "Signatur im Tool"),
        ("papier", "Papier"),
    ]

    person = forms.ModelChoiceField(
        label="Person",
        required=True,
        queryset=Person.objects.filter(aktiv=True).order_by("nachname"),
        widget=forms.Select(attrs={"data-test": "person"}),
    )
    rueckgabe_bis = forms.DateField(
        label="Rückgabe bis",
        required=True,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"data-test": "rueckgabe-bis", "type": "date"}),
    )
    zweck = forms.CharField(
        label="Zweck",
        required=True,
        widget=forms.TextInput(attrs={"data-test": "zweck"}),
    )
    unterschrift = forms.ChoiceField(
        choices=UNTERSCHRIFT,
        required=True,
        initial="tool",
        label="Unterschrift",
        widget=forms.RadioSelect,
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
        # Beschriftungen wörtlich aus dem Prototyp (TESTSCHNITTSTELLE 4).
        labels = {
            "kat": "Gerät",
            "beginn": "Von",
            "ende": "Bis",
            "zweck": "Zweck",
            "gerat": "Inventarnummer (optional)",
        }
        widgets = {
            "kat": forms.Select(attrs={"data-test": "kat"}),
            "beginn": forms.DateInput(format="%Y-%m-%d", attrs={"data-test": "beginn", "type": "date"}),
            "ende": forms.DateInput(format="%Y-%m-%d", attrs={"data-test": "ende", "type": "date"}),
            "zweck": forms.TextInput(attrs={
                "data-test": "zweck",
                "placeholder": "z. B. Schulung beim Kunden, Messe, Homeoffice-Phase",
            }),
            "gerat": forms.Select(attrs={"data-test": "gerat"}),
        }
        error_messages = {
            "kat": {"required": "Bitte eine Kategorie wählen."},
            "beginn": {"required": "Bitte das Startdatum angeben.", "invalid": "Bitte das Startdatum angeben."},
            "ende": {"required": "Bitte das Enddatum angeben.", "invalid": "Bitte das Enddatum angeben."},
            "zweck": {"required": "Bitte den Zweck angeben."},
        }

    def __init__(self, *args, leihpool_geraete=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["gerat"].required = False
        self.fields["gerat"].empty_label = "Beliebiges Gerät dieser Kategorie"
        self.fields["gerat"].label_from_instance = services.leihgeraet_bezeichnung
        if leihpool_geraete is not None:
            self.fields["gerat"].queryset = leihpool_geraete
            self.fields["kat"].queryset = Kategorie.objects.filter(
                pk__in=leihpool_geraete.values("kategorie_id")
            ).order_by("name")
        self.fields["kat"].empty_label = None
        self.fields["kat"].required = True
        self.fields["beginn"].required = True
        self.fields["ende"].required = True
        self.fields["zweck"].required = True

    def clean(self):
        data = super().clean()
        beginn = data.get("beginn")
        ende = data.get("ende")
        if beginn and ende and beginn > ende:
            self.add_error("ende", "Das Enddatum muss am oder nach dem Startdatum liegen.")
        if beginn and beginn < jetzt_wie_im_entwicklungsmodus().date():
            self.add_error("beginn", "Das Startdatum darf nicht in der Vergangenheit liegen.")
        gerat = data.get("gerat")
        kat = data.get("kat")
        if gerat is not None and kat is not None and gerat.kategorie_id != kat.id:
            self.add_error("gerat", "Das Gerät steht nicht in der Kategorie.")
        return data


class LeiheGenehmigenForm(forms.Form):
    """M5 Teil 2 (F-32): IT genehmigt mit Zuweisung eines Leihpool-Geräts.

    Der Queryset prüft nur die Kategorie; ob das Gerät verfügbar ist, sagt die
    Service-Schicht mit einer Meldung (F-32, F-34).
    """

    gerat = forms.ModelChoiceField(
        label="Gerät zuweisen",
        queryset=Gerat.objects.none(),
        error_messages={
            "required": "Bitte ein Gerät zuweisen.",
            "invalid_choice": "Dieses Gerät steht nicht im Leihpool der Kategorie.",
        },
        widget=forms.Select(attrs={"data-test": "gerat"}),
    )

    def __init__(self, *args, leihpool_geraete=None, **kwargs):
        super().__init__(*args, **kwargs)
        if leihpool_geraete is not None:
            self.fields["gerat"].queryset = leihpool_geraete


class LeiheAblehnenForm(forms.Form):
    """M5 Teil 2 (F-32): IT lehnt mit Pflichtbegründung ab."""

    begruendung = forms.CharField(
        label="Begründung",
        required=True,
        error_messages={"required": "Bitte eine Begründung angeben (Pflicht)."},
        widget=forms.Textarea(
            attrs={
                "data-test": "begruendung",
                "rows": 3,
                "placeholder": "Wird dem Mitarbeiter per E-Mail mitgeteilt",
            }
        ),
    )


class LeiheZurueckziehenForm(forms.Form):
    """M5 Teil 2 (F-37): Mitarbeiter zieht die Leihe zurück. Der Knopf genügt."""


class LeiheAusgebenForm(_LeihAngabenForm):
    """M5 Teil 4 (F-33): IT gibt eine genehmigte Leihe aus.

    Unterschrift wie beim direkten Verleih (F-30). Ohne Angabe gilt der
    Papierweg, wie in der Service-Schicht.
    """

    unterschrift = forms.ChoiceField(
        choices=VerleihForm.UNTERSCHRIFT,
        required=False,
        initial="tool",
        label="Unterschrift",
        widget=forms.RadioSelect,
    )


class LeiheVerlaengernForm(forms.Form):
    """M5 Teil 4 (F-35): IT gewährt eine Verlängerung."""

    rueckgabe_bis_neu = forms.DateField(
        label="Neues Rückgabedatum",
        required=True,
        error_messages={
            "required": "Bitte das neue Rückgabedatum angeben.",
            "invalid": "Bitte das neue Rückgabedatum angeben.",
        },
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"data-test": "rueckgabe-bis-neu", "type": "date"},
        ),
    )

    def __init__(self, *args, vorschlag=None, **kwargs):
        super().__init__(*args, **kwargs)
        if vorschlag is not None:
            self.fields["rueckgabe_bis_neu"].initial = vorschlag


class LeiheVerlaengerungAnfragenForm(forms.Form):
    """F-35, F-111: Mitarbeiter fragt eine Verlängerung an."""

    rueckgabe_bis_neu = forms.DateField(
        label="Neues Rückgabedatum",
        required=True,
        error_messages={
            "required": "Bitte das neue Rückgabedatum angeben.",
            "invalid": "Bitte das neue Rückgabedatum angeben.",
        },
    )
