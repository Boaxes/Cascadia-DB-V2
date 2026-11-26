"""
What the Django admin shows.

Users, groups and permissions are managed here in full. A user's role is the
group they hold (access.ROLES), shown as a column and a filter on the user
list, and changed by changing their groups. The admin writes every change to
its own log (LogEntry), which each user's History page shows.

The survey's records are listed read-only: every change to them goes through
the website, which writes the audit log and keeps the change across a rebuild,
and the admin would do neither.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from survey import models

from . import access


class RoleFilter(admin.SimpleListFilter):
    title = "Role"
    parameter_name = "role"
    NONE = "none"

    def lookups(self, request, model_admin):
        return [(role, role) for role in access.ROLES] + [(self.NONE, "No Role")]

    def queryset(self, request, queryset):
        value = self.value()
        if value == self.NONE:
            return queryset.exclude(groups__name__in=access.ROLES)
        if value in access.ROLES:
            # Someone holding two roles has the higher one (access.role_of),
            # so they are listed under that one only.
            higher = list(access.ROLES)[list(access.ROLES).index(value) + 1:]
            return queryset.filter(groups__name=value).exclude(groups__name__in=higher).distinct()
        return queryset


class RoleUserAdmin(UserAdmin):
    list_display = ("username", "name", "email", "role", "is_active", "last_login")
    list_filter = (RoleFilter, "is_active", "is_superuser")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name", "email")}),
        ("Role and Permissions", {
            "description": "A user's role is the group they hold: Viewer, Editor, Data Manager "
                           "or Admin. Each role can do everything the one before it can. "
                           "Single permissions can be added on top of a role below.",
            "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important Dates", {"fields": ("last_login", "date_joined")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("groups")

    @admin.display(description="Name", ordering="first_name")
    def name(self, user):
        return user.get_full_name()

    @admin.display(description="Role")
    def role(self, user):
        return access.role_of(user) or "No Role"


admin.site.unregister(User)
admin.site.register(User, RoleUserAdmin)


class ReadOnly(admin.ModelAdmin):
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True


for model in (models.DailyEffort, models.Sighting, models.Species, models.Vessel,
              models.Track, models.DailyCondition, models.DailyEvent, models.Sample):
    admin.site.register(model, ReadOnly)
