from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """Keep the current query string but replace the given keys (for pagination)."""
    query = context["request"].GET.copy()
    for key, value in kwargs.items():
        query[key] = value
    return query.urlencode()


@register.filter
def num(value, places=0):
    """Indian-style grouping is overkill here; use thousands separators."""
    try:
        return f"{float(value):,.{int(places)}f}"
    except (TypeError, ValueError):
        return value


@register.filter
def trim(value):
    """Drop trailing zeros from a Decimal: 12.50 -> 12.5, 12.00 -> 12."""
    try:
        text = f"{float(value):,.2f}".rstrip("0").rstrip(".")
        return text
    except (TypeError, ValueError):
        return value


@register.filter
def pct_tone(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return "secondary"
    if value >= 95:
        return "good"
    if value >= 75:
        return "warn"
    return "bad"


@register.filter
def is_wide(field):
    """Fields that should span the full form width."""
    return field.name in {"notes", "remarks", "description", "note"}
