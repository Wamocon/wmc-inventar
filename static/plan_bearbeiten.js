/* WMC Inventar · Plan pflegen (plan_bearbeiten.html)
   Ziehen von Plätzen und Räumen auf den Grundriss (F-67).
   Position wird in Prozent vom Mittelpunkt gespeichert.
   Bei Seitenaufruf setzt das Skript die Initial-Position aus
   data-x/data-y in style.left/style.top um, damit keine
   Inline-Styles im HTML stehen müssen (CSP style-src 'self'). */
(function () {
  var flaeche = document.querySelector('[data-test="plan-flaeche"]');
  if (!flaeche) return;
  var token = document.querySelector('meta[name="csrf-token"]').content;
  var planId = document.querySelector('[data-test="raumplan-pflegen"]').getAttribute('data-id');
  var pfad = '/arbeitsplaetze/plan/' + planId + '/bearbeiten/';

  // Initial-Position aus data-x/data-y setzen (statt Inline-Style im HTML)
  flaeche.querySelectorAll('.orte').forEach(function (knopf) {
    var x = knopf.getAttribute('data-x');
    var y = knopf.getAttribute('data-y');
    if (x !== null && y !== null) {
      knopf.style.left = x + '%';
      knopf.style.top = y + '%';
    }
  });

  function speichern(ortId, x, y) {
    var formular = document.createElement('form');
    formular.method = 'post';
    formular.action = pfad;
    formular.style.display = 'none';
    function feld(name, wert) {
      var input = document.createElement('input');
      input.type = 'hidden';
      input.name = name;
      input.value = wert;
      formular.appendChild(input);
    }
    feld('csrfmiddlewaretoken', token);
    feld('ort', ortId);
    feld('x', x);
    feld('y', y);
    document.body.appendChild(formular);
    formular.submit();
  }

  function koordinaten(ereignis, ziel) {
    var rechteck = ziel.getBoundingClientRect();
    var x = ((ereignis.clientX - rechteck.left) / rechteck.width) * 100;
    var y = ((ereignis.clientY - rechteck.top) / rechteck.height) * 100;
    x = Math.max(0, Math.min(100, Math.round(x * 10) / 10));
    y = Math.max(0, Math.min(100, Math.round(y * 10) / 10));
    return { x: x, y: y };
  }

  flaeche.addEventListener('click', function (ereignis) {
    if (ereignis.target.closest('.orte')) return;
    var gezogen = window.__gezogener_ort;
    if (!gezogen) return;
    var punkte = koordinaten(ereignis, flaeche);
    var knopf = flaeche.querySelector('[data-ort-id="' + gezogen.id + '"]');
    if (knopf) {
      knopf.style.left = punkte.x + '%';
      knopf.style.top = punkte.y + '%';
      knopf.setAttribute('data-x', String(punkte.x));
      knopf.setAttribute('data-y', String(punkte.y));
    } else {
      var knopf_neu = document.createElement('button');
      knopf_neu.type = 'button';
      knopf_neu.className = 'orte platz';
      knopf_neu.setAttribute('data-test', 'platz');
      knopf_neu.setAttribute('data-id', gezogen.kennung);
      knopf_neu.setAttribute('data-ort-id', gezogen.id);
      knopf_neu.setAttribute('data-x', String(punkte.x));
      knopf_neu.setAttribute('data-y', String(punkte.y));
      knopf_neu.style.left = punkte.x + '%';
      knopf_neu.style.top = punkte.y + '%';
      var name = document.createElement('span');
      name.className = 'orts-name';
      name.textContent = gezogen.kennung;
      knopf_neu.appendChild(name);
      flaeche.querySelector('[data-test="plan-orte"]').appendChild(knopf_neu);
    }
    speichern(gezogen.id, punkte.x, punkte.y);
  });

  flaeche.querySelectorAll('.ohne-position-liste .zeile').forEach(function (eintrag) {
    eintrag.addEventListener('dragstart', function (ereignis) {
      var id = eintrag.getAttribute('data-ort-id');
      var kennung = eintrag.getAttribute('data-kennung');
      window.__gezogener_ort = { id: id, kennung: kennung };
      ereignis.dataTransfer.effectAllowed = 'move';
      ereignis.dataTransfer.setData('text/plain', kennung);
    });
  });
})();
