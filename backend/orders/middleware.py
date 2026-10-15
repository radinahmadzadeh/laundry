from django.utils.cache import add_never_cache_headers


class PrivatePagesNoStoreMiddleware:
    """Pages shown to a logged-in customer or staff member hold personal data (orders, phone, wallet).

    Mark them no-store so that after logging out, the browser's back button or cache cannot show them again.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        logged_in = request.session.get('customer_logged_in') or getattr(request, 'user', None) and request.user.is_authenticated
        if logged_in and response.get('Content-Type', '').startswith('text/html'):
            add_never_cache_headers(response)  # no-cache, no-store, must-revalidate, private
        return response
