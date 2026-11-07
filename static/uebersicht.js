/* WMC Inventar · Übersicht (uebersicht.html)
   Anteile im Statusbalken aus data-anteil setzen (statt Inline-Style, CSP style-src 'self'). */
(function () {
  document.querySelectorAll('.stock-segment[data-anteil]').forEach(function (teil) {
    teil.style.flexGrow = teil.getAttribute('data-anteil');
  });
})();
