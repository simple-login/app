let setCookie = function(name, value, days) {
    if (!name || !value) return false;
    let expires = '';
    let secure = '';
    if (location.protocol === 'https:') secure = 'Secure; ';

    if (days) {
      let date = new Date();
      date.setTime(date.getTime() + (days * 24*60*60*1000));
      expires = 'Expires=' + date.toUTCString() + '; ';
    }

    document.cookie = name + '=' + value + '; ' +
                      expires +
                      secure +
                      'sameSite=Lax; ' +
                      'domain=' + window.location.hostname + '; ' +
                      'path=/';
    return true;
  }

let getCookie = function(name) {
  let match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
  if (match) return match[2];
}

$(document).ready(function() {
  /** Dark mode controller */
  if (getCookie('dark-mode') === "true") {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
  $('[data-toggle="dark-mode"]').on('click', function () {
    if (getCookie('dark-mode') === "true") {
      setCookie('dark-mode', 'false', 30);
      return document.documentElement.setAttribute('data-theme', 'light')
    }
    setCookie('dark-mode', 'true', 30);
    document.documentElement.setAttribute('data-theme', 'dark')
  })
});
