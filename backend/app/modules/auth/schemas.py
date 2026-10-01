from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.auth.domain.policies import normalize_email


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = normalize_email(value)
        if (
            value.count("@") != 1
            or any(character.isspace() for character in value)
            or not all(value.split("@"))
        ):
            raise ValueError("Invalid email")
        return value


class UserSummary(BaseModel):
    id: UUID
    email: str
    status: str
