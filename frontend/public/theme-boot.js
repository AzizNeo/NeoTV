// Runs before first paint (blocking <script> in <head>): apply the saved theme so the page never
// flashes the wrong colours. External file on purpose — works under a strict CSP (script-src 'self').
(function () {
  var choice = 'system';
  try {
    choice = localStorage.getItem('neotv.theme') || 'system';
  } catch {
    /* storage blocked: follow the system */
  }
  var dark = choice === 'dark' || (choice !== 'light' && !matchMedia('(prefers-color-scheme: light)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
})();
