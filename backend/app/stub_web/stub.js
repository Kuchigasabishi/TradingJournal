(function () {
  // Not a global named `status`: window.status is a built-in string property and would swallow the element.
  var label = document.getElementById('status');
  fetch('/api/health')
    .then(function (response) { return response.json(); })
    .then(function (body) {
      label.textContent = 'API status: ' + body.status;
      console.info('harness: /api/health ->', body.status);
    })
    .catch(function (error) {
      label.textContent = 'API status: unreachable';
      console.error('harness: /api/health failed', error);
    });
})();
