"""The three organization roles; capability policies are a subsequent slice."""

from enum import StrEnum


class MembershipRole(StrEnum):
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"
