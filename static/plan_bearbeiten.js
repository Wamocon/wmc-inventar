/* WMC Inventar · Plan pflegen (plan_bearbeiten.html)
   Ziehen von Plätzen und Räumen auf den Grundriss (F-67).
   Position in Prozent relativ zum Bild; ohne Inline-Styles im HTML (CSP). */
(function () {
  // Auswahl „Raumplan“: zum anderen Plan wechseln
  document.querySelectorAll('[data-test="plan-wechsel"] select').forEach(function (feld) {
    feld.addEventListener('change', function () { feld.form.submit(); });
  });

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

  function begrenzt(wert) {
    return Math.max(0, Math.min(100, Math.round(wert * 10) / 10));
  }

  function punktAus(ereignis) {
    var rechteck = flaeche.getBoundingClientRect();
    return {
      x: begrenzt(((ereignis.clientX - rechteck.left) / rechteck.width) * 100),
      y: begrenzt(((ereignis.clientY - rechteck.top) / rechteck.height) * 100)
    };
  }

  // Marken auf dem Plan: Position setzen, ziehen, per Tastatur verschieben
  flaeche.querySelectorAll('.orte').forEach(function (knopf) {
    var x = parseFloat(knopf.getAttribute('data-x'));
    var y = parseFloat(knopf.getAttribute('data-y'));
    setzen(knopf, x, y);

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

    // N-08: Tastaturbedienung statt Ziehen
    var schritte = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    var verschoben = false;
    knopf.addEventListener('keydown', function (ereignis) {
      var schritt = schritte[ereignis.key];
      if (schritt) {
        ereignis.preventDefault();
        x = begrenzt(x + schritt[0]);
        y = begrenzt(y + schritt[1]);
        verschoben = true;
        setzen(knopf, x, y);
      } else if (ereignis.key === 'Enter' && verschoben) {
        ereignis.preventDefault();
        speichern(knopf.getAttribute('data-ort-id'), { x: x, y: y });
      }
    });
  });

  // Aus der Liste „Ohne Position“ auf den Plan ziehen oder per Schaltfläche setzen
  document.querySelectorAll('[data-test="ohne-position-eintrag"]').forEach(function (eintrag) {
    eintrag.addEventListener('dragstart', function (ereignis) {
      ereignis.dataTransfer.effectAllowed = 'move';
      ereignis.dataTransfer.setData('text/plain', eintrag.getAttribute('data-ort-id'));
    });
    var knopf = eintrag.querySelector('[data-test="ohne-position-setzen"]');
    if (knopf) {
      knopf.addEventListener('click', function () {
        speichern(eintrag.getAttribute('data-ort-id'), { x: 50, y: 50 });
      });
    }
  });
  flaeche.addEventListener('dragover', function (ereignis) { ereignis.preventDefault(); });
  flaeche.addEventListener('drop', function (ereignis) {
    ereignis.preventDefault();
    var ortId = ereignis.dataTransfer.getData('text/plain');
    if (ortId) speichern(ortId, punktAus(ereignis));
  });
})();
