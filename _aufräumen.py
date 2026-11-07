import pathlib

for name in [
    "leih_genehmigen.html",
    "leih_ablehnen.html",
    "leih_anfrage.html",
]:
    pfad = pathlib.Path("templates/geraete") / name
    if pfad.exists():
        pfad.unlink()
        print(f"Entfernt: {pfad}")
    else:
        print(f"Steht nicht da: {pfad}")
