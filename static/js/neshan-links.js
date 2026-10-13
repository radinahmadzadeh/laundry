// Links marked data-neshan="lat,lng" point at nshn.ir, which opens the Neshan app on Android
// and the Neshan web map elsewhere. On iPhone/iPad the app has its own neshan:// scheme, so try
// that first and fall back to the web link if the app is not installed.
(function () {
    'use strict';
    var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
        (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    if (!isIOS) return;

    document.addEventListener('click', function (event) {
        var link = event.target.closest && event.target.closest('a[data-neshan]');
        if (!link) return;
        event.preventDefault();
        var webUrl = link.href;
        var left = false;
        function markLeft() { left = true; }
        document.addEventListener('visibilitychange', markLeft, { once: true });
        window.addEventListener('pagehide', markLeft, { once: true });
        window.location.href = 'neshan://?ll=' + link.getAttribute('data-neshan');
        setTimeout(function () {
            if (!left && !document.hidden) window.location.href = webUrl;
        }, 1400);
    });
})();
