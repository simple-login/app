(function () {
  // only enable on prod
  if (!window.location.host.endsWith('simplelogin.io')) {
    console.log("Analytics should only be enabled in prod");
    return;
  }

  if (store.get('analytics-ignore') === 't') {
    console.log("Analytics is disabled");
    return;
  }

  console.log("init Analytics");

  // Add Plausible script
  // <script async defer data-domain="app.simplelogin.io" src="https://plausible.simplelogin.io/js/index.js"></script>
  var plausibleScript = document.createElement('script');
  plausibleScript.defer = 1;
  plausibleScript.async = 1;
  plausibleScript.dataset.domain = "app.simplelogin.io";
  plausibleScript.src = 'https://plausible.simplelogin.io/js/index.js';

  var ins = document.getElementsByTagName('script')[0];
  ins.parentNode.insertBefore(plausibleScript, ins);

})();