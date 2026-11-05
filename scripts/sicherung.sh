#!/usr/bin/env bash
# WMC Inventar: tägliche Sicherung (N-06)
# Datenbank-Dump und Kopie der Dateiablage in ein Verzeichnis, das UrBackup erfasst.
# Aufruf: scripts/sicherung.sh [Zielverzeichnis]
#
# Scheitert ein Teil, endet das Skript mit einem Fehler und der Ordner behält die Endung
# .unvollstaendig. Eine Sicherung ohne Dump darf nicht als Erfolg durchgehen.

set -euo pipefail

ZIEL="${1:-/srv/inventar/sicherung}"
STEMPEL=$(date +%Y%m%d-%H%M%S)
# Der endgültige Name entsteht erst am Schluss; bis dahin heißt der Ordner .unvollstaendig.
ZIEL_VERZ="$ZIEL/$STEMPEL-$$.unvollstaendig"
AUFHEBEN_TAGE="${SICHERUNG_TAGE:-30}"

mkdir -p "$ZIEL_VERZ"
trap 'echo "Sicherung gescheitert: $ZIEL_VERZ" >&2' ERR

# Datenbank
if [ -n "${DATABASE_URL:-}" ]; then
    command -v pg_dump >/dev/null || { echo "pg_dump fehlt, ohne Dump keine Sicherung." >&2; false; }
    pg_dump --clean --if-exists --dbname="$DATABASE_URL" | gzip > "$ZIEL_VERZ/inventar.sql.gz"
    gzip -t "$ZIEL_VERZ/inventar.sql.gz"
    echo "Datenbank-Dump: $ZIEL_VERZ/inventar.sql.gz"
else
    SQLITE="${SQLITE_DATEI:-var/inventar.sqlite3}"
    [ -f "$SQLITE" ] || { echo "Keine Datenbank gefunden: $SQLITE" >&2; false; }
    cp -a "$SQLITE" "$ZIEL_VERZ/inventar.sqlite3"
    echo "SQLite-Kopie: $ZIEL_VERZ/inventar.sqlite3"
fi

# Dateiablage: Protokolle, Fotos, Anhänge, Grundrisse
DATEIABLAGE="${DATEIABLAGE:-var/dateien}"
if [ -d "$DATEIABLAGE" ]; then
    cp -a "$DATEIABLAGE" "$ZIEL_VERZ/dateien"
    echo "Dateiablage: $ZIEL_VERZ/dateien"
else
    echo "Dateiablage fehlt: $DATEIABLAGE" >&2
    false
fi

mv -T "$ZIEL_VERZ" "$ZIEL/$STEMPEL"

# Alte Stände aufräumen, nur die eigenen Stempelordner
find "$ZIEL" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime "+$AUFHEBEN_TAGE" -exec rm -rf {} +

echo "Sicherung abgeschlossen: $ZIEL/$STEMPEL"
