from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def page_query(context, param, number):
    """The current query string with only the page number changed, so filters and searches survive paging."""
    query = context['request'].GET.copy()
    query[param] = number
    return query.urlencode()


@register.filter
def page_range(paginator, number):
    """Page numbers around the current one, with ellipses: 1 … 4 5 6 … 20."""
    return paginator.get_elided_page_range(number, on_each_side=1, on_ends=1)
