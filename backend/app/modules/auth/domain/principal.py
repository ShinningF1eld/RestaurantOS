from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    id: UUID
    email: str
    status: str
    session_id: UUID
