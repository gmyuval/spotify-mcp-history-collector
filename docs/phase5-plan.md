# Phase 5: Admin UI for RBAC & User Management

## Context

Phases 0-4 are complete. The RBAC foundation exists (models, migrations, PermissionChecker) but has no admin-facing API endpoints or UI. Phase 5 adds role/permission CRUD endpoints to the admin API, a new Roles page to the admin frontend, and role assignment on the user detail page.

## Design Decisions

1. **RBAC methods go in existing `AdminService`** — not a new service. It already handles all admin operations.
2. **Permission assignment: full replacement on PUT** — send complete list of permission codenames. Simpler than add/remove, matches checkbox UX.
3. **User role assignment: full replacement via PUT** — send list of role IDs. Same pattern as permissions.
4. **Separate `/roles` page** — dedicated page with sidebar entry. User detail page gets a "Roles" card for inline role assignment.

## Files to Modify (Backend API)

### 1. `services/api/src/app/admin/schemas.py` — Add RBAC schemas
- `PermissionResponse` (id, codename, description)
- `RoleSummary` (id, name, description, is_system, permissions list, timestamps)
- `CreateRoleRequest` (name, description, permission_codenames)
- `UpdateRoleRequest` (name?, description?, permission_codenames?)
- `UserRoleAssignment` (role_ids list)
- `UserRolesResponse` (user_id, roles list)

### 2. `services/api/src/app/admin/service.py` — Add RBAC business logic
New methods on `AdminService`:
- `list_roles(session)` — eager-load permissions via `selectinload`
- `list_permissions(session)` — all permissions ordered by codename
- `create_role(name, description, permission_codenames, session)` — validate perms, create role + junction rows
- `update_role(role_id, name, description, permission_codenames, session)` — block rename of system roles, full-replace permissions
- `delete_role(role_id, session)` — block deletion of system roles
- `get_user_roles(user_id, session)` — user's roles with permissions
- `set_user_roles(user_id, role_ids, session)` — full-replace user's role assignments
- Helper: `_role_to_summary()`, `_get_role_or_raise()`, `_get_permission_map()`

### 3. `services/api/src/app/admin/router.py` — Add 7 endpoints
New routes (all behind `require_admin`):
- `GET /admin/roles` → `list[RoleSummary]`
- `GET /admin/permissions` → `list[PermissionResponse]`
- `POST /admin/roles` → `RoleSummary` (201)
- `PUT /admin/roles/{role_id}` → `RoleSummary`
- `DELETE /admin/roles/{role_id}` → `ActionResponse`
- `GET /admin/users/{user_id}/roles` → `UserRolesResponse`
- `PUT /admin/users/{user_id}/roles` → `ActionResponse`

Error mapping: `ValueError` → 400/404, `IntegrityError` → 409.

## Files to Modify (Frontend)

### 4. `services/frontend/src/frontend/api_client.py` — Add 7 API client methods
- `list_roles()`, `list_permissions()`, `create_role()`, `update_role()`, `delete_role()`
- `get_user_roles(user_id)`, `set_user_roles(user_id, role_ids)`
- Widen `_request()` return type from `dict[str, Any]` to `Any` (list endpoints return lists)

### 5. `services/frontend/src/frontend/routes/roles.py` — NEW: Roles page router
Class-based router (same pattern as `users.py`):
- `GET /roles/` — list roles + permissions, render `roles.html`
- `POST /roles/create` — HTMX form to create role
- `POST /roles/{role_id}/update` — HTMX form to update role
- `POST /roles/{role_id}/delete` — HTMX button to delete role

### 6. `services/frontend/src/frontend/routes/users.py` — Extend user detail
- Fetch all roles + user's roles in `user_detail()` (parallel with existing calls)
- Add `POST /users/{user_id}/set-roles` handler for HTMX role assignment form
- Pass `all_roles` and `user_role_ids` to template context

### 7. `services/frontend/src/frontend/routes/__init__.py` — Export roles router
### 8. `services/frontend/src/frontend/main.py` — Register roles router at `/roles`

## Templates

### 9. `services/frontend/src/frontend/templates/base.html` — Add "Roles" sidebar link
Between "Users" and "Job Runs" in the nav.

### 10. `services/frontend/src/frontend/templates/roles.html` — NEW: Roles page
- Card per role: name, description, system badge, permission checkboxes, save/delete buttons
- "Create New Role" card at bottom with form
- HTMX-powered: forms POST to `/roles/create`, `/roles/{id}/update`, `/roles/{id}/delete`
- Alert area for success/error feedback

### 11. `services/frontend/src/frontend/templates/user_detail.html` — Add Roles card
- Checkboxes for all available roles, pre-checked for assigned roles
- HTMX form POSTs to `/users/{id}/set-roles`

## Tests

### 12. `services/api/tests/test_admin/test_rbac.py` — NEW: Role CRUD + user role API tests
~15 tests covering:
- List roles/permissions
- Create role (success, duplicate name 409, invalid permission 400)
- Update role (permissions, system rename blocked, not found)
- Delete role (custom ok, system blocked, not found)
- User roles: get empty, set, replace, invalid role 400, user not found 404

### 13. `services/frontend/tests/test_routes.py` — Append roles page + user roles tests
~7 tests: roles page, create/update/delete role, user detail shows roles, set user roles

### 14. `services/frontend/tests/test_api_client.py` — Append RBAC client tests
~7 tests with respx mocking for each new API client method

### 15. `services/frontend/tests/conftest.py` — Add mock defaults for RBAC methods

## Implementation Order

1. Backend schemas → service → router
2. Backend tests (validate API)
3. Frontend API client + tests
4. Frontend roles route + templates + user detail update
5. Frontend route tests + conftest updates
6. `make lint && make typecheck && make test`

## Verification

- `make lint` — ruff check + format passes
- `make typecheck` — mypy passes
- `pytest services/api/tests/` — all API tests pass including new RBAC tests
- `cd services/frontend && pytest tests/` — all frontend tests pass
- Manual: visit `/roles` page, create/edit/delete roles, assign roles to users on detail page
