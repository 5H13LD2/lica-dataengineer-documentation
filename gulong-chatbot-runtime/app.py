"""
Compatibility shim for legacy entrypoints.
"""

from apps.api.main import app, create_app  # noqa: F401

__all__ = ["app", "create_app"]
