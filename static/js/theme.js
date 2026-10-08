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
  /** Dark mode controller with enhanced transitions */
  if (getCookie('dark-mode') === "true") {
    document.documentElement.setAttribute('data-theme', 'dark');
  }

  $('[data-toggle="dark-mode"]').on('click', function () {
    const isDarkMode = getCookie('dark-mode') === "true";
    const newTheme = isDarkMode ? 'light' : 'dark';
    const $icon = $(this).find('i');

    // Add rotation animation to icon
    $icon.css('transform', 'rotate(360deg)');

    setTimeout(function() {
      $icon.css('transform', 'rotate(0deg)');
    }, 300);

    // Toggle theme
    if (isDarkMode) {
      setCookie('dark-mode', 'false', 30);
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      setCookie('dark-mode', 'true', 30);
      document.documentElement.setAttribute('data-theme', 'dark');
    }

    // Add slight page transition effect
    $('body').css('opacity', '0.95');
    setTimeout(function() {
      $('body').css('opacity', '1');
    }, 150);
  });

  // Optional: Add keyboard shortcut (Ctrl/Cmd + D) for dark mode toggle
  $(document).on('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'd') {
      e.preventDefault();
      $('[data-toggle="dark-mode"]').trigger('click');
    }
  });
});
