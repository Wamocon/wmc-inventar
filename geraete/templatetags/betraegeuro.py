"""Template-Tags für die Übersicht (M7 Teil 3, A-0907).

F-104 Inventarwert als Beträge mit Tausenderpunkt und Euro-Zeichen
(TESTSCHNITTSTELLE Kapitel 5: Beträge).
"""
from decimal import Decimal, ROUND_HALF_UP

from django import template

register = template.Library()


@register.filter(name="betraegeuro")
def betraegeuro(wert) -> str:
    """Betrag als Euro: 123456.78 → 123.456,78 €.

    Tausenderpunkt, Komma als Dezimaltrenner, zwei Nachkommastellen,
    Euro-Zeichen (TESTSCHNITTSTELLE Kapitel 5).
    """
    if wert is None:
        return "–"
    try:
        dez = Decimal(str(wert))
    except Exception:
        return str(wert)
    dez = dez.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    negativ = dez < 0
    dez = abs(dez)
    ganz = int(dez)
    rest = int((dez - ganz) * 100)
    ganz_str = f"{ganz:,}".replace(",", ".")
    teile = f"{ganz_str},{rest:02d}"
    vorzeichen = "−" if negativ else ""
    return f"{vorzeichen}{teile} €"
