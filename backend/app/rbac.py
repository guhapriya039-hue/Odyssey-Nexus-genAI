"""Role-based access control resolved from request headers.

The prototype keeps identity in headers (no auth server) but the permission
model is real: every mutating endpoint declares a required permission and the
dependency enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from .constants import DEMO_ACTORS, ROLE_PERMISSIONS, Role


@dataclass(frozen=True)
class Actor:
    name: str
    role: str

    @property
    def permissions(self) -> set[str]:
        return ROLE_PERMISSIONS.get(self.role, set())

    def has(self, permission: str) -> bool:
        return permission in self.permissions


async def current_actor(
    x_odyssey_user: str | None = Header(default=None, alias="X-Odyssey-User"),
    x_odyssey_role: str | None = Header(default=None, alias="X-Odyssey-Role"),
) -> Actor:
    role = (x_odyssey_role or Role.ANALYST).strip().lower()
    if role not in ROLE_PERMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown role '{role}'. Allowed: {sorted(ROLE_PERMISSIONS)}",
        )
    name = (x_odyssey_user or DEMO_ACTORS.get(role, "analyst@odyssey.team")).strip()
    return Actor(name=name[:160], role=role)


def require(permission: str):
    """Dependency factory enforcing a single permission."""

    async def _dependency(actor: Actor = Depends(current_actor)) -> Actor:
        if not actor.has(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{actor.role}' lacks permission '{permission}'",
            )
        return actor

    return _dependency
