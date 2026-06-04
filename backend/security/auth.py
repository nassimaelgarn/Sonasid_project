from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import jwt  # PyJWT
from jwt import PyJWKClient
import requests


@dataclass(frozen=True)
class AuthUser:
    sub: str
    display_name: str
    email: str
    auth_provider: str  # "local" | "microsoft"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def hash_password(password: str, *, salt_b64: Optional[str] = None, iterations: int = 160_000) -> Dict[str, Any]:
    """
    PBKDF2 password hash: returns a dict that can be stored in config/db.
    """
    pwd = (password or "").encode("utf-8")
    if salt_b64:
        salt = base64.b64decode(salt_b64.encode("utf-8"))
    else:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pwd, salt, iterations, dklen=32)
    return {
        "alg": "pbkdf2_sha256",
        "iterations": iterations,
        "salt_b64": base64.b64encode(salt).decode("utf-8"),
        "hash_b64": base64.b64encode(dk).decode("utf-8"),
    }


def verify_password(password: str, spec: Dict[str, Any]) -> bool:
    try:
        if (spec or {}).get("alg") != "pbkdf2_sha256":
            return False
        iters = int(spec.get("iterations") or 0)
        salt_b64 = str(spec.get("salt_b64") or "")
        expected = str(spec.get("hash_b64") or "")
        if not iters or not salt_b64 or not expected:
            return False
        computed = hash_password(password, salt_b64=salt_b64, iterations=iters)
        return hmac.compare_digest(computed["hash_b64"], expected)
    except Exception:
        return False


# ---------------- Microsoft SSO (Entra ID) ----------------


def _microsoft_cfg() -> Dict[str, str]:
    return {
        "tenant_id": (os.getenv("AZURE_AD_TENANT_ID", "") or "").strip(),
        "client_id": (os.getenv("AZURE_AD_CLIENT_ID", "") or "").strip(),
        "client_secret": (os.getenv("AZURE_AD_CLIENT_SECRET", "") or "").strip(),
        "redirect_uri": (os.getenv("AZURE_AD_REDIRECT_URI", "") or "").strip(),
    }


def microsoft_enabled() -> bool:
    c = _microsoft_cfg()
    return bool(c["tenant_id"] and c["client_id"] and c["client_secret"] and c["redirect_uri"])


_MS_OAUTH_STATE_TTL_SEC = 900  # 15 minutes — Microsoft round-trip + user MFA


def mint_microsoft_oauth_state(
    *,
    secret: str,
    nonce: str,
    redirect_uri: str,
    return_to: str = "",
) -> str:
    """
    Signed OAuth `state` so /auth/microsoft/callback can be validated without relying on
    the session cookie surviving a cross-site redirect (Safari / split localhost vs 127.0.0.1).
    """
    body = {
        "v": 1,
        "iat": int(time.time()),
        "n": (nonce or "")[:80],
        "ru": (redirect_uri or "").strip()[:500],
        "rt": (return_to or "").strip()[:450],
    }
    raw = _b64url(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig = hmac.new((secret or "dev").encode("utf-8"), raw.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{raw}.{sig}"


def parse_microsoft_oauth_state(state: str, *, secret: str) -> Optional[Dict[str, Any]]:
    """Verify signature and TTL; return body dict or None."""
    try:
        s = (state or "").strip()
        if "." not in s:
            return None
        raw, sig = s.rsplit(".", 1)
        if len(sig) != 32 or len(raw) < 8:
            return None
        exp = hmac.new((secret or "dev").encode("utf-8"), raw.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(exp, sig):
            return None
        pad = "=" * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode((raw + pad).encode("ascii")).decode("utf-8"))
        if not isinstance(data, dict) or data.get("v") != 1:
            return None
        iat = int(data.get("iat") or 0)
        now = int(time.time())
        if now - iat > _MS_OAUTH_STATE_TTL_SEC or iat - now > 120:
            return None
        return data
    except Exception:
        return None


def microsoft_missing_env_vars() -> list[str]:
    """
    Return missing env vars required for Microsoft SSO.
    Useful to provide actionable errors to the UI.
    """
    c = _microsoft_cfg()
    missing: list[str] = []
    if not c["tenant_id"]:
        missing.append("AZURE_AD_TENANT_ID")
    if not c["client_id"]:
        missing.append("AZURE_AD_CLIENT_ID")
    if not c["client_secret"]:
        missing.append("AZURE_AD_CLIENT_SECRET")
    if not c["redirect_uri"]:
        missing.append("AZURE_AD_REDIRECT_URI")
    return missing


def microsoft_authorize_url(*, state: str, nonce: str, redirect_uri: Optional[str] = None) -> str:
    c = _microsoft_cfg()
    tenant = c["tenant_id"]
    ru = (redirect_uri or "").strip() or c["redirect_uri"]
    params = {
        "client_id": c["client_id"],
        "response_type": "code",
        "redirect_uri": ru,
        "response_mode": "query",
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        # Force an account picker so users can switch accounts easily
        # (otherwise Microsoft may auto-login the last signed-in account).
        "prompt": "select_account",
    }
    q = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{q}"


def _jwks_client(tenant_id: str) -> PyJWKClient:
    url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    return PyJWKClient(url)


def microsoft_exchange_code_for_user(
    code: str,
    *,
    redirect_uri: Optional[str] = None,
    expected_nonce: Optional[str] = None,
) -> AuthUser:
    """
    Exchange authorization code -> tokens, verify ID token, return AuthUser.
    """
    c = _microsoft_cfg()
    tenant = c["tenant_id"]
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    data = {
        "client_id": c["client_id"],
        "client_secret": c["client_secret"],
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": (redirect_uri or "").strip() or c["redirect_uri"],
        "scope": "openid profile email",
    }
    resp = requests.post(token_url, data=data, timeout=20)
    resp.raise_for_status()
    tok = resp.json()
    id_token = tok.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise RuntimeError("Missing id_token from Microsoft token endpoint")

    jwk_client = _jwks_client(tenant)
    # Validate issuer/audience/signature.
    # Azure v2 issuer example: https://login.microsoftonline.com/{tenant}/v2.0
    issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
    signing_key = jwk_client.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        key=signing_key.key,
        algorithms=["RS256"],
        audience=c["client_id"],
        issuer=issuer,
        options={"verify_at_hash": False},
    )

    if expected_nonce:
        got = str(claims.get("nonce") or "")
        if not got or not hmac.compare_digest(got, str(expected_nonce)):
            raise RuntimeError("Invalid Microsoft token: nonce mismatch")

    sub = str(claims.get("oid") or claims.get("sub") or "")
    email = str(claims.get("preferred_username") or claims.get("email") or "")
    display = str(claims.get("name") or email or sub)
    if not sub:
        raise RuntimeError("Invalid Microsoft token: missing subject")
    return AuthUser(sub=sub, email=email, display_name=display, auth_provider="microsoft")

