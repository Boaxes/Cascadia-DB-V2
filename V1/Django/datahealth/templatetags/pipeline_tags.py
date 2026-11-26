"""Rendering helpers for the Data Pipeline page."""

from django import template
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

register = template.Library()

ARROW_SVG = ('<svg class="arrow-icon" viewBox="0 0 24 24" aria-label="to" role="img">'
             '<path d="M4 12h15M13 6l6 6-6 6"/></svg>')


@register.simple_tag
def arrow():
    return mark_safe(ARROW_SVG)


@register.filter
def arrows(text):
    """Escape the text, then draw each " -> " in it as an arrow icon."""
    return mark_safe(conditional_escape(text).replace(" -&gt; ", f" {ARROW_SVG} "))


# The site's one Title Case rule: every word is capitalised except these.
MINOR = {"a", "an", "and", "of", "or", "the"}

# Schema names, always written in lower case.
SCHEMAS = {"raw", "dbo", "app"}


@register.filter
def titlecase(text):
    """Title Case, leaving names that already carry capitals or digits (DB167, SightingT, CRC), and the
    schema names raw, dbo and app, alone."""
    words = str(text).split(" ")
    out = []
    for i, word in enumerate(words):
        core = word.strip("'\"(")
        if not core or any(c.isupper() for c in core[1:]) or any(c.isdigit() for c in core) or "_" in core:
            out.append(word)
        elif core.rstrip(":,.") in SCHEMAS:
            out.append(word)
        elif 0 < i < len(words) - 1 and core.lower() in MINOR:
            out.append(word.lower())
        else:
            lead = word[:len(word) - len(word.lstrip("'\"("))]
            parts = core.split("-")
            core = "-".join(part if j and part in MINOR else part[:1].upper() + part[1:] for j, part in enumerate(parts))
            out.append(lead + core + word[len(lead) + len(core):])
    return " ".join(out)
