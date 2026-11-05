"""Konten-Modelle (F-01 bis F-05, F-121 Rollen).

Kapitel 2 der Anforderungen: Admin, Mitarbeiter, Leser.
Rechte werden serverseitig geprüft (AGENTS.md).
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class KontoManager(BaseUserManager):
    """Manager für Konten (F-02: anlegen, Rollen, deaktivieren)."""

    use_in_migrations = True

    def _create_konto(self, email, password=None, **extra):
        if not email:
            raise ValueError("Ein Konto braucht eine E-Mail-Adresse.")
        email = self.normalize_email(email)
        konto = self.model(email=email, **extra)
        if password is not None:
            konto.set_password(password)
        else:
            konto.set_unusable_password()
        konto.save(using=self._db)
        return konto

    def create_konto(self, email, password=None, **extra):
        extra.setdefault("rolle", Konto.ROLLE_MITARBEITER)
        return self._create_konto(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("rolle", Konto.ROLLE_ADMIN)
        return self._create_konto(email, password, **extra)


class Konto(AbstractBaseUser, PermissionsMixin):
    """Benutzerkonto (Anmeldung mit E-Mail und Passwort, F-01).

    Rollen (Kapitel 2):
      - admin       IT, pflegt alles
      - mitarbeiter  alle Beschäftigten, sieht nur eigene Geräte
      - leser        Geschäftsführung, liest Dashboard, Listen, Historie

    Deaktivierte Konten können sich nicht anmelden (F-02).
    Nach 5 Fehlversuchen 15 Minuten gesperrt (F-01).
    """

    ROLLE_ADMIN = "admin"
    ROLLE_MITARBEITER = "mitarbeiter"
    ROLLE_LESER = "leser"
    ROLLEN = [
        (ROLLE_ADMIN, "Admin"),
        (ROLLE_MITARBEITER, "Mitarbeiter"),
        (ROLLE_LESER, "Leser"),
    ]

    email = models.EmailField("E-Mail", unique=True)
    rolle = models.CharField("Rolle", max_length=16, choices=ROLLEN, default=ROLLE_MITARBEITER)
    aktiv = models.BooleanField("aktiv", default=True)
    letzter_login = models.DateTimeField("letzter Login", null=True, blank=True)

    # F-01: Sperre nach 5 Fehlversuchen für 15 Minuten.
    # Zähler in der Datenbank, nicht im Speicher (TESTSCHNITTSTELLE 1.2)
    fehlversuche = models.PositiveSmallIntegerField(default=0)
    gesperrt_bis = models.DateTimeField(null=True, blank=True)

    # Mitarbeiter-Rolle braucht eine Person (Kapitel 2)
    person = models.ForeignKey(
        "stammdaten.Person",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="konten",
    )

    objects = KontoManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Konto"
        verbose_name_plural = "Konten"
        ordering = ["email"]

    def __str__(self):
        return self.email

    # --- Rollen (Kapitel 2) -----------------------------------------------
    @property
    def ist_admin(self) -> bool:
        return self.rolle == self.ROLLE_ADMIN

    @property
    def ist_mitarbeiter(self) -> bool:
        return self.rolle == self.ROLLE_MITARBEITER

    @property
    def ist_leser(self) -> bool:
        return self.rolle == self.ROLLE_LESER

    def darf_geraete_sehen(self) -> bool:
        return self.rolle in (self.ROLLE_ADMIN, self.ROLLE_LESER)

    def darf_stammdaten_sehen(self) -> bool:
        return self.rolle in (self.ROLLE_ADMIN, self.ROLLE_LESER)

    def darf_verleih_entscheiden(self) -> bool:
        return self.rolle == self.ROLLE_ADMIN

    def darf_adminfunktionen(self) -> bool:
        return self.rolle == self.ROLLE_ADMIN

    def hat_person(self) -> bool:
        return self.person_id is not None

    def bezeichnung(self) -> str:
        """F-43 (A-0098): Name des Kontos, sonst die E-Mail-Adresse.

        Historie und „Erstellt“ zeigen das Konto, das den Vorgang
        ausgeführt hat. Ein leeres Name-Feld darf nicht leer bleiben.
        """
        if self.person is not None:
            name = f"{self.person.vorname} {self.person.nachname}".strip()
            if name:
                return name
        if self.email:
            return self.email
        return "ohne Konto"

    # --- Sperre (F-01) ------------------------------------------------------
    def ist_gesperrt(self, jetzt=None) -> bool:
        """F-01: nach 5 Fehlversuchen 15 Minuten gesperrt."""
        if not self.gesperrt_bis:
            return False
        if jetzt is None:
            from .zeit import jetzt_wie_im_entwicklungsmodus
            jetzt = jetzt_wie_im_entwicklungsmodus()
        return self.gesperrt_bis > jetzt

    def registriere_fehlversuch(self, jetzt=None):
        """Zählt einen Fehlversuch; sperrt nach dem fünften für 15 Minuten."""
        if jetzt is None:
            from .zeit import jetzt_wie_im_entwicklungsmodus
            jetzt = jetzt_wie_im_entwicklungsmodus()
        if self.gesperrt_bis is not None and self.gesperrt_bis <= jetzt:
            self.fehlversuche = 0
            self.gesperrt_bis = None
        self.fehlversuche = (self.fehlversuche or 0) + 1
        if self.fehlversuche >= 5 and self.gesperrt_bis is None:
            self.gesperrt_bis = jetzt + timedelta(minutes=15)
        self.save(update_fields=["fehlversuche", "gesperrt_bis"])

    def setze_fehlversuche_zurueck(self):
        self.fehlversuche = 0
        self.gesperrt_bis = None
        self.save(update_fields=["fehlversuche", "gesperrt_bis"])