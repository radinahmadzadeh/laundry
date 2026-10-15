from urllib.parse import quote

from django import template

register = template.Library()


@register.filter
def neshan_url(point):
    """Neshan link for a 'lat,lng' point: opens the Neshan app on Android (web map otherwise).

    Format from Neshan's own deeplink builder (NeshanMaps/Neshan-MCP). iPhones get the app
    through static/js/neshan-links.js, which reads the point from data-neshan.
    """
    if not point:
        return ''
    lat, _, lng = str(point).partition(',')
    return f'https://nshn.ir/?lat={quote(lat.strip())}&lng={quote(lng.strip())}'
