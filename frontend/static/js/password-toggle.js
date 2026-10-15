// Customer login and sign-up: the "show password" checkbox.

(function () {
  [['login-password', 'show-login-password'], ['password', 'show-register-password']].forEach(function (ids) {
    const password = document.getElementById(ids[0]);
    const toggle = document.getElementById(ids[1]);
    if (password && toggle) {
      toggle.addEventListener('change', function () {
        password.type = toggle.checked ? 'text' : 'password';
      });
    }
  });
})();
