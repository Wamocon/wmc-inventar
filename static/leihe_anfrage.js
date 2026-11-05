/* WMC Inventar · Leihgerät anfragen (leihe_neu.html, F-31)
   Nach jeder Wahl von Kategorie und Zeitraum fragt das Formular den Server,
   wie viele Leihpool-Geräte frei sind, und füllt die optionale Geräteauswahl. */
(function () {
  var formular = document.querySelector('[data-test="leih-anfrage"]');
  if (!formular) return;
  var kategorie = formular.querySelector('[data-test="kat"]');
  var von = formular.querySelector('[data-test="beginn"]');
  var bis = formular.querySelector('[data-test="ende"]');
  var geraet = formular.querySelector('[data-test="gerat"]');
  var anzeige = formular.querySelector('[data-test="freie-geraete"]');
  var HINWEIS = 'Zeitraum wählen, um die freien Geräte zu sehen.';
  var laufend = 0;

  function geraeteFuellen(geraete) {
    var gewaehlt = geraet.value;
    var leer = geraet.options[0];
    geraet.textContent = '';
    geraet.appendChild(leer);
    geraete.forEach(function (eintrag) {
      var option = document.createElement('option');
      option.value = String(eintrag.id);
      option.textContent = eintrag.text;
      geraet.appendChild(option);
    });
    geraet.value = gewaehlt;
    if (geraet.selectedIndex < 0) geraet.selectedIndex = 0;
  }

  function aktualisieren() {
    var nummer = ++laufend;
    var parameter = new URLSearchParams({
      kat: kategorie.value,
      beginn: von.value,
      ende: bis.value
    });
    fetch(formular.getAttribute('data-frei-url') + '?' + parameter.toString(), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (antwort) {
        if (!antwort.ok) throw new Error('Status ' + antwort.status);
        return antwort.json();
      })
      .then(function (stand) {
        if (nummer !== laufend) return;
        anzeige.textContent = stand.text || HINWEIS;
        anzeige.classList.toggle('warning', stand.art === 'warning');
        anzeige.classList.toggle('info', stand.art !== 'warning');
        geraeteFuellen(stand.geraete);
      })
      .catch(function () {
        if (nummer !== laufend) return;
        anzeige.textContent = HINWEIS;
      });
  }

  [kategorie, von, bis].forEach(function (feld) {
    feld.addEventListener('change', aktualisieren);
  });
})();
