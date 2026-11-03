/* WMC Inventar · Raumplan (raumplan.html)
   Pop-up, Hervorhebung, Ziehen im Plan (F-65 bis F-69).
   Ändert nichts an htmx; verwendet fetch für die Pop-up-Inhalte. */
(function () {
  var plan = document.querySelector('[data-test="raumplan"]');
  if (!plan) return;

  function popu(ziel) {
    var bereich = document.getElementById('platz-popup');
    var grund = ziel.getAttribute('data-pfad');
    if (!grund) return;
    fetch(grund, { headers: { 'HX-Request': 'true' } })
      .then(function (antwort) {
        if (!antwort.ok) {
          bereich.hidden = true;
          return null;
        }
        return antwort.text();
      })
      .then(function (html) {
        if (html === null) {
          return;
        }
        bereich.innerHTML = html;
        bereich.hidden = false;
        plan.querySelectorAll('.orte')
          .forEach(function (knopf) { knopf.removeAttribute('aria-expanded'); });
        ziel.setAttribute('aria-expanded', 'true');
      })
      .catch(function () { bereich.hidden = true; });
  }

  plan.querySelectorAll('.orte')
    .forEach(function (knopf) {
      knopf.addEventListener('click', function () { popu(knopf); });
    });

  document.addEventListener('click', function (ereignis) {
    var schliessen = ereignis.target.closest('[data-test="popup-schliessen"]');
    if (schliessen) {
      var bereich = document.getElementById('platz-popup');
      if (bereich) bereich.hidden = true;
      return;
    }
    if (ereignis.target.closest('.popup-bereich') || ereignis.target.closest('.orte')) return;
    var bereich2 = document.getElementById('platz-popup');
    if (bereich2) bereich2.hidden = true;
  });

  document.addEventListener('keydown', function (ereignis) {
    if (ereignis.key === 'Escape') {
      var bereich = document.getElementById('platz-popup');
      if (bereich) bereich.hidden = true;
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
