"""Deutsche Anzeigeformate der Anwendung (N-08): Datum immer TT.MM.JJJJ.

Ohne diese Datei gälte Djangos deutsches Sprachpaket mit „5. November 2026“.
"""

DATE_FORMAT = "d.m.Y"
DATETIME_FORMAT = "d.m.Y H:i"
SHORT_DATE_FORMAT = "d.m.Y"
SHORT_DATETIME_FORMAT = "d.m.Y H:i"
DECIMAL_SEPARATOR = ","
THOUSAND_SEPARATOR = "."
NUMBER_GROUPING = 3
