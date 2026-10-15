// Address map, reverse geocoding and postal check hooks (account page).

// Leaflet is deferred, so build the map once the page (and Leaflet) are ready.
document.addEventListener('DOMContentLoaded', function(){
  var latEl = document.getElementById('lat'), lngEl = document.getElementById('lng');
  var hasSaved = latEl.value && lngEl.value;
  var start = hasSaved ? [parseFloat(latEl.value), parseFloat(lngEl.value)] : [35.7262837, 51.2922665];
  var map = L.map('map', { gestureHandling: true, gestureHandlingOptions: { text: { touch: 'برای جابه‌جا کردن نقشه از دو انگشت استفاده کنید', scroll: 'برای بزرگ‌نمایی، Ctrl را نگه دارید و اسکرول کنید', scrollMac: 'برای بزرگ‌نمایی، ⌘ را نگه دارید و اسکرول کنید' } } }).setView(start, hasSaved ? 17 : 15);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {attribution:'© OpenStreetMap contributors', maxZoom:19, referrerPolicy:'strict-origin-when-cross-origin'}).addTo(map);
  var addrEl = document.querySelector('#address-form textarea[name="address"]');
  var lastAuto = '', seq = 0, timer = null;
  function join(parts){ var seen = {}; return parts.filter(function(p){ p = (p || '').trim(); if (!p || seen[p]) return false; seen[p] = true; return true; }).join('، '); }
  function postcodeOf(d){ return (d && d.address && d.address.postcode) || (d && d.features && d.features[0] && d.features[0].properties && d.features[0].properties.postcode) || ''; }
  function fromNominatim(d){ var a = (d && d.address) || {}; return join([a.city || a.town || a.village || a.county || a.state, a.neighbourhood || a.suburb || a.quarter || a.city_district, a.road || a.pedestrian || a.residential, a.house_number ? 'پلاک ' + a.house_number : '']); }
  function fromPhoton(d){ var p = (d && d.features && d.features[0] && d.features[0].properties) || {}; return join([p.city || p.county || p.state, p.locality || p.district, p.street, p.housenumber ? 'پلاک ' + p.housenumber : '']); }
  // Fill the address box from the chosen point (unless the customer has written their own text)
  // and suggest the point's postal code (unless they typed their own).
  function lookup(ll){
    var my = ++seq; clearTimeout(timer);
    var keepText = addrEl.value.trim() && addrEl.value !== lastAuto;
    if (!keepText) addrEl.placeholder = 'در حال پیدا کردن آدرس…';
    timer = setTimeout(function(){
      var lat = ll.lat.toFixed(5), lng = ll.lng.toFixed(5);
      fetch('https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=18&addressdetails=1&accept-language=fa&lat=' + lat + '&lon=' + lng, {referrerPolicy:'strict-origin-when-cross-origin'})
        .then(function(r){ if (!r.ok) throw 0; return r.json(); }).then(function(d){ var t = fromNominatim(d); if (!t) throw 0; return { t: t, postcode: postcodeOf(d) }; })
        .catch(function(){ return fetch('https://photon.komoot.io/reverse?lang=default&limit=1&lat=' + lat + '&lon=' + lng).then(function(r){ return r.json(); }).then(function(d){ return { t: fromPhoton(d), postcode: postcodeOf(d) }; }); })
        .then(function(found){
          if (my !== seq) return;
          var t = found.t;
          addrEl.placeholder = 'آدرس متنی (خیابان، کوچه، پلاک، واحد)';
          if (window.PostalCheck) PostalCheck.suggest(document.querySelector('input[name=postal]'), found.postcode);
          if (t && (!addrEl.value.trim() || addrEl.value === lastAuto)){ addrEl.value = lastAuto = t + '، '; addrEl.dispatchEvent(new Event('input', {bubbles:true})); }
        })
        .catch(function(){ addrEl.placeholder = 'آدرس متنی (خیابان، کوچه، پلاک، واحد)'; });
    }, 450);
  }
  var marker = null;
  function setPoint(ll, skipLookup){
    if (marker) map.removeLayer(marker);
    marker = L.marker(ll, {draggable:true}).addTo(map);
    marker.on('dragend', function(){ var p = marker.getLatLng(); latEl.value = p.lat; lngEl.value = p.lng; lookup(p); pinMoved(); });
    latEl.value = ll.lat; lngEl.value = ll.lng;
    if (!skipLookup) lookup(ll);
    pinMoved();
  }
  // Tell the postal-code check (static/js/postal-lookup.js) the pin moved.
  function pinMoved(){ document.dispatchEvent(new CustomEvent('postal:pin-moved', { detail: { latId: 'lat' } })); }
  if (hasSaved) setPoint(L.latLng(start[0], start[1]), true);
  // The saved postal code was confirmed when the address was saved.
  var postalEl = document.querySelector('input[name=postal]');
  if (hasSaved && postalEl.value && window.PostalCheck) PostalCheck.markConfirmed(postalEl, addrEl.value);
  map.on('click', function(e){ setPoint(e.latlng); });
  document.getElementById('locate-btn').addEventListener('click', function(){
    if (!navigator.geolocation){ alert('مرورگر شما امکان دریافت موقعیت را ندارد؛ نقطه را روی نقشه انتخاب کنید.'); return; }
    navigator.geolocation.getCurrentPosition(function(pos){
      var ll = L.latLng(pos.coords.latitude, pos.coords.longitude);
      map.setView(ll, 17); setPoint(ll);
    }, function(){ alert('دسترسی به موقعیت ممکن نشد؛ نقطه را روی نقشه انتخاب کنید.'); }, {enableHighAccuracy:true, timeout:10000});
  });
  // A confirmed postal code brings its own point and address.
  document.querySelector('input[name=postal]').addEventListener('postal:found', function(e){
    var ll = L.latLng(e.detail.lat, e.detail.lng);
    map.setView(ll, 17);
    setPoint(ll, !!e.detail.address);
    if (e.detail.address && (!addrEl.value.trim() || addrEl.value === lastAuto)){ addrEl.value = lastAuto = e.detail.address + '، '; }
  });
  document.getElementById('address-form').addEventListener('submit', function(e){
    if (!latEl.value){ e.preventDefault(); alert('لطفاً موقعیت خود را روی نقشه انتخاب کنید.'); }
  });
});
