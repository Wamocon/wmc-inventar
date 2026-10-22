#!/usr/bin/env bash
# WMC Inventar – tägliche Sicherung (N-06)
# Datenbank-Dump und Kopie der Dateiablage.
# Aufruf: scripts/sicherung.sh [Zielverzeichnis]

set -euo pipefail

ZIEL="${1:-/srv/inventar/sicherung}"
STAMPE=$(date +%Y%m%d-%H%M%S)
ZIEL_VERZ="$ZIEL/$STAMPE"

mkdir -p "$ZIEL_VERZ"

# Datenbank-Dump (PostgreSQL)
if command -v pg_dump &>/dev/null && [ -n "${DATABASE_URL:-}" ]; then
    pg_dump "$DATABASE_URL" | gzip > "$ZIEL_VERZ/inventar.sql.gz"
    echo "Datenbank-Dump: $ZIEL_VERZ/inventar.sql.gz"
fi

# Dateiablage kopieren
DATEIABLAGE="${DATEIABLAGE:-var/dateien}"
if [ -d "$DATEIABLAGE" ]; then
    cp -a "$DATEIABLAGE" "$ZIEL_VERZ/dateien"
    echo "Dateiablage: $ZIEL_VERZ/dateien"
fi

# Mailablage kopieren
MAIL_ABLAGE="${MAIL_ABLAGE:-var/mails}"
if [ -d "$MAIL_ABLAGE" ]; then
    cp -a "$MAIL_ABLAGE" "$ZIEL_VERZ/mails"
    echo "Mailablage: $ZIEL_VERZ/mails"
fi

echo "Sicherung abgeschlossen: $ZIEL_VERZ"
