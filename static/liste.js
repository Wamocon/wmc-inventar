/* WMC Inventar · Geräteliste (liste.html)
   Auswahl für den Etikettendruck: Zähler, Knopf und „alle auswählen“ (F-73). */
(function () {
  var formular = document.querySelector('[data-test="etiketten-formular"]');
  if (!formular) return;
  var alle = formular.querySelector('[data-test="auswahl-alle"]');
  var knopf = formular.querySelector('[data-test="etiketten-drucken"]');
  var anzahl = formular.querySelector('[data-test="auswahl-anzahl"]');
  var leiste = formular.querySelector('.bulk');
  var felder = formular.querySelectorAll('[data-test="auswahl"]');

  function aktualisieren() {
    var n = 0;
    felder.forEach(function (feld) {
      if (feld.checked) n += 1;
      var zeile = feld.closest('tr');
      if (zeile) zeile.classList.toggle('gewaehlt', feld.checked);
    });
    anzahl.textContent = n + ' ausgewählt';
    knopf.disabled = n === 0;
    leiste.classList.toggle('leer', n === 0);
    if (alle) alle.checked = n > 0 && n === felder.length;
  }

  felder.forEach(function (feld) { feld.addEventListener('change', aktualisieren); });
  if (alle) {
    alle.addEventListener('change', function () {
      felder.forEach(function (feld) { feld.checked = alle.checked; });
      aktualisieren();
    });
  }
  aktualisieren();
})();
