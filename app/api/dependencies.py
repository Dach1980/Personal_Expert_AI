"""Shared API dependency exports."""
from app.api.auth import Principal, get_current_principal

__all__ = ["Principal", "get_current_principal"]
