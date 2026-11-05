/* WMC Inventar · Plan pflegen (plan_bearbeiten.html)
   Ziehen von Plätzen und Räumen auf den Grundriss (F-67).
   Position in Prozent relativ zum Bild; ohne Inline-Styles im HTML (CSP). */
(function () {
  var pflegen = document.querySelector('[data-test="raumplan-pflegen"]');
  var flaeche = document.querySelector('[data-test="plan-flaeche"]');
  if (!pflegen || !flaeche) return;
  var token = document.querySelector('meta[name="csrf-token"]').content;
  var pfad = '/arbeitsplaetze/plan/' + pflegen.getAttribute('data-id') + '/bearbeiten/';

  function setzen(knopf, x, y) {
    knopf.style.left = x + '%';
    knopf.style.top = y + '%';
  }

  function speichern(ortId, punkt) {
    var formular = document.createElement('form');
    formular.method = 'post';
    formular.action = pfad;
    formular.hidden = true;
    [['csrfmiddlewaretoken', token], ['ort', ortId], ['x', punkt.x], ['y', punkt.y]].forEach(function (paar) {
      var feld = document.createElement('input');
      feld.type = 'hidden';
      feld.name = paar[0];
      feld.value = paar[1];
      formular.appendChild(feld);
    });
    document.body.appendChild(formular);
    formular.submit();
  }

  function punktAus(ereignis) {
    var rechteck = flaeche.getBoundingClientRect();
    var x = ((ereignis.clientX - rechteck.left) / rechteck.width) * 100;
    var y = ((ereignis.clientY - rechteck.top) / rechteck.height) * 100;
    return {
      x: Math.max(0, Math.min(100, Math.round(x * 10) / 10)),
      y: Math.max(0, Math.min(100, Math.round(y * 10) / 10))
    };
  }

  // Marken auf dem Plan: Position setzen und ziehen
  flaeche.querySelectorAll('.orte').forEach(function (knopf) {
    var x = knopf.getAttribute('data-x');
    var y = knopf.getAttribute('data-y');
    if (x !== null && y !== null) setzen(knopf, x, y);

    knopf.addEventListener('pointerdown', function (start) {
      start.preventDefault();
      knopf.setPointerCapture(start.pointerId);
      var bewegt = false;
      function weiter(ereignis) {
        var punkt = punktAus(ereignis);
        bewegt = true;
        setzen(knopf, punkt.x, punkt.y);
      }
      function ende(ereignis) {
        knopf.removeEventListener('pointermove', weiter);
        knopf.removeEventListener('pointerup', ende);
        if (bewegt) speichern(knopf.getAttribute('data-ort-id'), punktAus(ereignis));
      }
      knopf.addEventListener('pointermove', weiter);
      knopf.addEventListener('pointerup', ende);
    });
  });

  // Aus der Liste „Ohne Position“ auf den Plan ziehen
  document.querySelectorAll('[data-test="ohne-position-eintrag"]').forEach(function (eintrag) {
    eintrag.addEventListener('dragstart', function (ereignis) {
      ereignis.dataTransfer.effectAllowed = 'move';
      ereignis.dataTransfer.setData('text/plain', eintrag.getAttribute('data-ort-id'));
    });
  });
  flaeche.addEventListener('dragover', function (ereignis) { ereignis.preventDefault(); });
  flaeche.addEventListener('drop', function (ereignis) {
    ereignis.preventDefault();
    var ortId = ereignis.dataTransfer.getData('text/plain');
    if (ortId) speichern(ortId, punktAus(ereignis));
  });
})();
