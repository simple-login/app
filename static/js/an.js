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
  // <script async defer data-domain="app.simplelogin.io,everything.simplelogin.com" src="/p.outbound.js"></script>
  var plausibleScript = document.createElement('script');
  plausibleScript.defer = 1;
  plausibleScript.async = 1;
  plausibleScript.dataset.api = "/p/api/event";
  plausibleScript.dataset.domain = "app.simplelogin.io,everything.simplelogin.com";
  plausibleScript.src = '/p.outbound.js';

  var ins = document.getElementsByTagName('script')[0];
  ins.parentNode.insertBefore(plausibleScript, ins);

  // allow custom event
  window.plausible = window.plausible || function() { (window.plausible.q = window.plausible.q || []).push(arguments) }

})();