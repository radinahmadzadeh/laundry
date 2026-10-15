// Postal code check for fields marked data-postal-lookup="<lookup url>".
//
// Under the field: a 10-segment meter that fills as digits are typed, then a card that asks the
// customer to confirm the code belongs to the address they picked on the map. When map.ir answers
// (see orders/postal.py), the card shows the post office's own address for the code and how far it
// is from the map pin; otherwise it shows the pin's address. Until the customer confirms, the field
// is invalid (setCustomValidity), so submitting stops on it with the form-error toast.
//
// Optional data attributes on the field:
//   data-lat / data-lng   ids of the hidden inputs holding the map pin
//   data-addr             id of the element (or textarea) showing the pin's address
// The page sends document events:
//   "postal:pin-moved" (detail.latId)   the pin moved: ask again
// and listens for "postal:found" (detail: lat, lng, address) on the field to move its pin.
// window.PostalCheck.markConfirmed(field, addressText) marks a saved, already-known code as confirmed.
(function () {
    'use strict';

    var STYLE = [
        '.pc{margin:-6px 0 14px;text-align:right;}',
        '.pc-meter{display:flex;gap:3px;padding:0 6px;direction:ltr;}',
        '.pc-meter i{flex:1;height:4px;border-radius:4px;background:#e2e8f0;transition:background .25s ease,transform .25s ease;}',
        '.pc-meter i:nth-child(6){margin-left:7px;}',
        '.pc-meter i.on{background:linear-gradient(90deg,#22d3ee,#0891b2);}',
        '.pc[data-state="confirmed"] .pc-meter i.on{background:#10b981;}',
        '.pc[data-state="bad"] .pc-meter i.on{background:#fb7185;}',
        '.pc-card{margin-top:10px;border-radius:18px;border:1px solid #e2e8f0;background:#fff;padding:14px;box-shadow:0 14px 30px -22px rgba(15,23,42,.35);animation:pcIn .35s cubic-bezier(.2,.8,.2,1);}',
        '.pc-card[hidden]{display:none;}',
        '.pc-head{display:flex;align-items:center;gap:10px;}',
        '.pc-ico{flex:none;width:36px;height:36px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#fff;background:linear-gradient(140deg,#22d3ee,#0e7490);}',
        '.pc-ico svg{width:19px;height:19px;}',
        '.pc-code{font-size:16px;font-weight:900;letter-spacing:.06em;color:#0f172a;direction:ltr;}',
        '.pc-sub{display:block;font-size:11px;font-weight:700;color:#64748b;}',
        '.pc-addr{margin-top:12px;padding:10px 12px;border-radius:12px;background:#f8fafc;border:1px dashed #cbd5e1;font-size:12.5px;line-height:1.9;color:#0f172a;font-weight:700;}',
        '.pc-addr small{display:block;font-size:10.5px;font-weight:800;color:#64748b;margin-bottom:2px;}',
        '.pc-addr.empty{color:#94a3b8;font-weight:600;}',
        '.pc-dist{display:flex;align-items:center;gap:6px;margin-top:8px;font-size:11.5px;font-weight:800;}',
        '.pc-dist.near{color:#047857;} .pc-dist.mid{color:#b45309;} .pc-dist.far{color:#e11d48;}',
        '.pc-q{margin-top:12px;font-size:13px;font-weight:900;color:#0f172a;}',
        '.pc-actions{display:flex;gap:8px;margin-top:10px;}',
        '.pc-actions button{flex:1;min-height:44px;border-radius:12px;font:inherit;font-size:13px;font-weight:900;cursor:pointer;transition:transform .15s ease,box-shadow .2s ease,opacity .2s ease;}',
        '.pc-actions button:active{transform:scale(.97);}',
        '.pc-actions button:disabled{opacity:.45;cursor:not-allowed;}',
        '.pc-yes{border:0;color:#fff;background:linear-gradient(120deg,#22d3ee,#0891b2 55%,#0e7490);box-shadow:0 10px 20px -12px rgba(8,145,178,.7);}',
        '.pc-no{border:1px solid #e2e8f0;background:#fff;color:#334155;}',
        '.pc-hint{margin-top:10px;font-size:11.5px;line-height:1.8;color:#64748b;}',
        '.pc-card.checking .pc-ico{background:#f1f5f9;color:#0891b2;}',
        '.pc-spin{width:18px;height:18px;border-radius:50%;border:2.5px solid #cbd5e1;border-top-color:#0891b2;animation:pcSpin .7s linear infinite;}',
        '.pc-card.bad{border-color:#fecdd3;background:#fff1f2;}',
        '.pc-card.bad .pc-ico{background:linear-gradient(140deg,#fb7185,#e11d48);}',
        '.pc-card.bad .pc-q{color:#be123c;}',
        '.pc-card.ok{display:flex;align-items:flex-start;gap:10px;border-color:#a7f3d0;background:#ecfdf5;padding:11px 13px;}',
        '.pc-card.ok .pc-ico{width:30px;height:30px;border-radius:10px;background:linear-gradient(140deg,#34d399,#059669);}',
        '.pc-card.ok .pc-ico path{stroke-dasharray:30;stroke-dashoffset:30;animation:pcCheck .5s .1s ease forwards;}',
        '.pc-ok-text{flex:1;min-width:0;font-size:12px;line-height:1.8;color:#065f46;font-weight:800;}',
        '.pc-ok-text span{display:block;font-weight:600;color:#047857;}',
        '.pc-change{flex:none;border:0;background:transparent;color:#0e7490;font:inherit;font-size:11.5px;font-weight:900;cursor:pointer;padding:4px 2px;}',
        '.pc-input-ok{border-color:#34d399 !important;box-shadow:0 0 0 3px rgba(52,211,153,.2) !important;}',
        '@keyframes pcIn{from{opacity:0;transform:translateY(-6px) scale(.98);}to{opacity:1;transform:none;}}',
        '@keyframes pcSpin{to{transform:rotate(360deg);}}',
        '@keyframes pcCheck{to{stroke-dashoffset:0;}}',
        '@media (prefers-reduced-motion:reduce){.pc-card,.pc-card.ok .pc-ico path{animation:none;stroke-dashoffset:0;}.pc-spin{animation-duration:2s;}}'
    ].join('');

    var ICON_MAIL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M4 7l8 6 8-6"/></svg>';
    var ICON_BAD = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 7v6M12 17h.01"/></svg>';
    var ICON_OK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5.5 12.5l4 4 9-9"/></svg>';
    var ICON_PIN = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.4"/></svg>';
    var ASK = 'لطفاً تأیید کنید که این کد پستی مال همین آدرس است.';

    function normalize(value) {
        return String(value || '')
            .replace(/[۰-۹]/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'.indexOf(d); })
            .replace(/[٠-٩]/g, function (d) { return '٠١٢٣٤٥٦٧٨٩'.indexOf(d); })
            .replace(/[\s\-‌]/g, '');
    }
    function fa(text) { return String(text).replace(/\d/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'[d]; }); }
    function pretty(code) { return '<bdi dir="ltr">' + fa(code.slice(0, 5) + '-' + code.slice(5)) + '</bdi>'; }
    function esc(text) { var d = document.createElement('div'); d.textContent = text; return d.innerHTML; }

    function ensureStyle() {
        if (document.getElementById('pc-style')) return;
        var style = document.createElement('style');
        style.id = 'pc-style';
        style.textContent = STYLE;
        document.head.appendChild(style);
    }

    function box(input) {
        if (input._pc) return input._pc;
        ensureStyle();
        var el = document.createElement('div');
        el.className = 'pc';
        el.innerHTML = '<div class="pc-meter" aria-hidden="true">' + new Array(11).join('<i></i>') + '</div>' +
            '<div class="pc-card" aria-live="polite" hidden></div>';
        input.insertAdjacentElement('afterend', el);
        el.querySelector('.pc-card').addEventListener('click', function (e) {
            var btn = e.target.closest('button[data-act]');
            if (btn) act(input, btn.getAttribute('data-act'));
        });
        input._pc = el;
        return el;
    }

    // The pin on the page's map, and its readable address.
    function pin(input) {
        var lat = document.getElementById(input.dataset.lat || ''), lng = document.getElementById(input.dataset.lng || '');
        if (!lat || !lng || !lat.value || !lng.value) return null;
        return { lat: parseFloat(lat.value), lng: parseFloat(lng.value) };
    }
    function pinAddress(input) {
        var el = document.getElementById(input.dataset.addr || '');
        if (!el) return '';
        if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') return el.value.replace(/[،,\s]+$/, '').trim();
        var state = el.closest('[data-state]');
        return state && state.getAttribute('data-state') !== 'found' ? '' : el.textContent.trim();
    }
    function distance(a, b) {
        var R = 6371000, rad = Math.PI / 180;
        var dLat = (b.lat - a.lat) * rad, dLng = (b.lng - a.lng) * rad;
        var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
        return 2 * R * Math.asin(Math.sqrt(h));
    }
    function meters(m) { return m < 1000 ? fa(Math.round(m / 10) * 10) + ' متر' : fa((m / 1000).toFixed(1)).replace('.', '٫') + ' کیلومتر'; }

    function meter(input, code) {
        var bars = box(input).querySelectorAll('.pc-meter i');
        for (var i = 0; i < bars.length; i++) bars[i].classList.toggle('on', i < code.length);
    }

    function setState(input, state, html, cls) {
        var el = box(input), card = el.querySelector('.pc-card');
        el.setAttribute('data-state', state);
        card.className = 'pc-card' + (cls ? ' ' + cls : '');
        card.innerHTML = html;
        card.hidden = !html;
        input.classList.toggle('pc-input-ok', state === 'confirmed');
        if (state === 'confirmed') { input.classList.remove('fe-invalid'); input.removeAttribute('aria-invalid'); }
    }

    // ---------- What the card says ----------
    function render(input) {
        var s = input._pcData;
        if (!s) return;
        var code = s.code;
        if (s.confirmed) {
            setState(input, 'confirmed',
                '<span class="pc-ico">' + ICON_OK + '</span>' +
                '<div class="pc-ok-text">کد پستی ' + pretty(code) + ' برای این آدرس تأیید شد.' +
                (s.confirmedText ? '<span>' + esc(s.confirmedText) + '</span>' : '') + '</div>' +
                '<button type="button" class="pc-change" data-act="change">تغییر</button>', 'ok');
            input.setCustomValidity('');
            return;
        }
        if (s.status === 'checking') {
            setState(input, 'checking', '<div class="pc-head"><span class="pc-ico"><span class="pc-spin"></span></span>' +
                '<div><span class="pc-code">' + pretty(code) + '</span><span class="pc-sub">در حال بررسی کد پستی…</span></div></div>', 'checking');
            input.setCustomValidity(ASK);
            return;
        }
        if (s.status === 'bad') {
            setState(input, 'bad', '<div class="pc-head"><span class="pc-ico">' + ICON_BAD + '</span>' +
                '<div><span class="pc-code">' + pretty(code) + '</span><span class="pc-sub">' + esc(s.message) + '</span></div></div>' +
                '<p class="pc-hint">ارقام را با قبض آب، برق یا گاز دوباره مقایسه کنید؛ کد پستی ۱۰ رقم است و روی همه‌ی قبض‌ها چاپ می‌شود.</p>', 'bad');
            input.setCustomValidity(s.message);
            return;
        }

        var here = pin(input), official = s.status === 'found', html, hasPin = !!here;
        var head = '<div class="pc-head"><span class="pc-ico">' + ICON_MAIL + '</span><div><span class="pc-code">' + pretty(code) + '</span>' +
            '<span class="pc-sub">' + (official ? 'این کد در سامانه پست پیدا شد' : 'کد پستی ۱۰ رقمی') + '</span></div></div>';
        if (official) {
            html = head + '<div class="pc-addr"><small>آدرس ثبت‌شده برای این کد پستی</small>' + esc(s.address || 'بدون آدرس متنی؛ موقعیتش روی نقشه مشخص است') + '</div>';
            if (here) {
                var d = distance(here, s);
                var level = d <= 150 ? 'near' : (d <= 600 ? 'mid' : 'far');
                var words = level === 'near' ? 'با نقطه‌ای که روی نقشه زدید یکی است.' :
                    'با نقطه‌ای که روی نقشه زدید حدود ' + meters(d) + ' فاصله دارد' + (level === 'far' ? '؛ یکی از این دو اشتباه است.' : '.');
                html += '<div class="pc-dist ' + level + '">' + ICON_PIN + '<span>' + words + '</span></div>';
            }
            html += '<p class="pc-q">آدرس شما همین است؟</p>' +
                '<div class="pc-actions"><button type="button" class="pc-yes" data-act="yes">بله، همین است</button>' +
                '<button type="button" class="pc-no" data-act="no">نه، اصلاحش می‌کنم</button></div>';
            if (here && distance(here, s) > 150) html += '<p class="pc-hint">با «بله»، نقطه‌ی روی نقشه به محل این کد پستی منتقل می‌شود.</p>';
        } else {
            var text = pinAddress(input);
            html = head + '<div class="pc-addr' + (text ? '' : ' empty') + '"><small>آدرس نقطه‌ای که روی نقشه انتخاب کردید</small>' +
                (text ? esc(text) : (hasPin ? 'در حال پیدا کردن آدرس این نقطه…' : 'هنوز نقطه‌ای روی نقشه انتخاب نشده است.')) + '</div>' +
                '<p class="pc-q">این کد پستی مال همین آدرس است؟</p>' +
                '<div class="pc-actions"><button type="button" class="pc-yes" data-act="yes"' + (hasPin ? '' : ' disabled') + '>بله، درست است</button>' +
                '<button type="button" class="pc-no" data-act="no">نه، اصلاحش می‌کنم</button></div>' +
                (hasPin ? '' : '<p class="pc-hint">اول محل خانه را روی نقشه بزنید تا آدرسش را ببینید و کد پستی را با آن مقایسه کنید.</p>');
        }
        if (s.retry) html += '<p class="pc-hint">کد پستی را دوباره وارد کنید یا نقطه را روی نقشه جابه‌جا کنید.</p>';
        setState(input, 'ask', html, '');
        input.setCustomValidity(hasPin || official ? ASK : 'لطفاً اول موقعیت خود را روی نقشه انتخاب کنید.');
    }

    function act(input, what) {
        var s = input._pcData;
        if (!s) return;
        if (what === 'yes') {
            s.confirmed = true;
            s.retry = false;
            if (s.status === 'found') {
                s.confirmedText = s.address || pinAddress(input);
                var here = pin(input);
                if (!here || distance(here, s) > 150) {
                    s.movingPin = true;
                    input.dispatchEvent(new CustomEvent('postal:found', { bubbles: true, detail: { lat: s.lat, lng: s.lng, address: s.address || '' } }));
                    s.movingPin = false;
                }
            } else {
                s.confirmedText = pinAddress(input);
            }
            s.confirmedAt = pinKey(input);
        } else if (what === 'no') {
            s.retry = true;
            input.focus();
            input.select();
        } else if (what === 'change') {
            s.confirmed = false;
        }
        render(input);
    }

    function pinKey(input) { var p = pin(input); return p ? p.lat.toFixed(5) + ',' + p.lng.toFixed(5) : ''; }

    function check(input) {
        var code = normalize(input.value);
        meter(input, code);
        if (!/^\d*$/.test(code)) {
            input._pcData = { code: code, status: 'bad', message: 'کد پستی فقط از رقم تشکیل می‌شود.' };
            return render(input);
        }
        if (code.length !== 10) {
            input._pcData = null;
            input.setCustomValidity(code.length ? 'کد پستی باید ۱۰ رقم باشد.' : '');
            setState(input, code.length ? 'typing' : '', '', '');
            return;
        }
        if (input._pcData && input._pcData.code === code) return render(input);
        if (/^(\d)\1{9}$/.test(code)) {
            input._pcData = { code: code, status: 'bad', message: 'این کد پستی معتبر به نظر نمی‌رسد.' };
            return render(input);
        }
        var s = input._pcData = { code: code, status: 'checking' };
        render(input);
        if (!input.dataset.postalLookup) { s.status = 'unavailable'; return render(input); }
        fetch(input.dataset.postalLookup + '?code=' + encodeURIComponent(code), { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (input._pcData !== s) return;
                if (data.status === 'found') { s.status = 'found'; s.lat = data.lat; s.lng = data.lng; s.address = data.address || ''; }
                else if (data.status === 'not_found' || data.status === 'invalid') { s.status = 'bad'; s.message = data.message || 'این کد پستی در سامانه پست پیدا نشد.'; }
                else s.status = 'unavailable';
                render(input);
            })
            .catch(function () { if (input._pcData === s) { s.status = 'unavailable'; render(input); } });
    }

    var timers = new WeakMap();
    document.addEventListener('input', function (event) {
        var input = event.target;
        if (input.matches && input.matches('input[data-postal-lookup]')) {
            var code = normalize(input.value);
            meter(input, code);
            if (input._pcData && input._pcData.code !== code) { input._pcData = null; }
            clearTimeout(timers.get(input));
            timers.set(input, setTimeout(function () { check(input); }, code.length === 10 ? 120 : 300));
            return;
        }
        // An address textarea used as the pin's address changed: refresh any card showing it.
        if (input.id) refreshWhere(function (f) { return f.dataset.addr === input.id; });
    });

    function refreshWhere(test) {
        document.querySelectorAll('input[data-postal-lookup]').forEach(function (f) {
            if (f._pcData && test(f)) render(f);
        });
    }

    // The pin moved: a confirmed code must be confirmed again for the new place.
    document.addEventListener('postal:pin-moved', function (e) {
        var latId = e.detail && e.detail.latId;
        refreshWhere(function (f) {
            if (f.dataset.lat !== latId) return false;
            var s = f._pcData;
            if (s.confirmed && !s.movingPin && s.confirmedAt !== pinKey(f)) s.confirmed = false;
            return true;
        });
    });

    // Address previews update after a reverse lookup: keep the card's text in step.
    function watchAddresses() {
        document.querySelectorAll('input[data-postal-lookup][data-addr]').forEach(function (f) {
            var el = document.getElementById(f.dataset.addr);
            if (!el || el.tagName === 'TEXTAREA' || el._pcWatched) return;
            el._pcWatched = true;
            new MutationObserver(function () { if (f._pcData && !f._pcData.confirmed) render(f); })
                .observe(el.closest('[data-state]') || el, { childList: true, characterData: true, subtree: true, attributes: true });
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', watchAddresses); else watchAddresses();

    window.PostalCheck = {
        // A saved address's postal code was already confirmed by the customer.
        markConfirmed: function (input, text) {
            var code = normalize(input.value);
            if (code.length !== 10) return;
            box(input);
            meter(input, code);
            input._pcData = { code: code, status: 'unavailable', confirmed: true, confirmedText: text || '', confirmedAt: pinKey(input) };
            render(input);
        },
        reset: function (input) {
            input._pcData = null;
            input.setCustomValidity('');
            if (input._pc) { meter(input, ''); setState(input, '', '', ''); }
        }
    };
})();
