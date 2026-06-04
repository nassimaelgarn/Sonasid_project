from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _base_dir() -> Path:
    # backend/security/profile_store.py -> backend -> project root
    return Path(__file__).resolve().parents[2]


def _profiles_path() -> Path:
    # Keep it simple: local JSON store, git-ignored by default in many setups.
    # In production you can map this to a volume if needed.
    p = (os.getenv("USER_PROFILES_JSON_PATH", "") or "").strip()
    if p:
        return Path(p).expanduser()
    return _base_dir() / "backend" / "security" / "user_profiles.json"


@dataclass(frozen=True)
class UserProfile:
    phone: str = ""
    personal_email: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"phone": self.phone, "personal_email": self.personal_email}


def _read_all() -> Dict[str, Any]:
    path = _profiles_path()
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_profile(sub: str) -> UserProfile:
    s = str(sub or "").strip()
    if not s:
        return UserProfile()
    data = _read_all()
    row = data.get(s) if isinstance(data, dict) else None
    if not isinstance(row, dict):
        return UserProfile()
    # Backward compatibility: older keys might use "address" for personal email.
    pe = str(row.get("personal_email") or "").strip()
    if not pe:
        pe = str(row.get("address") or "").strip()
    return UserProfile(
        phone=str(row.get("phone") or "").strip(),
        personal_email=pe,
    )


def update_profile(
    sub: str, *, phone: Optional[str] = None, personal_email: Optional[str] = None
) -> Tuple[bool, UserProfile]:
    s = str(sub or "").strip()
    if not s:
        return False, UserProfile()
    data = _read_all()
    if not isinstance(data, dict):
        data = {}
    cur = data.get(s) if isinstance(data.get(s), dict) else {}
    cur = dict(cur)
    if phone is not None:
        cur["phone"] = str(phone or "").strip()
    if personal_email is not None:
        cur["personal_email"] = str(personal_email or "").strip()
    data[s] = cur

    path = _profiles_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return False, get_profile(s)
    return True, get_profile(s)

