// Postal code fields marked data-postal-lookup="<url>" are checked as soon as 10 digits are typed.
// A status line appears under the field; when the code is found, a "postal:found" event
// (detail: lat, lng, address) is sent from the field so the page can move its map pin.
(function () {
    'use strict';

    var STYLE = [
        '.pl-status{display:flex;align-items:flex-start;gap:7px;margin:-6px 2px 12px;font-size:11.5px;font-weight:700;line-height:1.7;text-align:right;animation:plIn .3s ease;}',
        '.pl-status[hidden]{display:none;}',
        '.pl-status svg{flex:none;width:16px;height:16px;margin-top:2px;}',
        '.pl-status.checking{color:#64748b;}',
        '.pl-status.found{color:#047857;}',
        '.pl-status.not_found{color:#e11d48;}',
        '.pl-status small{display:block;font-weight:500;color:#64748b;}',
        '.pl-spin{width:14px;height:14px;margin-top:3px;border-radius:50%;border:2px solid #cbd5e1;border-top-color:#0891b2;animation:plSpin .7s linear infinite;flex:none;}',
        '.pl-ok{border-color:#34d399 !important;box-shadow:0 0 0 3px rgba(52,211,153,.2) !important;}',
        '@keyframes plSpin{to{transform:rotate(360deg);}}',
        '@keyframes plIn{from{opacity:0;transform:translateY(-4px);}to{opacity:1;transform:none;}}',
        '@media (prefers-reduced-motion:reduce){.pl-status{animation:none;}}'
    ].join('');
    var ICON_OK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.8"/></svg>';
    var ICON_BAD = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/></svg>';

    function normalize(value) {
        return String(value || '')
            .replace(/[۰-۹]/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'.indexOf(d); })
            .replace(/[٠-٩]/g, function (d) { return '٠١٢٣٤٥٦٧٨٩'.indexOf(d); })
            .replace(/[\s\-‌]/g, '');
    }

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function statusFor(input) {
        var el = input.nextElementSibling;
        if (el && el.classList.contains('pl-status')) return el;
        el = document.createElement('div');
        el.className = 'pl-status';
        el.setAttribute('aria-live', 'polite');
        el.hidden = true;
        input.insertAdjacentElement('afterend', el);
        return el;
    }

    function show(input, state, html) {
        var el = statusFor(input);
        el.className = 'pl-status ' + state;
        el.innerHTML = html;
        el.hidden = !html;
    }

    function reset(input) {
        input.classList.remove('pl-ok');
        input.setCustomValidity('');
        show(input, '', '');
    }

    function check(input) {
        var code = normalize(input.value);
        if (code.length !== 10 || !/^\d+$/.test(code)) { reset(input); return; }
        if (input.dataset.plChecked === code) return;
        input.dataset.plChecked = code;
        var seq = (input._plSeq || 0) + 1;
        input._plSeq = seq;
        input.setCustomValidity('');
        show(input, 'checking', '<span class="pl-spin" aria-hidden="true"></span><span>در حال بررسی کد پستی…</span>');
        fetch(input.dataset.postalLookup + '?code=' + encodeURIComponent(code), { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (seq !== input._plSeq) return;
                if (data.status === 'found') {
                    input.classList.add('pl-ok');
                    show(input, 'found', ICON_OK + '<span>کد پستی تأیید شد؛ موقعیت آن روی نقشه گذاشته شد.' +
                        (data.address ? '<small>' + escapeHtml(data.address) + '</small>' : '') + '</span>');
                    input.dispatchEvent(new CustomEvent('postal:found', { bubbles: true, detail: data }));
                } else if (data.status === 'not_found' || data.status === 'invalid') {
                    input.classList.remove('pl-ok');
                    input.setCustomValidity(data.message || 'این کد پستی پیدا نشد.');
                    show(input, 'not_found', ICON_BAD + '<span>' + escapeHtml(data.message || 'این کد پستی پیدا نشد.') + '</span>');
                } else {
                    // The service could not answer: say nothing and let the customer continue.
                    reset(input);
                }
            })
            .catch(function () { if (seq === input._plSeq) reset(input); });
    }

    var timers = new WeakMap();
    document.addEventListener('input', function (event) {
        var input = event.target;
        if (!input.matches || !input.matches('input[data-postal-lookup]')) return;
        if (!document.getElementById('pl-style')) {
            var style = document.createElement('style');
            style.id = 'pl-style';
            style.textContent = STYLE;
            document.head.appendChild(style);
        }
        if (normalize(input.value) !== input.dataset.plChecked) { input.dataset.plChecked = ''; reset(input); }
        clearTimeout(timers.get(input));
        timers.set(input, setTimeout(function () { check(input); }, 350));
    });
})();
