// Replaces the browser's own "Please fill out this field" bubble with a Persian toast
// and a highlight on the field. Works for every form on the page, with no per-form setup.
(function () {
    'use strict';

    var STYLE = [
        '.fe-toast{position:fixed;left:50%;top:calc(env(safe-area-inset-top,0px) + 16px);z-index:2147483000;width:min(420px,calc(100% - 24px));',
        'display:flex;align-items:center;gap:12px;padding:12px 14px 14px;border-radius:18px;background:#fff;color:#0f172a;direction:rtl;text-align:right;',
        'font-family:inherit;box-shadow:0 0 0 1px rgba(225,29,72,.14),0 22px 48px -20px rgba(15,23,42,.45);overflow:hidden;',
        'transform:translate(-50%,-140%);opacity:0;transition:transform .5s cubic-bezier(.3,1.4,.5,1),opacity .25s ease;}',
        '.fe-toast.show{transform:translate(-50%,0);opacity:1;}',
        '.fe-toast-icon{flex:none;width:38px;height:38px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#fff;',
        'background:linear-gradient(140deg,#fb7185,#e11d48);box-shadow:0 10px 18px -10px rgba(225,29,72,.8);}',
        '.fe-toast.show .fe-toast-icon{animation:feIcon .6s .15s cubic-bezier(.3,1.6,.5,1) both;}',
        '.fe-toast-icon svg{width:20px;height:20px;}',
        '.fe-toast-body{flex:1;min-width:0;}',
        '.fe-toast-title{display:block;font-size:11px;font-weight:800;color:#e11d48;margin-bottom:2px;}',
        '.fe-toast-msg{display:block;font-size:13.5px;font-weight:800;line-height:1.7;}',
        '.fe-toast-close{flex:none;width:32px;height:32px;border-radius:10px;border:0;background:transparent;color:#94a3b8;font-size:20px;line-height:1;cursor:pointer;}',
        '.fe-toast-close:hover{background:#f1f5f9;color:#475569;}',
        '.fe-toast-bar{position:absolute;right:0;left:0;bottom:0;height:3px;background:linear-gradient(90deg,#fda4af,#e11d48);transform-origin:right;}',
        '.fe-toast.show .fe-toast-bar{animation:feBar var(--fe-time,4500ms) linear forwards;}',
        '.fe-invalid{border-color:#fb7185 !important;box-shadow:0 0 0 3px rgba(251,113,133,.28) !important;animation:feShake .42s ease;}',
        '@keyframes feIcon{0%{transform:scale(.3) rotate(-20deg);}100%{transform:none;}}',
        '@keyframes feBar{from{transform:scaleX(1);}to{transform:scaleX(0);}}',
        '@keyframes feShake{0%,100%{transform:translateX(0);}20%{transform:translateX(-6px);}40%{transform:translateX(5px);}60%{transform:translateX(-3px);}80%{transform:translateX(2px);}}',
        '@media (prefers-reduced-motion:reduce){.fe-toast{transition:opacity .2s ease;}.fe-toast.show .fe-toast-icon,.fe-invalid{animation:none;}.fe-toast.show .fe-toast-bar{animation:none;}}'
    ].join('');

    var SHOW_MS = 4500;
    var toast, msgEl, hideTimer, batchOpen = false;

    function faDigits(value) {
        return String(value).replace(/\d/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'[d]; });
    }

    function fieldName(el) {
        var text = el.getAttribute('aria-label') || '';
        if (!text && el.id) {
            var label = document.querySelector('label[for="' + el.id + '"]');
            if (label) text = label.textContent;
        }
        if (!text && el.closest('label')) text = el.closest('label').textContent;
        if (!text) text = el.getAttribute('placeholder') || '';
        text = text.replace(/\s+/g, ' ').replace(/[*:：]/g, '').replace(/\(.*?\)/g, '').trim();
        return text.length > 40 ? '' : text;
    }

    function messageFor(el) {
        var v = el.validity, name = fieldName(el);
        var quoted = name ? '«' + name + '»' : 'این بخش';
        if (v.customError) return el.validationMessage;
        if (v.valueMissing) {
            if (el.type === 'checkbox') return 'لطفاً ' + (name ? quoted + ' را ' : 'این گزینه را ') + 'تیک بزنید.';
            if (el.type === 'radio' || el.tagName === 'SELECT') return 'لطفاً یکی از گزینه‌های ' + quoted + ' را انتخاب کنید.';
            if (el.type === 'file') return 'لطفاً یک فایل برای ' + quoted + ' انتخاب کنید.';
            return 'لطفاً ' + quoted + ' را وارد کنید.';
        }
        if (v.tooShort) return quoted + ' باید حداقل ' + faDigits(el.minLength) + ' کاراکتر باشد.';
        if (v.tooLong) return quoted + ' حداکثر ' + faDigits(el.maxLength) + ' کاراکتر می‌تواند باشد.';
        if (v.typeMismatch) {
            if (el.type === 'email') return 'ایمیل واردشده درست نیست.';
            if (el.type === 'url') return 'نشانی واردشده درست نیست.';
            return quoted + ' درست وارد نشده است.';
        }
        if (v.badInput) return 'لطفاً برای ' + quoted + ' یک عدد درست وارد کنید.';
        if (v.rangeUnderflow) return quoted + ' نباید کمتر از ' + faDigits(el.min) + ' باشد.';
        if (v.rangeOverflow) return quoted + ' نباید بیشتر از ' + faDigits(el.max) + ' باشد.';
        if (v.stepMismatch) return quoted + ' مقدار مجاز ندارد.';
        if (v.patternMismatch) return el.title ? el.title : quoted + ' با قالب خواسته‌شده جور نیست.';
        return 'لطفاً ' + quoted + ' را بررسی کنید.';
    }

    function ensureToast() {
        if (toast) return;
        var style = document.createElement('style');
        style.textContent = STYLE;
        document.head.appendChild(style);
        toast = document.createElement('div');
        toast.className = 'fe-toast';
        toast.setAttribute('role', 'alert');
        toast.style.setProperty('--fe-time', SHOW_MS + 'ms');
        toast.innerHTML =
            '<span class="fe-toast-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M12 7v6"/><path d="M12 17h.01"/></svg></span>' +
            '<span class="fe-toast-body"><span class="fe-toast-title">یک مورد کامل نشده</span><span class="fe-toast-msg"></span></span>' +
            '<button type="button" class="fe-toast-close" aria-label="بستن">×</button>' +
            '<span class="fe-toast-bar" aria-hidden="true"></span>';
        msgEl = toast.querySelector('.fe-toast-msg');
        toast.querySelector('.fe-toast-close').addEventListener('click', hideToast);
        document.body.appendChild(toast);
    }

    function showToast(text) {
        ensureToast();
        msgEl.textContent = text;
        toast.classList.remove('show');
        void toast.offsetWidth;  // restart the slide-in and the countdown bar
        toast.classList.add('show');
        clearTimeout(hideTimer);
        hideTimer = setTimeout(hideToast, SHOW_MS);
    }

    function hideToast() {
        clearTimeout(hideTimer);
        if (toast) toast.classList.remove('show');
    }

    function markInvalid(el) {
        el.classList.remove('fe-invalid');
        void el.offsetWidth;
        el.classList.add('fe-invalid');
        el.setAttribute('aria-invalid', 'true');
    }

    // The browser fires "invalid" once per bad field on a submit attempt; speak only about the first one.
    document.addEventListener('invalid', function (event) {
        var el = event.target;
        event.preventDefault();
        markInvalid(el);
        if (batchOpen) return;
        batchOpen = true;
        setTimeout(function () { batchOpen = false; }, 0);
        showToast(messageFor(el));
        if (el.type !== 'hidden' && typeof el.focus === 'function') {
            el.focus({ preventScroll: true });
            el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
    }, true);

    function clearIfValid(event) {
        var el = event.target;
        if (!el.classList || !el.classList.contains('fe-invalid')) return;
        if (el.validity && el.validity.valid) {
            el.classList.remove('fe-invalid');
            el.removeAttribute('aria-invalid');
            if (!document.querySelector('.fe-invalid')) hideToast();
        }
    }
    document.addEventListener('input', clearIfValid, true);
    document.addEventListener('change', clearIfValid, true);
})();
