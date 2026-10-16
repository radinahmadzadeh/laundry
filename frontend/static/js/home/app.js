// Home page behaviour. Values from the server (URLs, saved address, wallet balance,
// courier and status data) are written into the page by home/page_data.html.

/* ==== Delivery tabs, shop map and courier maps ==== */
function faNumber(n){ return Number(n || 0).toLocaleString('fa-IR'); }
var courierMaps = {};
var courierMarkers = {};

function positionDeliveryIndicator(orderId, btn){
    var track = document.getElementById('delivery-track-' + orderId);
    var indicator = document.getElementById('delivery-indicator-' + orderId);
    if(!track || !indicator) return;
    var trackRect = track.getBoundingClientRect();
    var btnRect = btn.getBoundingClientRect();
    indicator.style.width = btnRect.width + 'px';
    indicator.style.right = (trackRect.right - btnRect.right) + 'px';
}

function setDelivery(orderId, type, btn){
    var btnPickup = document.getElementById('btn-pickup-' + orderId);
    var btnCourier = document.getElementById('btn-courier-' + orderId);
    var secPickup = document.getElementById('section-pickup-' + orderId);
    var secCourier = document.getElementById('section-courier-' + orderId);

    btnPickup.classList.remove('active');
    btnCourier.classList.remove('active');

    if (type === 'pickup'){
        secPickup.classList.remove('hidden');
        secCourier.classList.add('hidden');
        btnPickup.classList.add('active');
    } else {
        secPickup.classList.add('hidden');
        secCourier.classList.remove('hidden');
        btnCourier.classList.add('active');
        initCourierMap(orderId);
    }

    positionDeliveryIndicator(orderId, btn || (type === 'pickup' ? btnPickup : btnCourier));
}

// The shop map loads its tiles only when the customer asks, so it never slows the page.
function loadShopMap(btn){
    var box = btn.closest('[data-shop-map]');
    if (!box || typeof L === 'undefined') return;
    var point = box.getAttribute('data-shop-map').split(',').map(parseFloat);
    box.innerHTML = '';
    var map = L.map(box, { gestureHandling: true, gestureHandlingOptions: { text: { touch: 'برای جابه‌جا کردن نقشه از دو انگشت استفاده کنید', scroll: 'برای بزرگ‌نمایی، Ctrl را نگه دارید و اسکرول کنید', scrollMac: 'برای بزرگ‌نمایی، ⌘ را نگه دارید و اسکرول کنید' } } }).setView(point, 16);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap contributors', maxZoom: 19, referrerPolicy: 'strict-origin-when-cross-origin' }).addTo(map);
    L.marker(point).addTo(map).bindPopup(box.getAttribute('data-shop-name')).openPopup();
}

function initCourierMap(orderId){
    if (courierMaps[orderId]){
        setTimeout(function(){ courierMaps[orderId].invalidateSize(); }, 50);
        return;
    }
    setTimeout(function(){
        var mapEl = document.getElementById('interactive-map-' + orderId);
        if (!mapEl || courierMaps[orderId]) return;

        // Map fallback center is only a safe Tehran-area fallback; the customer can
        // select the exact point manually or use the browser's current location.
        var map = L.map('interactive-map-' + orderId, { gestureHandling: true, gestureHandlingOptions: { text: { touch: 'برای جابه‌جا کردن نقشه از دو انگشت استفاده کنید', scroll: 'برای بزرگ‌نمایی، Ctrl را نگه دارید و اسکرول کنید', scrollMac: 'برای بزرگ‌نمایی، ⌘ را نگه دارید و اسکرول کنید' } } }).setView([35.7262837, 51.2922665], 15);
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '© OpenStreetMap contributors',
            maxZoom: 19,
            referrerPolicy: 'strict-origin-when-cross-origin'
        }).addTo(map);

        function setCourierPoint(latlng){
            placeCourierMarker(orderId, latlng);
            setAddrMode(orderId, 'new');
            lookupAddress(orderId, latlng);
        }

        map.on('click', function(e){ setCourierPoint(e.latlng); });
        map.on('locationfound', function(e){
            map.setView(e.latlng, Math.max(map.getZoom(), 17));
            setCourierPoint(e.latlng);
        });

        courierMaps[orderId] = map;
        map.invalidateSize();
        if (SAVED_ADDRESS){ useSavedAddress(orderId); }
        else { setTimeout(function(){ map.locate({setView:false, enableHighAccuracy:true, maxZoom:17}); }, 150); }
    }, 50);
}

function editCourierAddress(orderId){
    var box = document.getElementById('courier-edit-' + orderId);
    var btn = document.getElementById('courier-edit-btn-' + orderId);
    if (!box) return;
    box.classList.remove('hidden');
    if (btn) btn.classList.add('hidden');
    initCourierMap(orderId);
}

/* ==== Saved address, reverse geocoding and the courier pin ==== */
// Postal codes may be typed with Persian digits, spaces or dashes.
function normalizePostal(value){
    return String(value || '').replace(/[۰-۹]/g, function(d){ return String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)); })
        .replace(/[٠-٩]/g, function(d){ return String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)); })
        .replace(/[\s\-‌]/g, '');
}

// SAVED_ADDRESS comes from home/page_data.html.

function useSavedAddress(orderId){
    var map = courierMaps[orderId];
    if (!SAVED_ADDRESS || !map) return;
    var point = L.latLng(parseFloat(SAVED_ADDRESS.lat), parseFloat(SAVED_ADDRESS.lng));
    map.setView(point, 17);
    placeCourierMarker(orderId, point);
    if (SAVED_ADDRESS.postal){
        var savedPostal = document.getElementById('postal-' + orderId);
        savedPostal.value = SAVED_ADDRESS.postal;
        // The customer confirmed this code when they saved the address.
        if (window.PostalCheck) PostalCheck.markConfirmed(savedPostal, SAVED_ADDRESS.text);
    }
    setAddrMode(orderId, 'saved');
    if (SAVED_ADDRESS.text){
        addrSeq[orderId] = (addrSeq[orderId] || 0) + 1;
        setAddrPreview(orderId, 'found', SAVED_ADDRESS.text);
    } else {
        lookupAddress(orderId, point);
    }
}

// ---------- Point on map → readable address (reverse geocoding) ----------
var addrCache = {}, addrSeq = {}, addrTimers = {};

function placeCourierMarker(orderId, latlng){
    var map = courierMaps[orderId];
    if (courierMarkers[orderId]) map.removeLayer(courierMarkers[orderId]);
    var marker = L.marker(latlng, { draggable: true }).addTo(map);
    marker.on('dragend', function(){
        var p = marker.getLatLng();
        document.getElementById('lat-' + orderId).value = p.lat;
        document.getElementById('lng-' + orderId).value = p.lng;
        setAddrMode(orderId, 'new');
        lookupAddress(orderId, p);
        pinMoved(orderId);
    });
    courierMarkers[orderId] = marker;
    document.getElementById('lat-' + orderId).value = latlng.lat;
    document.getElementById('lng-' + orderId).value = latlng.lng;
    pinMoved(orderId);
}

// Tell the postal-code check (static/js/postal-lookup.js) that this map's pin moved.
function pinMoved(orderId){
    document.dispatchEvent(new CustomEvent('postal:pin-moved', { detail: { latId: 'lat-' + orderId } }));
}

function setAddrPreview(orderId, state, text){
    var box = document.getElementById('addr-preview-' + orderId);
    var el = document.getElementById('addr-text-' + orderId);
    if (!box || !el) return;
    box.setAttribute('data-state', state);
    el.textContent = text;
}

function joinAddressParts(parts){
    var seen = {};
    return parts.filter(function(p){
        p = (p || '').trim();
        if (!p || seen[p]) return false;
        seen[p] = true;
        return true;
    }).join('، ');
}

// Persian addresses go from general to specific: city، neighbourhood، street، number
function formatNominatim(data){
    var a = (data && data.address) || {};
    var city = a.city || a.town || a.village || a.county || a.state || '';
    var area = a.neighbourhood || a.suburb || a.quarter || a.city_district || '';
    var road = a.road || a.pedestrian || a.residential || a.footway || '';
    var place = a.amenity || a.shop || a.building || '';
    var num = a.house_number ? 'پلاک ' + a.house_number : '';
    return joinAddressParts([city, area, road, num, place]);
}

function formatPhoton(data){
    var p = (data && data.features && data.features[0] && data.features[0].properties) || {};
    var num = p.housenumber ? 'پلاک ' + p.housenumber : '';
    return joinAddressParts([p.city || p.county || p.state, p.locality || p.district, p.street, num, p.name]);
}

// {text, postcode}: the readable address of a point and, when OpenStreetMap knows it,
// the postal code of the nearest registered building (a suggestion: flats each have their own).
function fetchAddress(lat, lng){
    var nominatim = 'https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=18&addressdetails=1&accept-language=fa&lat=' + lat + '&lon=' + lng;
    var photon = 'https://photon.komoot.io/reverse?lang=default&limit=1&lat=' + lat + '&lon=' + lng;
    return fetch(nominatim, { referrerPolicy: 'strict-origin-when-cross-origin' })
        .then(function(r){ if (!r.ok) throw new Error('nominatim ' + r.status); return r.json(); })
        .then(function(d){
            var t = formatNominatim(d);
            if (!t) throw new Error('empty');
            return { text: t, postcode: (d.address && d.address.postcode) || '' };
        })
        .catch(function(){
            return fetch(photon).then(function(r){ if (!r.ok) throw new Error('photon'); return r.json(); }).then(function(d){
                var p = (d && d.features && d.features[0] && d.features[0].properties) || {};
                return { text: formatPhoton(d), postcode: p.postcode || '' };
            });
        });
}

function suggestPostal(orderId, postcode){
    var field = document.getElementById('postal-' + orderId);
    if (field && window.PostalCheck) PostalCheck.suggest(field, postcode);
}

function lookupAddress(orderId, latlng){
    var lat = Number(latlng.lat).toFixed(5), lng = Number(latlng.lng).toFixed(5);
    var key = lat + ',' + lng;
    var seq = addrSeq[orderId] = (addrSeq[orderId] || 0) + 1;
    clearTimeout(addrTimers[orderId]);
    if (addrCache[key]){ setAddrPreview(orderId, 'found', addrCache[key].text); suggestPostal(orderId, addrCache[key].postcode); return; }
    setAddrPreview(orderId, 'loading', 'در حال پیدا کردن آدرس…');
    // Short debounce: fast repeated taps/drags send only one request (Nominatim allows ~1 req/s).
    addrTimers[orderId] = setTimeout(function(){
        fetchAddress(lat, lng).then(function(found){
            if (seq !== addrSeq[orderId]) return;
            if (found && found.text){
                addrCache[key] = found;
                setAddrPreview(orderId, 'found', found.text);
                suggestPostal(orderId, found.postcode);
            } else {
                setAddrPreview(orderId, 'empty', 'آدرس این نقطه پیدا نشد؛ لطفاً جزئیات را در کادر زیر بنویسید.');
            }
        }).catch(function(){
            if (seq !== addrSeq[orderId]) return;
            setAddrPreview(orderId, 'empty', 'دریافت آدرس ممکن نشد؛ موقعیت روی نقشه ثبت شده است. جزئیات را در کادر زیر بنویسید.');
        });
    }, 450);
}

// Address text sent with the courier request: found address + the customer's extra details.
function getCourierAddress(orderId){
    var box = document.getElementById('addr-preview-' + orderId);
    var auto = box && box.getAttribute('data-state') === 'found' ? document.getElementById('addr-text-' + orderId).textContent : '';
    var detailEl = document.getElementById('addr-detail-' + orderId);
    var detail = detailEl ? detailEl.value.trim() : '';
    return joinAddressParts([auto, detail]).slice(0, 500);
}

function setAddrMode(orderId, mode){
    var b1 = document.getElementById('addr-btn-saved-' + orderId);
    var b2 = document.getElementById('addr-btn-new-' + orderId);
    var st = document.getElementById('addr-status-' + orderId);
    if (!b1 || !b2) return;
    b1.classList.toggle('active', mode === 'saved');
    b2.classList.toggle('active', mode === 'new');
    if (st) st.textContent = mode === 'saved'
        ? 'این سفارش به آدرس ثبت‌شده شما ارسال می‌شود' + (SAVED_ADDRESS && SAVED_ADDRESS.text ? ': ' + SAVED_ADDRESS.text : '.')
        : 'این سفارش به لوکیشن جدیدی که روی نقشه انتخاب می‌کنید ارسال می‌شود.';
}

function useNewLocation(orderId){
    var map = courierMaps[orderId];
    if (!map) return;
    if (courierMarkers[orderId]){ map.removeLayer(courierMarkers[orderId]); delete courierMarkers[orderId]; }
    document.getElementById('lat-' + orderId).value = '';
    document.getElementById('lng-' + orderId).value = '';
    var postalField = document.getElementById('postal-' + orderId);
    postalField.value = '';
    if (window.PostalCheck) PostalCheck.reset(postalField);
    addrSeq[orderId] = (addrSeq[orderId] || 0) + 1;
    setAddrPreview(orderId, 'empty', 'روی نقشه بزنید تا آدرس نمایش داده شود.');
    setAddrMode(orderId, 'new');
    showToast('نقطه جدید را روی نقشه انتخاب کنید یا از موقعیت فعلی استفاده کنید.');
}

// A confirmed postal code brings its own point: put the pin there (the customer can still drag it).
document.addEventListener('postal:found', function(e){
    var orderId = (e.target.id || '').replace(/^postal-/, '');
    var map = courierMaps[orderId];
    if (!map || !e.target.id) return;
    var point = L.latLng(e.detail.lat, e.detail.lng);
    map.setView(point, 17);
    placeCourierMarker(orderId, point);
    setAddrMode(orderId, 'new');
    if (e.detail.address){
        addrSeq[orderId] = (addrSeq[orderId] || 0) + 1;
        setAddrPreview(orderId, 'found', e.detail.address);
    } else {
        lookupAddress(orderId, point);
    }
});

function locateCourier(orderId){
    var map = courierMaps[orderId];
    if (!map){
        showToast('لطفاً ابتدا گزینه «ارسال با پیک» را باز کنید.');
        return;
    }
    if (!navigator.geolocation){
        showToast('مرورگر شما امکان دریافت موقعیت مکانی را ندارد؛ نقطه را روی نقشه انتخاب کنید.');
        return;
    }
    showToast('در حال دریافت موقعیت فعلی شما...');
    navigator.geolocation.getCurrentPosition(function(position){
        var point = L.latLng(position.coords.latitude, position.coords.longitude);
        map.setView(point, 17);
        placeCourierMarker(orderId, point);
        setAddrMode(orderId, 'new');
        lookupAddress(orderId, point);
        showToast('موقعیت شما روی نقشه ثبت شد.');
    }, function(){
        showToast('دسترسی به موقعیت مکانی ممکن نشد؛ لطفاً روی نقشه نقطه را انتخاب کنید.');
    }, { enableHighAccuracy:true, timeout:10000, maximumAge:30000 });
}

/* ==== Toasts and invalid-field feedback ==== */
function showToast(message, duration){
    var toast = document.getElementById('global-toast');
    if (!toast){
        toast = document.createElement('div');
        toast.id = 'global-toast';
        toast.className = 'toast-msg';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    requestAnimationFrame(function(){ toast.classList.add('show'); });
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(function(){ toast.classList.remove('show'); }, duration || 2800);
}

function flashInvalid(el, message){
    if (el){
        el.classList.remove('input-shake');
        void el.offsetWidth;
        el.classList.add('input-shake');
    }
    showToast(message);
}

/* ==== Live courier/order status and "order ready" notices ==== */
// Courier status watcher: as soon as the admin marks a courier as dispatched, the
// customer page updates in place and shows a toast (no reload, so open forms are kept).
var COURIER_WATCH = JSON.parse(document.getElementById('courier-watch-data').textContent || '{}');
var STATUS_LABELS = JSON.parse(document.getElementById('status-labels-data').textContent || '{}');
var courierPollTimer = null;

// Keep polling while something can still change for the customer: a courier that has not left yet,
// or an order that has not reached "ready" yet.
function courierHasPending(){
    return Object.keys(COURIER_WATCH).some(function(id){
        var s = COURIER_WATCH[id];
        return (s.pickup[0] && !s.pickup[1]) || (s.delivery[0] && !s.delivery[1]) ||
               (s.status !== 'ready' && s.status !== 'delivered');
    });
}

function readyNoticeSeen(orderId){
    try { return localStorage.getItem('readyNoticeSeen:' + orderId) === '1'; } catch (e) { return false; }
}

function dismissReadyNotice(orderId){
    try { localStorage.setItem('readyNoticeSeen:' + orderId, '1'); } catch (e) {}
    var el = document.getElementById('ready-notice-' + orderId);
    if (!el) return;
    el.classList.add('leaving');
    setTimeout(function(){ el.remove(); }, 300);
}

function openReadyOrder(orderId){
    var panel = document.getElementById('delivery-track-' + orderId);
    dismissReadyNotice(orderId);
    if (panel){
        panel.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
        window.location.href = HOME_URLS.home + '?order_id=' + encodeURIComponent(orderId) + '#track-section';
    }
}

function showReadyNotice(orderId){
    var box = document.getElementById('ready-notices');
    if (!box || readyNoticeSeen(orderId) || document.getElementById('ready-notice-' + orderId)) return;
    if (box.children.length >= 3) return;
    var s = COURIER_WATCH[orderId] || {};
    var note = (s.delivery && s.delivery[0])
        ? 'لباس‌ها شسته و اتو شده‌اند و به‌زودی تحویل پیک می‌شوند.'
        : 'لباس‌ها شسته و اتو شده‌اند. می‌توانید حضوری تحویل بگیرید یا ارسال با پیک را انتخاب کنید.';
    var el = document.createElement('div');
    el.className = 'ready-notice';
    el.id = 'ready-notice-' + orderId;
    el.setAttribute('role', 'status');
    el.innerHTML =
        '<div class="ready-notice-icon"><svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.4" d="M5 13l4 4L19 7"/></svg></div>' +
        '<div class="min-w-0 flex-1">' +
            '<p class="text-[10px] font-bold text-emerald-600 mb-0.5">اعلان سفارش</p>' +
            '<p class="text-sm font-black text-gray-900">سفارش #' + faNumber(orderId) + ' آماده تحویل است</p>' +
            '<p class="text-[11px] text-gray-500 leading-5 mt-1">' + note + '</p>' +
            '<button type="button" class="ready-notice-cta" data-ready-open>مشاهده سفارش' +
                '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.4" d="M15 19l-7-7 7-7"/></svg>' +
            '</button>' +
        '</div>' +
        '<button type="button" class="ready-notice-close" aria-label="بستن اعلان" data-ready-close>' +
            '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-width="2.2" d="M6 6l12 12M18 6L6 18"/></svg>' +
        '</button>';
    el.querySelector('[data-ready-open]').addEventListener('click', function(){ openReadyOrder(orderId); });
    el.querySelector('[data-ready-close]').addEventListener('click', function(){ dismissReadyNotice(orderId); });
    box.appendChild(el);
}

function hideCourierBanners(orderId, kind){
    document.querySelectorAll('[data-courier-banner="' + orderId + '-' + kind + '"]').forEach(function(el){ el.classList.add('hidden'); });
}

function applyStatusChange(orderId, oldStatus, newStatus){
    // Pickup courier info only matters before the clothes reach us; delivery info only while ready.
    if (oldStatus === 'collecting') hideCourierBanners(orderId, 'pickup');
    if (oldStatus === 'ready') hideCourierBanners(orderId, 'delivery');
    if (newStatus === 'ready'){
        showReadyNotice(orderId);
    } else if (newStatus === 'delivered' && COURIER_WATCH[orderId] && !COURIER_WATCH[orderId].reviewed && !reviewState.orderId){
        setTimeout(function(){ openReview(orderId); }, 600);
    } else {
        showToast('وضعیت سفارش #' + faNumber(orderId) + ': ' + (STATUS_LABELS[newStatus] || newStatus), 5000);
    }
}

function applyCourierDispatched(orderId, kind){
    document.querySelectorAll('[data-courier-banner="' + orderId + '-' + kind + '"]').forEach(function(el){
        el.classList.toggle('hidden', el.getAttribute('data-state') !== 'sent');
    });
    if (kind === 'delivery'){
        document.querySelectorAll('[data-courier-card-title="' + orderId + '"]').forEach(function(el){ el.textContent = 'پیک شما ارسال شده است'; });
        document.querySelectorAll('[data-courier-card-note="' + orderId + '"]').forEach(function(el){ el.textContent = 'پیک در مسیر رسیدن به شماست'; });
        showToast('لباس‌های سفارش #' + faNumber(orderId) + ' به پیک تحویل داده شد و در مسیر رسیدن به شماست.', 6000);
    } else {
        showToast('پیک دریافت سفارش #' + faNumber(orderId) + ' برای شما ارسال شد.', 6000);
    }
}

function pollCourierStatus(){
    if (document.visibilityState !== 'visible' || !courierHasPending()) return;
    var ids = Object.keys(COURIER_WATCH).join(',');
    fetch(HOME_URLS.courierStatus + '?ids=' + encodeURIComponent(ids), { credentials: 'same-origin' })
        .then(function(r){ return r.ok ? r.json() : null; })
        .then(function(data){
            if (!data || data.status !== 'success') return;
            Object.keys(data.orders).forEach(function(id){
                var oldS = COURIER_WATCH[id], newS = data.orders[id];
                if (!oldS) return;
                if (oldS.status !== newS.status) applyStatusChange(id, oldS.status, newS.status);
                ['pickup', 'delivery'].forEach(function(kind){
                    var stillRelevant = kind === 'pickup' ? newS.status === 'collecting' : newS.status === 'ready';
                    if (stillRelevant && oldS[kind][0] && !oldS[kind][1] && newS[kind][0] && newS[kind][1]) applyCourierDispatched(id, kind);
                });
                COURIER_WATCH[id] = newS;
            });
        })
        .catch(function(){});
}

function startCourierWatch(){
    if (courierPollTimer || !courierHasPending()) return;
    courierPollTimer = setInterval(pollCourierStatus, 30000);
}

document.addEventListener('visibilitychange', function(){ if (document.visibilityState === 'visible') pollCourierStatus(); });
startCourierWatch();
Object.keys(COURIER_WATCH).forEach(function(id, i){
    if (COURIER_WATCH[id].status === 'ready') setTimeout(function(){ showReadyNotice(id); }, 700 + i * 180);
});

/* ==== Rating sheet after delivery ==== */
// ---------- Review / rating after delivery ----------
var REVIEW_FACES = {
    1: { color: '#f87171', mouth: 'M8 17q4-3.6 8 0',   label: 'خیلی ناراضی بودم' },
    2: { color: '#fb923c', mouth: 'M8.5 16.4q3.5-2 7 0', label: 'ناراضی بودم' },
    3: { color: '#fbbf24', mouth: 'M8.5 15.5h7',        label: 'معمولی بود' },
    4: { color: '#34d399', mouth: 'M8.5 14.6q3.5 2.4 7 0', label: 'راضی بودم' },
    5: { color: '#10b981', mouth: 'M7.8 14q4.2 4.6 8.4 0', label: 'عالی بود!' }
};
var REVIEW_SNOOZE_MS = 3 * 24 * 60 * 60 * 1000;
var reviewState = { orderId: null, rating: 0, tags: [], sending: false };

function reviewSnoozed(orderId){
    try { return Date.now() - Number(localStorage.getItem('reviewSnooze:' + orderId) || 0) < REVIEW_SNOOZE_MS; } catch (e) { return false; }
}

function setReviewRating(value, animate){
    reviewState.rating = value;
    var face = REVIEW_FACES[value];
    document.querySelectorAll('#rv-stars button').forEach(function(b){
        var v = Number(b.getAttribute('data-v'));
        b.classList.toggle('on', v <= value);
        b.setAttribute('aria-checked', v === value ? 'true' : 'false');
        if (animate && v <= value){
            b.classList.remove('pop'); void b.offsetWidth; b.classList.add('pop');
            b.style.animationDelay = (v * 35) + 'ms';
        }
    });
    var faceEl = document.getElementById('rv-face');
    faceEl.style.setProperty('--rv-face', face.color);
    faceEl.classList.remove('bump'); void faceEl.offsetWidth; faceEl.classList.add('bump');
    document.getElementById('rv-mouth').setAttribute('d', face.mouth);
    document.getElementById('rv-label').textContent = face.label;
    var happy = value >= 4;
    document.getElementById('rv-chips-title').textContent = happy ? 'چه چیزی را بیشتر دوست داشتید؟' : 'کدام بخش باید بهتر شود؟';
    document.getElementById('rv-text').placeholder = happy
        ? 'اگر دوست دارید، چند کلمه از تجربه‌تان بنویسید…'
        : 'بگویید کجای کار مشکل داشت تا جبرانش کنیم…';
    document.getElementById('rv-public-hint').classList.toggle('hidden', value < 5);
    document.getElementById('rv-details').classList.add('show');
    document.getElementById('rv-submit').disabled = false;
}

function openReview(orderId, rating){
    var modal = document.getElementById('review-modal');
    if (!modal) return;
    reviewState = { orderId: String(orderId), rating: 0, tags: [], sending: false };
    document.getElementById('rv-form').classList.remove('hidden');
    document.getElementById('rv-thanks').classList.add('hidden');
    document.getElementById('rv-order-label').textContent = 'سفارش #' + faNumber(orderId) + ' تحویل داده شد';
    document.getElementById('rv-text').value = '';
    document.getElementById('rv-details').classList.remove('show');
    document.getElementById('rv-public-hint').classList.add('hidden');
    document.getElementById('rv-label').textContent = 'روی ستاره‌ها بزنید';
    document.getElementById('rv-mouth').setAttribute('d', 'M8.5 15.5h7');
    document.getElementById('rv-face').style.removeProperty('--rv-face');
    document.getElementById('rv-submit').disabled = true;
    document.getElementById('rv-submit').textContent = 'ثبت نظر';
    document.querySelectorAll('#rv-stars button').forEach(function(b){ b.classList.remove('on', 'pop'); b.setAttribute('aria-checked', 'false'); });
    document.querySelectorAll('#rv-chips .rv-chip').forEach(function(c){ c.classList.remove('on'); });
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    document.documentElement.style.overflow = 'hidden';
    if (rating) setTimeout(function(){ setReviewRating(rating, true); }, 120);
    setTimeout(function(){ document.querySelector('#rv-stars button').focus({ preventScroll: true }); }, 200);
}

function closeReview(snooze){
    var modal = document.getElementById('review-modal');
    if (!modal || !modal.classList.contains('open')) return;
    if (snooze && reviewState.orderId){
        try { localStorage.setItem('reviewSnooze:' + reviewState.orderId, String(Date.now())); } catch (e) {}
    }
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    document.documentElement.style.overflow = '';
    reviewState.orderId = null;
}

function markOrderReviewed(orderId, rating){
    if (COURIER_WATCH[orderId]) COURIER_WATCH[orderId].reviewed = true;
    var stars = '';
    for (var i = 1; i <= 5; i++) stars += '<span class="' + (i > rating ? 'off' : '') + '">★</span>';
    document.querySelectorAll('[data-review-cta="' + orderId + '"]').forEach(function(el){
        el.outerHTML =
            '<div class="review-done mt-4 mb-3 rounded-2xl px-4 py-3 flex items-center justify-between gap-3">' +
                '<div class="min-w-0"><p class="text-[11px] font-bold text-gray-500">امتیاز شما به این سفارش</p>' +
                '<div class="review-stars sm mt-1">' + stars + '</div></div>' +
                '<span class="text-[10px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-full px-3 py-1 shrink-0">ممنون از نظرتان</span>' +
            '</div>';
    });
}

function burstConfetti(host){
    var colors = ['#22d3ee', '#a78bfa', '#fbbf24', '#34d399', '#f472b6'];
    for (var i = 0; i < 22; i++){
        var p = document.createElement('span');
        var angle = (Math.PI * 2 * i) / 22, dist = 60 + Math.random() * 50;
        p.className = 'rv-confetti';
        p.style.background = colors[i % colors.length];
        p.style.setProperty('--x', Math.cos(angle) * dist + 'px');
        p.style.setProperty('--y', Math.sin(angle) * dist + 'px');
        p.style.setProperty('--r', (Math.random() * 540 - 270) + 'deg');
        p.style.animationDelay = (Math.random() * 120) + 'ms';
        host.appendChild(p);
        setTimeout(function(el){ return function(){ el.remove(); }; }(p), 1300);
    }
}

function submitReview(){
    if (!reviewState.orderId || !reviewState.rating || reviewState.sending) return;
    reviewState.sending = true;
    var btn = document.getElementById('rv-submit');
    btn.disabled = true;
    btn.textContent = 'در حال ثبت…';
    var orderId = reviewState.orderId, rating = reviewState.rating;
    fetch(HOME_URLS.submitReview, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('#review-modal input[name="csrfmiddlewaretoken"]').value },
        body: JSON.stringify({ order_id: orderId, rating: rating, tags: reviewState.tags, comment: document.getElementById('rv-text').value })
    })
    .then(function(r){ return r.json(); })
    .then(function(data){
        reviewState.sending = false;
        if (data.status !== 'success'){
            btn.disabled = false;
            btn.textContent = 'ثبت نظر';
            showToast(data.message || 'ثبت نظر انجام نشد؛ دوباره تلاش کنید.');
            if (/قبلاً/.test(data.message || '')) { markOrderReviewed(orderId, rating); closeReview(false); }
            return;
        }
        markOrderReviewed(orderId, rating);
        document.getElementById('rv-thanks-text').textContent = (data.pending_approval && rating >= 5)
            ? 'خوشحالیم که از ما راضی بودید! نظر شما پس از تأیید فروشگاه در بخش «نظر مشتریان» صفحه اول نمایش داده می‌شود.'
            : (rating >= 4
                ? 'خوشحالیم که از ما راضی بودید. منتظر سفارش بعدی‌تان هستیم.'
                : 'متأسفیم که تجربه‌تان کامل نبود. نظر شما به دست مدیریت رسید و برای بهتر شدن از آن استفاده می‌کنیم.');
        document.getElementById('rv-form').classList.add('hidden');
        document.getElementById('rv-thanks').classList.remove('hidden');
        if (rating >= 4) burstConfetti(document.getElementById('rv-thanks-icon'));
    })
    .catch(function(){
        reviewState.sending = false;
        btn.disabled = false;
        btn.textContent = 'ثبت نظر';
        showToast('ارتباط برقرار نشد؛ دوباره تلاش کنید.');
    });
}

(function initReview(){
    var modal = document.getElementById('review-modal');
    if (!modal) return;
    document.querySelectorAll('#rv-stars button').forEach(function(b){
        b.addEventListener('click', function(){ setReviewRating(Number(b.getAttribute('data-v')), true); });
    });
    document.querySelectorAll('#rv-chips .rv-chip').forEach(function(c){
        c.addEventListener('click', function(){
            var tag = c.getAttribute('data-tag'), i = reviewState.tags.indexOf(tag);
            if (i === -1) reviewState.tags.push(tag); else reviewState.tags.splice(i, 1);
            c.classList.toggle('on', i === -1);
        });
    });
    modal.addEventListener('click', function(e){ if (e.target === modal) closeReview(true); });
    document.addEventListener('keydown', function(e){ if (e.key === 'Escape') closeReview(true); });

    // Ask once for the most recent delivered order that has no review yet (unless snoozed).
    var pending = Object.keys(COURIER_WATCH).filter(function(id){
        var s = COURIER_WATCH[id];
        return s.status === 'delivered' && !s.reviewed;
    }).sort(function(a, b){ return Number(b) - Number(a); });
    if (pending.length && !reviewSnoozed(pending[0])){
        setTimeout(function(){ if (!reviewState.orderId) openReview(pending[0]); }, 1600);
    }
})();

/* ==== Courier request for a ready order ==== */
function submitCourier(orderId){
    var latEl = document.getElementById('lat-' + orderId);
    var postalEl = document.getElementById('postal-' + orderId);
    var lat = latEl.value;
    var lng = document.getElementById('lng-' + orderId).value;
    var postal = normalizePostal(postalEl.value);

    if (!lat){
        flashInvalid(document.getElementById('interactive-map-' + orderId), 'لطفاً موقعیت خود را روی نقشه انتخاب کنید.');
        return;
    }
    if (!/^\d{10}$/.test(postal)){
        flashInvalid(postalEl, 'کد پستی باید ۱۰ رقم باشد.');
        return;
    }
    // Not confirmed for this address yet: the form-error toast explains and points at it.
    if (!postalEl.checkValidity()) return;

    var btn = document.getElementById('courier-submit-' + orderId);
    if (!btn || btn.disabled) return;
    var originalText = btn.innerHTML;
    btn.innerHTML = '<svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg> در حال ثبت درخواست...';
    btn.disabled = true;
    btn.classList.add('opacity-75', 'cursor-not-allowed');

    fetch('/request-courier/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getOrderCsrfToken() },
        body: JSON.stringify({ order_id: orderId, lat: lat, lng: lng, postal: postal, address: getCourierAddress(orderId) })
    })
    .then(function(response){ return response.json(); })
    .then(function(data){
        if (data.status === 'success'){
            // Reload this order so the page shows the saved address and live courier status.
            showToast(data.message || 'درخواست پیک ثبت شد.');
            setTimeout(function(){
                window.location.href = HOME_URLS.home + '?order_id=' + encodeURIComponent(orderId) + '#track-section';
            }, 900);
        } else {
            btn.innerHTML = originalText;
            btn.disabled = false;
            btn.classList.remove('opacity-75', 'cursor-not-allowed');
            showToast(data.message || 'ثبت درخواست پیک انجام نشد؛ دوباره تلاش کنید.', 4500);
        }
    })
    .catch(function(){
        btn.innerHTML = originalText;
        btn.disabled = false;
        btn.classList.remove('opacity-75', 'cursor-not-allowed');
        showToast('خطا در ارتباط با سرور. لطفاً اینترنت خود را بررسی کنید.');
    });
}

/* ==== Cart, item picker, categories and search ==== */
/* ---------- سبد سفارش آنلاین ---------- */
var cart = {};
var itemIronOnly = {};
var MAX_ITEM_QTY = 50;
// WALLET_BALANCE comes from home/page_data.html.
var orderSubmitting = false;

function escapeHtml(text){
    return String(text).replace(/[&<>"']/g, function(c){ return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
}

// قیمت‌ها در دیتابیس متنی هستند (مثلاً "520,000" یا "۳ تا ۷ میلیون").
// اگر عدد خالص نبود null برمی‌گردد یعنی «قیمت پس از بررسی».
function parsePrice(raw){
    if (!raw) return null;
    var normalized = String(raw).replace(/[۰-۹]/g, function(d){ return String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)); })
        .replace(/[,٬\s]/g, '');
    if (/^\d+$/.test(normalized)) return parseInt(normalized, 10);
    return null;
}

// Same label the invoice will show: «پیراهن مردانه (فقط اتو)».
function itemLabel(cardEl, ironOnly){
    var name = cardEl.dataset.name || '';
    var category = cardEl.dataset.category || '';
    if (category && name.indexOf(category) === -1) name += ' ' + category;
    return name + (ironOnly ? ' (فقط اتو)' : ' (خشکشویی + اتو)');
}

function cartEntry(itemId, qty, description){
    var cardEl = document.getElementById('item-card-' + itemId);
    var ironOnly = !!itemIronOnly[itemId];
    var priceRaw = ironOnly ? cardEl.dataset.ironPrice : cardEl.dataset.dryPrice;
    return { name: itemLabel(cardEl, ironOnly), price: parsePrice(priceRaw), qty: qty, description: description || '' };
}

function updateCartUI(){
    var listEl = document.getElementById('cart-list');
    var noteEl = document.getElementById('cart-note');
    var keys = Object.keys(cart);
    var total = 0, html = '', hasUnknown = false;
    keys.forEach(function(id){
        var it = cart[id];
        var lineText;
        if (it.price === null){
            hasUnknown = true;
            lineText = 'پس از بررسی';
        } else {
            total += it.price * it.qty;
            lineText = faNumber(it.price * it.qty) + ' تومان';
        }
        html += '<li class="flex justify-between items-center gap-3 text-sm">' +
                    '<span class="text-gray-600 min-w-0">' + escapeHtml(it.name) + ' × ' + faNumber(it.qty) + '</span>' +
                    '<span class="font-bold text-gray-800 whitespace-nowrap">' + lineText + '</span>' +
                '</li>';
    });
    listEl.innerHTML = keys.length ? html : '<li class="text-gray-400 text-xs" id="cart-empty">هنوز قلمی انتخاب نکرده‌اید.</li>';
    document.getElementById('cart-total').innerHTML = faNumber(total) + ' تومان' +
        (hasUnknown ? '<span class="block text-[11px] font-bold text-amber-600 mt-0.5">+ اقلام پس از بررسی</span>' : '');
    if (noteEl) noteEl.classList.toggle('hidden', !hasUnknown);
    var totalLabel = document.getElementById('cart-total-label');
    if (totalLabel) totalLabel.textContent = hasUnknown ? 'مبلغ تا این لحظه:' : 'مبلغ قابل پرداخت:';

    // Orders with items priced after inspection are paid once ready, so no wallet payment now.
    var useWallet = document.getElementById('use-wallet');
    var walletOption = document.getElementById('wallet-option');
    if (walletOption) walletOption.classList.toggle('hidden', hasUnknown);
    if (useWallet && hasUnknown) useWallet.checked = false;
    var hint = document.getElementById('wallet-hint');
    if (useWallet && hint){
        var short = useWallet.checked && total > 0 && WALLET_BALANCE < total;
        hint.textContent = short ? 'موجودی کیف پول برای این سفارش کافی نیست؛ سفارش ثبت می‌شود و بعداً می‌توانید پرداخت کنید.' : '';
        hint.classList.toggle('hidden', !short);
    }
}

function toggleIronOnly(itemId, checked){
    itemIronOnly[itemId] = checked;
    var cardEl = document.getElementById('item-card-' + itemId);
    var priceLabel = document.getElementById('price-label-' + itemId);
    if (!cardEl) return;
    var price = parsePrice(checked ? cardEl.dataset.ironPrice : cardEl.dataset.dryPrice);
    if (priceLabel){
        priceLabel.innerHTML = price === null
            ? '<span class="item-price-empty">قیمت پس از بررسی</span>'
            : '<span class="item-price">' + faNumber(price) + ' تومان</span>';
    }
    if (cart[itemId]){
        cart[itemId] = cartEntry(itemId, cart[itemId].qty, cart[itemId].description);
        updateCartUI();
    }
}

function updateItemDescription(itemId, value){ if (!cart[itemId]) return; cart[itemId].description = value || ''; }

function changeQty(itemId, delta){
    var cardEl = document.getElementById('item-card-' + itemId);
    if (!cardEl || orderSubmitting) return;
    var current = cart[itemId] ? cart[itemId].qty : 0;
    var next = Math.min(MAX_ITEM_QTY, Math.max(0, current + delta));
    if (delta > 0 && current >= MAX_ITEM_QTY){
        showToast('حداکثر ' + faNumber(MAX_ITEM_QTY) + ' عدد از هر قلم را می‌توانید آنلاین ثبت کنید؛ برای تعداد بیشتر با فروشگاه تماس بگیرید.', 4500);
    }
    if (next === 0){
        delete cart[itemId];
    } else {
        cart[itemId] = cartEntry(itemId, next, cart[itemId] ? cart[itemId].description : '');
    }
    var qtyEl = document.getElementById('qty-' + itemId);
    if (qtyEl) qtyEl.textContent = faNumber(next);
    cardEl.classList.toggle('selected', next > 0);
    if (next !== current){
        if (qtyEl) replayClass(qtyEl, 'bump');
        if (next > current) replayClass(cardEl, 'swing');
        floatQtyChange(cardEl, next - current);
    }
    var noteWrap = document.getElementById('item-note-wrap-' + itemId); if (noteWrap) noteWrap.classList.toggle('hidden', next <= 0);
    updateCartUI();
    updateCategoryCounts();
}

// Restart a one-shot CSS animation even if it is already on the element.
function replayClass(el, cls){
    el.classList.remove(cls);
    void el.offsetWidth;
    el.classList.add(cls);
}

function floatQtyChange(cardEl, delta){
    var ctrl = cardEl.querySelector('.item-ctrl');
    if (!ctrl) return;
    var tag = document.createElement('span');
    tag.className = 'qty-float';
    tag.setAttribute('aria-hidden', 'true');
    tag.textContent = (delta > 0 ? '+' : '−') + faNumber(Math.abs(delta));
    ctrl.appendChild(tag);
    setTimeout(function(){ tag.remove(); }, 750);
}

function openItemNote(itemId){
    document.getElementById('item-note-btn-' + itemId).classList.add('hidden');
    var note = document.getElementById('item-note-' + itemId);
    note.classList.remove('hidden');
    note.focus();
}

// Each category tag shows how many pieces were picked from it, so nothing gets lost behind another tab.
function updateCategoryCounts(){
    document.querySelectorAll('[data-category-block]').forEach(function(block){
        var total = 0;
        block.querySelectorAll('.item-card').forEach(function(card){
            var entry = cart[card.id.replace('item-card-', '')];
            if (entry) total += entry.qty;
        });
        var badge = document.getElementById('cat-count-' + block.dataset.cat);
        var text = total ? faNumber(total) : '';
        if (badge && badge.textContent !== text){
            badge.textContent = text;
            if (text) replayClass(badge, 'pop');
        }
    });
}

// One category at a time keeps the list short on phones; a search looks through all of them.
var firstCatTag = document.querySelector('.cat-tag');
var activeItemCategory = firstCatTag ? firstCatTag.dataset.cat : null;

function showItemCategory(catId){
    activeItemCategory = catId;
    var input = document.getElementById('item-search');
    if (input) input.value = '';
    document.querySelectorAll('.cat-tag').forEach(function(tag){
        tag.setAttribute('aria-selected', tag.dataset.cat === catId ? 'true' : 'false');
    });
    filterItems();
    var block = document.querySelector('[data-category-block][data-cat="' + catId + '"]');
    if (block){
        replayClass(block, 'printing');
        setTimeout(function(){ block.classList.remove('printing'); }, 1400);
    }
    var grid = document.getElementById('item-grid');
    var tags = document.querySelector('.cat-tags');
    if (grid && tags && grid.getBoundingClientRect().top < tags.getBoundingClientRect().bottom){
        window.scrollBy(0, grid.getBoundingClientRect().top - tags.getBoundingClientRect().bottom);
    }
}

function filterItems(){
    var input = document.getElementById('item-search');
    var grid = document.getElementById('item-grid');
    if (!input || !grid) return;
    var q = input.value.trim().replace(/ي/g, 'ی').replace(/ك/g, 'ک');
    var anyVisible = false;
    grid.classList.toggle('searching', !!q);
    var tags = document.querySelector('.cat-tags');
    if (tags) tags.classList.toggle('is-searching', !!q);
    document.querySelectorAll('[data-category-block]').forEach(function(block){
        var blockVisible = false;
        block.querySelectorAll('.item-card').forEach(function(card){
            var text = (card.dataset.name || '') + ' ' + (card.dataset.category || '');
            var match = !q || text.indexOf(q) !== -1;
            card.classList.toggle('search-hidden', !match);
            if (match) blockVisible = true;
        });
        block.classList.toggle('search-hidden', !blockVisible);
        block.classList.toggle('cat-hidden', !q && block.dataset.cat !== activeItemCategory);
        if (blockVisible) anyVisible = true;
    });
    document.getElementById('item-search-empty').classList.toggle('hidden', anyVisible);
}

(function initItemSearch(){
    var input = document.getElementById('item-search');
    if (input) input.addEventListener('input', filterItems);
    // The category tags dock right under the sticky header, whose height changes with the screen.
    var header = document.querySelector('.site-header');
    function syncHeaderHeight(){ if (header) document.documentElement.style.setProperty('--header-h', header.offsetHeight + 'px'); }
    syncHeaderHeight();
    window.addEventListener('resize', syncHeaderHeight);
})();

/* ==== Placing the order ==== */
function getOrderCsrfToken(){
    var el = document.querySelector('#order-form input[name="csrfmiddlewaretoken"]');
    return el ? el.value : '';
}

function setSubmitIdle(btn, html){
    btn.innerHTML = html;
    btn.disabled = false;
    btn.classList.remove('opacity-75', 'cursor-not-allowed');
    orderSubmitting = false;
}

function startNewOrder(){
    window.location.href = HOME_URLS.home + '#order-section';
    window.location.reload();
}

function submitOrder(){
    var btn = document.getElementById('submit-order-btn');
    if (!btn || orderSubmitting) return;

    var items = Object.keys(cart).map(function(id){
        return {
            line_id: id,
            iron_only: !!itemIronOnly[id],
            price_numeric: cart[id].price,
            quantity: cart[id].qty,
            description: cart[id].description || ''
        };
    });
    if (items.length === 0){ flashInvalid(document.getElementById('item-grid'), 'لطفاً حداقل یک قلم لباس انتخاب کنید.'); return; }

    var courierActive = document.getElementById('btn-courier-neworder').classList.contains('active');
    var useWalletEl = document.getElementById('use-wallet');
    var payload = { items: items, delivery_method: courierActive ? 'courier' : 'pickup', use_wallet: !!(useWalletEl && useWalletEl.checked) };

    if (courierActive){
        var lat = document.getElementById('lat-neworder').value;
        var lng = document.getElementById('lng-neworder').value;
        var postalEl = document.getElementById('postal-neworder');
        var postal = normalizePostal(postalEl.value);
        if (!lat){ flashInvalid(document.getElementById('interactive-map-neworder'), 'لطفاً موقعیت خود را روی نقشه انتخاب کنید.'); return; }
        if (!/^\d{10}$/.test(postal)){ flashInvalid(postalEl, 'کد پستی باید ۱۰ رقم باشد.'); return; }
        if (!postalEl.checkValidity()) return;
        var saveEl = document.getElementById('save-address-neworder');
        payload.lat = lat; payload.lng = lng; payload.postal = postal; payload.address = getCourierAddress('neworder');
        payload.save_address = !!(saveEl && saveEl.checked);
    }

    orderSubmitting = true;
    var originalText = btn.innerHTML;
    btn.innerHTML = '<svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg> در حال ثبت سفارش...';
    btn.disabled = true;
    btn.classList.add('opacity-75', 'cursor-not-allowed');

    fetch(HOME_URLS.placeOrder, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getOrderCsrfToken() },
        body: JSON.stringify(payload)
    })
    .then(function(r){ return r.json(); })
    .then(function(data){
        if (data.status !== 'success'){
            setSubmitIdle(btn, originalText);
            showToast(data.message || 'ثبت سفارش انجام نشد؛ لطفاً دوباره تلاش کنید.', 5000);
            return;
        }
        var paymentText = data.paid_by_wallet
            ? 'مبلغ سفارش از کیف پول شما پرداخت شد.'
            : (data.wallet_insufficient
                ? 'موجودی کیف پول کافی نبود؛ می‌توانید از صفحه سفارش، آنلاین یا بعد از شارژ کیف پول پرداخت کنید.'
                : 'برای پرداخت، روی «مشاهده و پرداخت سفارش» بزنید.');
        var successText = data.price_pending
            ? 'قیمت برخی اقلام بعد از بررسی لباس مشخص می‌شود؛ وقتی سفارش آماده تحویل شد، مبلغ نهایی اعلام می‌شود و می‌توانید پرداخت کنید.'
            : 'مبلغ فاکتور: ' + faNumber(data.total) + ' تومان. ' + paymentText;
        document.getElementById('order-success-invoice').textContent = 'شماره فاکتور: ' + faNumber(data.invoice_number || data.order_id);
        document.getElementById('order-success-msg').textContent = successText + ' وضعیت سفارش را همیشه در بخش «سفارش‌های من» می‌بینید.';
        var trackLink = document.getElementById('order-success-track');
        trackLink.href = data.track_url;
        if (data.price_pending) trackLink.textContent = 'مشاهده سفارش';
        document.getElementById('order-form').querySelectorAll('input, textarea, .qty-btn, .item-note-toggle, .cat-tag, .delivery-tab, #submit-order-btn').forEach(function(el){ el.disabled = true; });
        btn.innerHTML = '✓ سفارش ثبت شد';
        btn.classList.remove('opacity-75');
        document.getElementById('order-success').classList.remove('hidden');
        document.getElementById('order-success').scrollIntoView({ behavior: 'smooth', block: 'center' });
    })
    .catch(function(){
        setSubmitIdle(btn, originalText);
        showToast('ارتباط با سرور برقرار نشد؛ اینترنت خود را بررسی و دوباره تلاش کنید.', 5000);
    });
}

/* ==== Page load, anchors and resize ==== */
window.addEventListener('load', function(){
    var indicators = document.querySelectorAll('.delivery-indicator');
    indicators.forEach(function(indicator){
        var orderId = indicator.id.replace('delivery-indicator-', '');
        var activeBtn = document.getElementById('btn-pickup-' + orderId);
        if (activeBtn) positionDeliveryIndicator(orderId, activeBtn);
    });
    // Images may have shifted the layout: land on the anchor again unless the customer already scrolled.
    if (!userScrolled) scrollToHashTarget();
});

// Links such as «مشاهده سفارش» or the return from a payment point at #track-section.
var userScrolled = false;
['wheel', 'touchmove', 'keydown'].forEach(function(type){
    window.addEventListener(type, function(){ userScrolled = true; }, { passive: true, once: true });
});
function scrollToHashTarget(){
    var target = null;
    try { target = location.hash ? document.querySelector(location.hash) : null; } catch (e) {}
    if (target) target.scrollIntoView({ block: 'start' });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scrollToHashTarget);
else scrollToHashTarget();

window.addEventListener('resize', function(){
    var actives = document.querySelectorAll('.delivery-tab.active');
    actives.forEach(function(btn){
        var track = btn.closest('.delivery-tabs');
        if (track){
            var orderId = track.id.replace('delivery-track-', '');
            positionDeliveryIndicator(orderId, btn);
        }
    });
});
