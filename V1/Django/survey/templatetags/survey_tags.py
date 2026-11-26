from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from ..glossary import text as glossary_text
from ..services import querystring

register = template.Library()


@register.simple_tag
def tip(key):
    """A question mark that opens a short explanation when clicked.

    The words live in glossary.py so a term reads the same everywhere. An
    unknown key renders nothing rather than an empty bubble, which keeps a
    typo from looking like a working control.
    """
    body = glossary_text(key)
    if not body:
        return ""
    return format_html(
        '<button type="button" class="tip" aria-label="{}" data-tip="{}">?</button>',
        body, body)


@register.simple_tag
def value_tip(key, value):
    """Tip for one value of a coded column, such as a sight type.

    Renders nothing when the value has no entry, so a code nobody has written
    up yet simply shows as itself.
    """
    return tip(f"{key}:{value}") if value else ""


@register.simple_tag(takes_context=True)
def sort_header(context, key, label):
    """A column heading that sorts by `key`, keeping the current filters.

    Clicking the column already sorted reverses it. Sorting always returns to
    page one, otherwise the reader lands on page 12 of a different ordering.
    """
    request = context["request"]
    current = context.get("sort_key")
    descending = context.get("sort_desc")

    if key == current:
        new_sort = key if descending else f"-{key}"
        arrow = " ↓" if descending else " ↑"
        css = "sorted"
    else:
        new_sort = key
        arrow = ""
        css = ""

    url = querystring(request, sort=new_sort, page=None)
    return format_html(
        '<th class="{}"><a href="{}">{}{}</a></th>', css, url, label, arrow
    )


@register.simple_tag(takes_context=True)
def page_url(context, page):
    return querystring(context["request"], page=page)


@register.simple_tag(takes_context=True)
def with_params(context, **kwargs):
    return querystring(context["request"], **kwargs)


@register.simple_tag
def elided_pages(page):
    """Page numbers around the current one, with gaps marked by an ellipsis.

    A template cannot call get_elided_page_range itself because it takes an
    argument.
    """
    return list(page.paginator.get_elided_page_range(page.number))


@register.filter
def dash(value):
    """An empty value is shown as a dash, never as a guess or a zero.

    The data has real gaps and the interface says so.
    """
    if value is None or value == "":
        return mark_safe('<span class="none">-</span>')
    return value


@register.filter
def unknown(value):
    """An empty value on a detail page, written as a word.

    A dash reads as a formatting choice next to a label. `Unknown` says the
    database has no answer, which is different from zero and different from
    the field not applying. Tables keep the dash, where a word in every empty
    cell would be noise.
    """
    if value is None or value == "":
        return mark_safe('<span class="none">Unknown</span>')
    return value


@register.filter
def nm(value, places=1):
    """A distance in nautical miles, or a dash."""
    if value is None:
        return mark_safe('<span class="none">-</span>')
    return format_html("{}", f"{float(value):,.{places}f}")


@register.filter
def duration(value):
    """A timedelta as hours and minutes, which is how an effort reads."""
    if value is None:
        return mark_safe('<span class="none">-</span>')
    total = int(value.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    return format_html("{}", f"{sign}{total // 3600}h {total % 3600 // 60:02d}m")


@register.filter
def lookup(mapping, key):
    """One value out of a dict whose keys are not valid template names.

    The edit form is described by database column names -- `Start Dec Lat`,
    `Photos?` -- which a template cannot write as an attribute.
    """
    if hasattr(mapping, "get"):
        return mapping.get(key)
    return None


@register.filter
def species_colour(species_id, profile="cascadia"):
    """The species' colour, so a detail page's map matches Explore."""
    from ..services import species_colour as colour

    return colour(species_id, profile)


@register.simple_tag(takes_context=True)
def section_open(context, key):
    """`open` on a filter section the link says was open.

    The link carries every open section as ?open=...; with none given,
    every section starts folded.
    """
    get = context["request"].GET
    keys = get.getlist("open")
    return "open" if key in keys else ""
