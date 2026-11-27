# 006: Roles in Django

**Status:** Decided (2026-11-27, by Brandon, Q-077)
**Phase:** 2
**Spec requirements served:** ROLE-01 to ROLE-06, NAV-02, AUTH

## Question

How the spec's five roles map onto Django's groups and permissions, with no custom permission tables.

## Options

### A: Six Custom Permissions on Groups (Chosen)

- **Permissions:** six permissions are declared in `Meta.permissions` on one model with no table (`managed = False`): `browse`, `edit_records`, `manage_tracks`, `manage_audit`, `manage_users` and `view_server`.
- **Groups:** a data migration creates the groups Viewer, Editor, Track Manager, Audit Manager and Admin, and sets each group's permissions from a dictionary in code. Running it again resets permissions and never touches memberships (ROLE-05).
- **Checks:** views use `permission_required`, and templates hide controls with `perms` (ROLE-06).
- **Django Admin** checks `manage_users` instead of `is_staff`.

| Role | browse | edit_records | manage_tracks | manage_audit | manage_users | view_server |
|---|---|---|---|---|---|---|
| Viewer | Yes | | | | | |
| Editor | Yes | Yes | | | | |
| Track Manager | Yes | Yes | Yes | | | |
| Audit Manager | Yes | Yes | | Yes | | |
| Admin | Yes | Yes | Yes | Yes | Yes | Yes |

### B: Check Group Names in Views

This has fewer pieces, but role names spread through the code. Not chosen.

### C: Django's Per-Table Permissions

This means dozens of permissions to assign for six actions. Not chosen.

## Decision

A. Django's own tables hold everything: `auth_group`, `auth_permission` and `auth_group_permissions`. A user's access is the union of their groups' permissions (ROLE-03). A user with no group has no `browse` permission, so every page returns 403 (ROLE-04).
