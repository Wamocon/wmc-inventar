/* WMC Inventar · Import (import.html)
   Sobald eine .xlsx gewählt ist, geht sie hoch: Erst dann stehen ihre Blätter fest (F-80).
   Ohne Skript macht das der Knopf „Weiter“. */
(function () {
  var formular = document.querySelector('[data-test="import-dateiformular"]');
  if (!formular) return;
  var datei = formular.querySelector('input[type=file]');
  datei.addEventListener('change', function () {
    if (datei.files.length) formular.submit();
  });
})();
