from django import template

register = template.Library()


@register.filter
def clp(value):
    """Formato de pesos chilenos: 138440 -> $138.440."""
    try:
        return f"${int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return value
