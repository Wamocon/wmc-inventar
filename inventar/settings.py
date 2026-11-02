"""Einstellungen der Anwendung.

Konfiguration ausschließlich über Umgebungsvariablen (docs/TESTSCHNITTSTELLE.md, Abschnitt 1).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# TESTSCHNITTSTELLE 1: Relative Pfade gelten ab dem Wurzelverzeichnis des Repos
# (wo manage.py liegt). Damit liegen Datenbank, Dateiablage und Testsiegel
# im Repository, nicht außerhalb.
ROOT_DIR = BASE_DIR

# --- Entwicklungsmodus ------------------------------------------------------
DEBUG = os.environ.get("INVENTAR_DEBUG", "0") == "1"

# --- Sicherheit -------------------------------------------------------------
if DEBUG:
    # Im Entwicklungsmodus ein fester, nicht geheimer Testwert (TESTSCHNITTSTELLE 1)
    SECRET_KEY = "wmc-inventar-test-geheim-2026"
else:
    secret = os.environ.get("INVENTAR_SECRET_KEY", "").strip()
    if not secret:
        raise RuntimeError(
            "INVENTAR_SECRET_KEY fehlt. Ohne Entwicklungsmodus (INVENTAR_DEBUG=1) "
            "braucht die Anwendung einen eigenen Schlüssel."
        )
    SECRET_KEY = secret

# --- Zeitzone ---------------------------------------------------------------
# N-08: Zeitzone Europe/Berlin, Datumsanzeige TT.MM.JJJJ
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
LANGUAGE_CODE = "de"
USE_TZ = True
DATE_FORMAT = "d.m.Y"
DATETIME_FORMAT = "d.m.Y H:i"
SHORT_DATE_FORMAT = "d.m.Y"
SHORT_DATETIME_FORMAT = "d.m.Y H:i"

# --- Apps -------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "konten",
    "stammdaten",
    "geraete",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "inventar.middleware.CSPMiddleware",
]

ROOT_URLCONF = "inventar.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [ROOT_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "inventar.wsgi.application"

# --- Datenbank --------------------------------------------------------------
# N-01: PostgreSQL im Betrieb, ohne DATABASE_URL SQLite (TESTSCHNITTSTELLE 1)
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL and DATABASE_URL.startswith("postgres"):
    # z. B. postgres://inventar:secret@db:5432/inventar
    import re
    m = re.match(
        r"postgres(?:ql)?://(?P<user>[^:]+):(?P<pass>[^@]*)@"
        r"(?P<host>[^:/]+)(?::(?P<port>\d+))?/(?P<name>[^/?]+)",
        DATABASE_URL,
    )
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": m.group("name"),
            "USER": m.group("user"),
            "PASSWORD": m.group("pass"),
            "HOST": m.group("host"),
            "PORT": m.group("port") or "5432",
        }
    }
else:
    sqlite_path = ROOT_DIR / "var" / "inventar.sqlite3"
    sqlite_path.parent.mkdir(exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(sqlite_path),
        }
    }

# --- Passwörter -------------------------------------------------------------
# N-02: Argon2id
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# --- Authentifizierung ------------------------------------------------------
# F-05: Sitzungsende nach 8 h ohne Aktivität
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# --- Statische Dateien ------------------------------------------------------
STATIC_URL = "static/"
static_dir = ROOT_DIR / "static"
STATICFILES_DIRS = [static_dir] if static_dir.exists() else []
STATIC_ROOT = ROOT_DIR / "var" / "static"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_ARGS = {
    "max_age": 60,
    "no_vary": True,
}

# --- Dateiablage -------------------------------------------------------------
# Protokolle, Fotos, Anhänge, Grundrisse (TESTSCHNITTSTELLE 1)
DATEIABLAGE = os.environ.get("DATEIABLAGE", "").strip() or str(ROOT_DIR / "var" / "dateien")
Path(DATEIABLAGE).mkdir(parents=True, exist_ok=True)
MEDIA_ROOT = DATEIABLAGE
MEDIA_URL = "medien/"

# --- Basis-URL für Links in Mails und QR-Codes -------------------------------
BASIS_URL = os.environ.get("BASIS_URL", "").strip() or "http://127.0.0.1:8000"
BASIS_URL = BASIS_URL.rstrip("/")

# --- Mailablage ---------------------------------------------------------------
# Statt Versand: jede Mail als Datei (TESTSCHNITTSTELLE 1.3)
MAIL_ABLAGE = os.environ.get("MAIL_ABLAGE", "").strip()
if MAIL_ABLAGE:
    Path(MAIL_ABLAGE).mkdir(parents=True, exist_ok=True)
    EMAIL_BACKEND = "konten.mail.MailAblageBackend"
    EMAIL_HOST = "mail-ablage"
    DEFAULT_FROM_EMAIL = os.environ.get("MAIL_ABSENDER", "inventar@beispiel.test")
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ.get("SMTP_HOST", "localhost")
    EMAIL_PORT = int(os.environ.get("SMTP_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("SMTP_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("SMTP_PASSWORT", "")
    EMAIL_USE_TLS = os.environ.get("SMTP_TLS", "1") == "1"
    DEFAULT_FROM_EMAIL = os.environ.get("MAIL_ABSENDER", "inventar@beispiel.test")

# --- Siegel (F-138) ----------------------------------------------------------
SIEGEL_P12 = os.environ.get("SIEGEL_P12", "").strip()
SIEGEL_PASSWORT = os.environ.get("SIEGEL_PASSWORT", "").strip()
if not SIEGEL_P12 and DEBUG:
    SIEGEL_P12 = str(ROOT_DIR / "var" / "testsiegel.p12")
    SIEGEL_PASSWORT = "testsiegel"

# --- Kennzahlen-Schnittstelle (F-105) ---------------------------------------
KENNZAHLEN_TOKEN = os.environ.get("KENNZAHLEN_TOKEN", "").strip()

# --- Passwort-Beispielwert (TESTSCHNITTSTELLE 2) -----------------------------
BEISPIEL_PASSWORT = os.environ.get("BEISPIEL_PASSWORT", "Beispiel-Passwort-2026")

# --- Sicherheit ---------------------------------------------------------------
# N-02: sichere Session-Cookies, CSRF, Sicherheitsheader, CSP ohne Inline-Skripte
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "form-action 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'"
)

AUTH_USER_MODEL = "konten.Konto"

LOGIN_URL = "/anmelden/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/anmelden/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
