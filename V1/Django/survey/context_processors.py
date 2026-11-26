from .services import colour_profile as profile


def colour_profile(request):
    """The chosen species colour profile, for every template."""
    return {"colour_profile": profile(request)}
