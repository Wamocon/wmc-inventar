/* WMC Inventar · Raumplan (raumplan.html)
   Positionen aus data-x/data-y setzen, Pop-up, Hervorhebung.
   Ändert nichts an htmx; verwendet fetch für die Pop-up-Inhalte.
   (F-65 bis F-69, A-0913 Teil 2) */
(function () {
  // Auswahl Standort und Etage: ohne Inline-Handler (CSP script-src 'self')
  document.querySelectorAll('[data-test="auswahl"] select').forEach(function (feld) {
    feld.addEventListener('change', function () { feld.form.submit(); });
  });

  var plan = document.querySelector('[data-test="raumplan"]');
  var bereich = document.getElementById('platz-popup');
  var ausloeser = null;

  // Positionen aus data-x/data-y setzen (statt Inline-Style im HTML, CSP style-src 'self')
  if (plan) {
    plan.querySelectorAll('[data-test="plan-orte"] .orte').forEach(function (knopf) {
      var x = knopf.getAttribute('data-x');
      var y = knopf.getAttribute('data-y');
      if (x !== null && y !== null) {
        knopf.style.left = x + '%';
        knopf.style.top = y + '%';
      }
    });
  }

  function schliessen() {
    if (!bereich || bereich.hidden) return;
    bereich.hidden = true;
    bereich.innerHTML = '';
    if (ausloeser) {
      ausloeser.removeAttribute('aria-expanded');
      ausloeser.focus();
      ausloeser = null;
    }
  }

  function bedienbar() {
    return Array.prototype.slice.call(bereich.querySelectorAll('a[href], button'));
  }

  function oeffnen(ziel) {
    var pfad = ziel.getAttribute('data-pfad');
    if (!pfad || !bereich) return;
    schliessen();
    fetch(pfad, { headers: { 'HX-Request': 'true' } })
      .then(function (antwort) { return antwort.ok ? antwort.text() : null; })
      .then(function (html) {
        if (html === null) return;
        bereich.innerHTML = html;
        bereich.hidden = false;
        bereich.querySelectorAll('[data-test="popup-schliessen"]').forEach(function (knopf) {
          knopf.addEventListener('click', function (ereignis) {
            ereignis.stopPropagation();
            schliessen();
          });
        });
        ausloeser = ziel;
        ziel.setAttribute('aria-expanded', 'true');
        // F-66: Der Fokus geht in den Dialog und kommt beim Schließen zurück.
        var erster = bedienbar()[0];
        if (erster) erster.focus();
      })
      .catch(function () { schliessen(); });
  }

  // Klick und Enter: Alle Auslöser sind Schaltflächen, Enter löst dort den Klick aus.
  document.querySelectorAll('[data-pfad]').forEach(function (knopf) {
    knopf.addEventListener('click', function () { oeffnen(knopf); });
  });

  // Klick außerhalb schließt das Pop-up
  document.addEventListener('click', function (ereignis) {
    if (ereignis.target.closest('#platz-popup') || ereignis.target.closest('[data-pfad]')) return;
    schliessen();
  });

  document.addEventListener('keydown', function (ereignis) {
    if (ereignis.key === 'Escape') {
      schliessen();
      return;
    }
    // Der Dialog ist modal: Tab bleibt darin.
    if (ereignis.key === 'Tab' && bereich && !bereich.hidden) {
      var felder = bedienbar();
      if (!felder.length) return;
      var erstes = felder[0];
      var letztes = felder[felder.length - 1];
      if (ereignis.shiftKey && document.activeElement === erstes) {
        ereignis.preventDefault();
        letztes.focus();
      } else if (!ereignis.shiftKey && document.activeElement === letztes) {
        ereignis.preventDefault();
        erstes.focus();
      }
    }
  });

  // F-69: „Im Raumplan zeigen“: Der Server nennt den Ort auf diesem Plan.
  var kennung = plan && plan.getAttribute('data-hervorheben');
  if (kennung) {
    var marke = plan.querySelector('.orte[data-id="' + kennung + '"]');
    if (marke) {
      marke.classList.add('hervorgehoben');
      marke.scrollIntoView({ block: 'center', inline: 'center' });
    }
  }
})();
