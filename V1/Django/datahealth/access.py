"""
Who may do what.

Six permissions, grouped into four roles. The permissions are ordinary Django
permissions, so they can also be granted one at a time to a user in the
Django admin, and templates test them as `perms.datahealth.<name>`.

The survey models are unmanaged, so Django's migrations never create their
permissions. These six hang off a ContentType made here, by `ensure()`, which
`manage.py setup_access` runs. It is safe to run again.
"""

from functools import wraps

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib.auth.views import redirect_to_login

APP = "datahealth"

PERMISSIONS = {
    "edit_records": "Can edit efforts and sightings",
    "delete_records": "Can delete efforts and sightings",
    "export_data": "Can export data",
    "access_data_health": "Can open Cascadia Admin",
    "access_django_admin": "Can open the Django admin",
    "manage_users": "Can manage users and their permissions",
}

# Each role has what the one before it has. Viewer is the role of someone who
# can look and do nothing else.
ROLES = {
    "Viewer": [],
    "Editor": ["edit_records", "delete_records"],
    "Data Manager": ["edit_records", "delete_records", "export_data", "access_data_health"],
    "Admin": list(PERMISSIONS),
}

# What the Admin role also needs for the Django admin's User and Group pages.
ADMIN_AUTH = [f"{action}_{model}" for model in ("user", "group")
              for action in ("view", "add", "change", "delete")] + ["view_permission"]


def has(user, name):
    return user.is_active and user.has_perm(f"{APP}.{name}")


def require(name):
    """A view for people holding `name`: the sign-in page for strangers, 403 for the rest."""
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not has(request.user, name):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def _content_type():
    content_type, _ = ContentType.objects.get_or_create(app_label=APP, model="access")
    return content_type


def permissions_named(names):
    return Permission.objects.filter(content_type__app_label=APP, codename__in=names)


def role_of(user):
    """The user's role name, or None when they hold none of the four groups."""
    names = [g.name for g in user.groups.all() if g.name in ROLES]
    return max(names, key=list(ROLES).index) if names else None


def ensure():
    """Create the permissions and roles, and give anyone without a role one.

    Anyone already holding a role is left alone, so this never undoes a change
    made in the Django admin. Returns the number of users it placed.
    """
    content_type = _content_type()
    perms = {}
    for codename, name in PERMISSIONS.items():
        perms[codename], _ = Permission.objects.update_or_create(
            content_type=content_type, codename=codename, defaults={"name": name})

    auth_perms = list(Permission.objects.filter(
        content_type__app_label="auth", codename__in=ADMIN_AUTH))
    for role, names in ROLES.items():
        group, _ = Group.objects.get_or_create(name=role)
        wanted = [perms[n] for n in names] + (auth_perms if role == "Admin" else [])
        group.permissions.set(wanted)

    placed = 0
    for user in User.objects.filter(is_active=True).prefetch_related("groups"):
        if role_of(user) is None and not user.is_superuser:
            user.groups.add(Group.objects.get(name="Admin" if user.is_staff else "Viewer"))
            placed += 1
    return placed
