"""Tenant administration contracts; identity and scope remain server-derived."""

from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from app.modules.tenancy.domain.roles import MembershipRole


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    number: int
    name: str
    slug: str


class MembershipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    role: MembershipRole
    restaurant_ids: list[int] = Field(default_factory=list, max_length=100)


class MembershipUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: MembershipRole | None = None
    restaurant_ids: list[int] | None = Field(default=None, max_length=100)


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    organization_id: UUID
    role: MembershipRole
    status: str


class AccessResponse(BaseModel):
    organization_id: UUID
    organization_number: int
    role: MembershipRole
    capabilities: list[str]
    restaurant_ids: list[int]
