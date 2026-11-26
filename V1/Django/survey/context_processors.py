from django.http import QueryDict

from .services import colour_profile as profile


def colour_profile(request):
    """The chosen species colour profile, for every template."""
    return {"colour_profile": profile(request)}


def research_group_query(request):
    """The Research Group choice as a query string, for the links between
    pages. Nothing chosen is the default (CRC) and needs no parameter, so only
    a choice of other groups, or of all of them, is carried from one page to
    the next."""
    values = [v for v in request.GET.getlist("research_group") if v.strip()]
    if not values:
        return {"research_group_query": ""}
    query = QueryDict(mutable=True)
    query.setlist("research_group", values)
    return {"research_group_query": "?" + query.urlencode()}


def export_count(request):
    """How many queries wait in the export, for the Export link in the bar."""
    from .export_stack import count
    return {"export_count": count(request) if hasattr(request, "session") else 0}
