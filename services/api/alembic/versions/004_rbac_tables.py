"""Add RBAC tables (roles, permissions, role_permissions, user_roles) and seed defaults

Revision ID: 004_rbac_tables
Revises: 003_spotify_cache_tables
Create Date: 2026-02-16

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "004_rbac_tables"
down_revision = "003_spotify_cache_tables"
branch_labels = None
depends_on = None

# Default permissions seeded by this migration.
_DEFAULT_PERMISSIONS: list[tuple[str, str]] = [
    ("users.manage", "Create, edit, and delete any user"),
    ("users.view_all", "View all user profiles"),
    ("roles.manage", "Create, edit, and delete roles"),
    ("own_data.view", "View own listening history and playlists"),
    ("own_data.export", "Export own listening data"),
    ("mcp_tools.use", "Invoke MCP tools (ChatGPT integration)"),
    ("playlists.write", "Create and modify playlists via MCP"),
    ("system.sync_control", "Pause, resume, and trigger sync operations"),
    ("system.logs", "View and purge system logs"),
    ("system.imports", "Upload and manage ZIP imports"),
]

# Default roles and the permission codenames they include.
_DEFAULT_ROLES: list[tuple[str, str, list[str]]] = [
    (
        "admin",
        "Full system access — manage users, roles, and all data",
        [codename for codename, _ in _DEFAULT_PERMISSIONS],  # all permissions
    ),
    (
        "user",
        "Standard user — own data, MCP tools, playlist management",
        [
            "own_data.view",
            "own_data.export",
            "mcp_tools.use",
            "playlists.write",
        ],
    ),
    (
        "viewer",
        "Read-only access to own data",
        [
            "own_data.view",
        ],
    ),
]


def upgrade() -> None:
    """Create RBAC tables and seed default roles/permissions."""

    # -- Permissions table --
    op.create_table(
        "permissions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("codename", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codename", name="uq_permissions_codename"),
    )
    op.create_index("ix_permissions_codename", "permissions", ["codename"])

    # -- Roles table --
    op.create_table(
        "roles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.create_index("ix_roles_name", "roles", ["name"])

    # -- Role-permission junction --
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.BigInteger(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "permission_id", sa.BigInteger(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )

    # -- User-role junction --
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_id", sa.BigInteger(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    # -- Seed default permissions --
    permissions_table = sa.table(
        "permissions",
        sa.column("id", sa.BigInteger),
        sa.column("codename", sa.String),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(
        permissions_table,
        [{"id": i + 1, "codename": code, "description": desc} for i, (code, desc) in enumerate(_DEFAULT_PERMISSIONS)],
    )

    # -- Seed default roles (all system roles) --
    roles_table = sa.table(
        "roles",
        sa.column("id", sa.BigInteger),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_system", sa.Boolean),
    )
    op.bulk_insert(
        roles_table,
        [
            {"id": i + 1, "name": name, "description": desc, "is_system": True}
            for i, (name, desc, _perms) in enumerate(_DEFAULT_ROLES)
        ],
    )

    # -- Seed role-permission links --
    # Build a codename → id lookup from the seeded permissions.
    perm_id_by_codename = {code: i + 1 for i, (code, _) in enumerate(_DEFAULT_PERMISSIONS)}

    rp_table = sa.table(
        "role_permissions",
        sa.column("role_id", sa.BigInteger),
        sa.column("permission_id", sa.BigInteger),
    )
    links: list[dict[str, int]] = []
    for role_idx, (_name, _desc, perm_codenames) in enumerate(_DEFAULT_ROLES):
        role_id = role_idx + 1
        for codename in perm_codenames:
            links.append({"role_id": role_id, "permission_id": perm_id_by_codename[codename]})
    op.bulk_insert(rp_table, links)


def downgrade() -> None:
    """Drop RBAC tables (junction tables first for FK ordering)."""
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("permissions")
