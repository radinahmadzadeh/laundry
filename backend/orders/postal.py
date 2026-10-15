"""Iranian postal codes: normalizing, and looking a code up through map.ir's postal-code service.

map.ir sends the exact endpoint and an API key after a request to info@map.ir. Until both are
set (MAPIR_POSTAL_URL, MAPIR_API_KEY), lookups report 'unavailable' and only the 10-digit check
applies, so orders never get blocked by a missing or broken service.
"""
import logging
import re

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
LAT_KEYS = ('lat', 'latitude', 'y')
LNG_KEYS = ('lng', 'lon', 'long', 'longitude', 'x')
ADDRESS_KEYS = ('address', 'postal_address', 'address_compact', 'full_address', 'text')
FOUND_DAYS = 30


def normalize_postal(value):
    """Digits only: Persian/Arabic digits become ASCII, spaces, dashes and ZWNJ are dropped."""
    return re.sub(r'[\s\-‌]', '', str(value or '').translate(DIGITS))


def is_postal_format(code):
    """10 digits, and not one digit repeated (0000000000 is never a real code).

    Only these checks: the post office publishes no further structure rule we could rely on.
    """
    return code.isdigit() and len(code) == 10 and len(set(code)) > 1


def postal_format_error(code):
    """Why a normalized code is not a usable postal code, or '' when it is."""
    if not code.isdigit() or len(code) != 10:
        return 'کد پستی باید ۱۰ رقم باشد.'
    if not is_postal_format(code):
        return 'این کد پستی معتبر به نظر نمی‌رسد؛ ارقام را دوباره بررسی کنید.'
    return ''


def lookup_enabled():
    return bool(getattr(settings, 'MAPIR_API_KEY', '') and getattr(settings, 'MAPIR_POSTAL_URL', ''))


def _find(data, keys):
    """First value under any of `keys`, searching nested dicts and lists."""
    if isinstance(data, dict):
        for key in keys:
            if data.get(key) not in (None, ''):
                return data[key]
        for value in data.values():
            found = _find(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _find(value, keys)
            if found is not None:
                return found
    return None


def _coordinates(data):
    lat, lng = _find(data, LAT_KEYS), _find(data, LNG_KEYS)
    if lat is None or lng is None:
        # GeoJSON keeps a point as "coordinates": [lng, lat].
        pair = _find(data, ('coordinates',))
        if isinstance(pair, list) and len(pair) == 2:
            lng, lat = pair
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    # A real Iranian address; anything else means the response was not understood.
    if not (24.0 <= lat <= 40.5 and 43.5 <= lng <= 63.5):
        return None
    return lat, lng


def _is_empty(data):
    if data in (None, '', [], {}):
        return True
    if isinstance(data, dict):
        if data.get('found') is False or data.get('success') is False:
            return True
        for key in ('value', 'result', 'results', 'data'):
            if key in data and data[key] in (None, [], {}):
                return True
    return False


def lookup_postal_code(code):
    """Returns {'status': 'found'|'not_found'|'unavailable', 'lat', 'lng', 'address'}.

    'unavailable' means "could not check" (not configured, timeout, unreadable answer): callers
    must then let the customer continue. Answers are cached so a code is paid for only once.
    """
    code = normalize_postal(code)
    if not is_postal_format(code) or not lookup_enabled():
        return {'status': 'unavailable'}
    cache_key = f'mapir-postal:{code}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    url = settings.MAPIR_POSTAL_URL.replace('{code}', code)
    try:
        response = requests.get(url, headers={'x-api-key': settings.MAPIR_API_KEY, 'Accept': 'application/json'}, timeout=5)
    except requests.RequestException as exc:
        logger.warning('map.ir postal lookup failed: %s', exc)
        return {'status': 'unavailable'}
    if response.status_code == 404:
        result = {'status': 'not_found'}
        cache.set(cache_key, result, FOUND_DAYS * 86400)
        return result
    if response.status_code != 200:
        logger.warning('map.ir postal lookup answered HTTP %s', response.status_code)
        return {'status': 'unavailable'}
    try:
        data = response.json()
    except ValueError:
        logger.warning('map.ir postal lookup answered non-JSON')
        return {'status': 'unavailable'}

    point = _coordinates(data)
    if point:
        address = _find(data, ADDRESS_KEYS)
        result = {'status': 'found', 'lat': point[0], 'lng': point[1],
                  'address': address.strip() if isinstance(address, str) else ''}
    elif _is_empty(data):
        result = {'status': 'not_found'}
    else:
        # A shape we do not recognise: never reject a customer because of it.
        logger.warning('map.ir postal lookup answer not understood: %.300s', response.text)
        return {'status': 'unavailable'}
    cache.set(cache_key, result, FOUND_DAYS * 86400)
    return result
