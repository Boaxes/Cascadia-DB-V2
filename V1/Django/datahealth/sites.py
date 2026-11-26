"""The Django admin, opened by a permission of ours rather than by is_staff."""

from functools import update_wrapper

from django.contrib.admin import AdminSite
from django.urls import path
from django.core.exceptions import PermissionDenied

from . import access


class AccessAdminSite(AdminSite):
    site_header = "Django Admin"
    site_title = "Django Admin"
    index_title = "Site Administration"
    # The header bar links Users and Groups, and the home page lists the rest,
    # so the list pages keep the width for their columns.
    enable_nav_sidebar = False

    def has_permission(self, request):
        return access.has(request.user, "access_django_admin")

    def admin_view(self, view, cacheable=False):
        guarded = super().admin_view(view, cacheable)

        def wrapped(request, *args, **kwargs):
            # Someone signed in without the permission is refused outright,
            # not sent round to a login page that cannot help them.
            if request.user.is_authenticated and not self.has_permission(request):
                raise PermissionDenied
            return guarded(request, *args, **kwargs)
        return update_wrapper(wrapped, view)

    def login(self, request, extra_context=None):
        # Everyone signs in on the site's own page. The admin's form only lets
        # staff through, which is not the rule here.
        if request.user.is_authenticated:
            raise PermissionDenied
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())

    def get_urls(self):
        # The Server page: the server's log and a graph of how it is doing. Wrapped by admin_view, so it
        # needs the same permission as the rest of the admin and sends a stranger to
        # the site's sign-in page.
        from . import server_views
        pages = [("server/", server_views.server, "server"),
                 ("server/feed.json", server_views.server_feed, "server_feed")]
        return [path(route, self.admin_view(view), name=name) for route, view, name in pages] + super().get_urls()
