/* WMC Inventar · Raumplan (raumplan.html)
   Positionen aus data-x/data-y setzen, Pop-up, Hervorhebung.
   Ändert nichts an htmx; verwendet fetch für die Pop-up-Inhalte.
   (F-65 bis F-68, A-0913 Teil 2) */
(function () {
  var plan = document.querySelector('[data-test="raumplan"]');
  if (!plan) return;

  // Positionen aus data-x/data-y setzen (statt Inline-Style im HTML, CSP style-src 'self')
  plan.querySelectorAll('[data-test="plan-orte"] .orte').forEach(function (knopf) {
    var x = knopf.getAttribute('data-x');
    var y = knopf.getAttribute('data-y');
    if (x !== null && y !== null) {
      knopf.style.left = x + '%';
      knopf.style.top = y + '%';
    }
  });

  function schliessenPopu() {
    var bereich = document.getElementById('platz-popup');
    if (bereich) {
      bereich.hidden = true;
      bereich.innerHTML = '';
    }
    plan.querySelectorAll('[data-test="platz"]')
      .forEach(function (knopf) { knopf.removeAttribute('aria-expanded'); });
  }

  function popu(ziel) {
    var bereich = document.getElementById('platz-popup');
    var grund = ziel.getAttribute('data-pfad');
    if (!grund) return;
    schliessenPopu();
    fetch(grund, { headers: { 'HX-Request': 'true' } })
      .then(function (antwort) {
        if (!antwort.ok) {
          schliessenPopu();
          return null;
        }
        return antwort.text();
      })
      .then(function (html) {
        if (html === null) return;
        bereich.innerHTML = html;
        bereich.hidden = false;
        // Schließen-Knopf verbinden
        var schliessen = bereich.querySelector('[data-test="popup-schliessen"]');
        if (schliessen) {
          schliessen.addEventListener('click', function (ereignis) {
            ereignis.stopPropagation();
            schliessenPopu();
          });
        }
        ziel.setAttribute('aria-expanded', 'true');
      })
      .catch(function () { schliessenPopu(); });
  }

  // Klick auf Platz öffnet Pop-up
  plan.querySelectorAll('[data-test="platz"]').forEach(function (knopf) {
    knopf.addEventListener('click', function () { popu(knopf); });
    knopf.addEventListener('keydown', function (ereignis) {
      if (ereignis.key === 'Enter') { popu(knopf); }
    });
  });

  // Klick außerhalb schließt Pop-up
  document.addEventListener('click', function (ereignis) {
    if (ereignis.target.closest('#platz-popup')) return;
    if (ereignis.target.closest('[data-test="platz"]')) return;
    schliessenPopu();
  });

  // Escape schließt Pop-up
  document.addEventListener('keydown', function (ereignis) {
    if (ereignis.key === 'Escape') {
      schliessenPopu();
    }
  });

  // Hervorhebung aus ?hervorheben=Standort|Kennung (F-69, „Im Raumplan zeigen")
  var parameter = new URLSearchParams(window.location.search);
  var hervorheben = parameter.get('hervorheben');
  if (hervorheben) {
    var kennung = hervorheben.split('|')[1];
    if (kennung) {
      var mark = plan.querySelector('[data-id="' + kennung + '"]');
      if (mark) {
        mark.classList.add('hervorgehoben');
        mark.scrollIntoView({ block: 'nearest' });
      }
    }
  }
})();
