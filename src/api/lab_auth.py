"""Fail-closed, local-only access boundary until a pilot identity provider exists."""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_TOKEN_ENV = {
    "read": "FDI_API_READ_TOKEN",
    "scenario": "FDI_API_SCENARIO_TOKEN",
    "reschedule": "FDI_API_RESCHEDULE_TOKEN",
}
_ALLOWED = {
    "read": frozenset({"read", "scenario", "reschedule"}),
    "scenario": frozenset({"scenario"}),
    "reschedule": frozenset({"reschedule"}),
}
_bearer = HTTPBearer(auto_error=False)


def lab_tokens_configured(environ: Mapping[str, str] | None = None) -> bool:
    """Require distinct long secrets; partial or weak configuration stays closed."""
    values = os.environ if environ is None else environ
    tokens = [values.get(name, "") for name in _TOKEN_ENV.values()]
    return all(len(token) >= 32 for token in tokens) and len(set(tokens)) == len(tokens)


def token_allows(token: str, scope: str, environ: Mapping[str, str] | None = None) -> bool:
    """Compare digests so the check does not short-circuit on secret prefixes."""
    values = os.environ if environ is None else environ
    if not token or scope not in _ALLOWED or not lab_tokens_configured(values):
        return False
    candidate = hashlib.sha256(token.encode("utf-8")).digest()
    matched = False
    for role, name in _TOKEN_ENV.items():
        expected = hashlib.sha256(values[name].encode("utf-8")).digest()
        equal = hmac.compare_digest(candidate, expected)
        matched |= equal and role in _ALLOWED[scope]
    return matched


def require_scope(scope: str):
    """FastAPI dependency for every schedule and audit endpoint."""

    def check(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
        if not lab_tokens_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Access control is not configured.",
            )
        if credentials is None or not token_allows(credentials.credentials, scope):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return check
