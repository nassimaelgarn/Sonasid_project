from __future__ import annotations

import datetime as _dt
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.llm.llm_sql import kpi_period_span_from_question
from backend.security.users_excel import load_users_from_excel


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    effective_question: str
    reason: str = ""
    allowed_years: Tuple[int, ...] = ()


def looks_like_kpi_question(text: str) -> bool:
    """
    Heuristic: return True only when the user is likely asking for a KPI/metric.
    Important: a bare year/date should NOT be enough to qualify as KPI, otherwise RBAC
    would affect general conversation (bad UX).
    """
    t = (text or "").lower()
    if not t.strip():
        return False
    # KPI/metric keywords (aciérie + Sonasid port / arrivages)
    keywords = [
        "kpi",
        "kip",
        "navire",
        "navires",
        "arrivage",
        "arrivages",
        "tonnage",
        "marchandise",
        "marchandises",
        "valeur",
        "valeurs",
        "importé",
        "importe",
        "importée",
        "importees",
        "importées",
        "demurrage",
        "démurrage",
        "accostage",
        "booking",
        "dechargement",
        "déchargement",
        "decharg",
        "port",
        "fournisseur",
        "qualité",
        "qualite",
        "transfert",
        "transféré",
        "transfere",
        "commande",
        "production",
        "prod",
        "consommation",
        "conso",
        "disponibilite",
        "disponibilité",
        "taux de disponibilite",
        "taux de disponibilité",
        "dispo",
        "td",
        "tr",
        "mtbf",
        "mttr",
        "rendement",
        "coul",
        "coulee",
        "coulée",
        "brame",
        "brames",
        "ferraille",
        "ferrailles",
        "oxyg",
        "gpl",
        "carbone",
        "electric",
        "élec",
        "elec",
        "gaz",
    ]
    if any(k in t for k in keywords):
        return True
    if "par mois" in t or "par semaine" in t or "par jour" in t or "par an" in t or "par année" in t:
        return True
    if re.search(r"\btop\s*\d+\b", t):
        return True
    if re.search(r"\b(résumé|resume|recap|récap|synthèse|synthese|analyse|analyser)\b", t):
        if re.search(r"\b(kpi|kip|indicateurs?|arrivages?|tonnage|tous|ensemble)\b", t):
            return True
        if re.search(r"\b20\d{2}\b", t):
            return True
    return False


def _base_dir() -> Path:
    # backend/security/access_control.py -> backend -> sonasid_project
    return Path(__file__).resolve().parents[2]


def _load_rbac_config() -> Dict[str, Any]:
    """
    Load RBAC config from:
    - env `RBAC_CONFIG_JSON` (optional JSON string)
    - file `backend/security/rbac.json` (default)
    """
    env = (os.getenv("RBAC_CONFIG_JSON", "") or "").strip()
    if env:
        try:
            return json.loads(env)
        except Exception:
            # fall back to file
            pass
    p = _base_dir() / "backend" / "security" / "rbac.json"
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}

    # Optional: load user mapping from an Excel file (editable by non-devs).
    xlsx_path = (os.getenv("RBAC_USERS_XLSX_PATH", "") or "").strip()
    if xlsx_path:
        x = load_users_from_excel(xlsx_path)
        if isinstance(cfg, dict):
            ube = cfg.get("users_by_email")
            if not isinstance(ube, dict):
                ube = {}
            # Excel overrides / extends JSON mapping
            ube = dict(ube)
            ube.update(x.users_by_email)
            cfg["users_by_email"] = ube
            ubu = cfg.get("users_by_username")
            if not isinstance(ubu, dict):
                ubu = {}
            ubu = dict(ubu)
            for uname, row in (x.local_users or {}).items():
                role = str((row or {}).get("role") or "").strip()
                if role:
                    ubu[str(uname).strip().lower()] = role
            cfg["users_by_username"] = ubu
    return cfg


def _normalize_actor(actor_name: str) -> str:
    return (actor_name or "").strip()


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _role_for_actor(cfg: Dict[str, Any], actor_name: str, actor_email: str = "", actor_username: str = "") -> str:
    """
    Resolve role for an identity.

    Priority:
    1) `users_by_email` mapping (stable for Microsoft accounts)
    2) `users_by_username` mapping (local username+code mode)
    3) `users` mapping (display_name)
    3) default_role
    """
    email = _normalize_email(actor_email)
    users_by_email = cfg.get("users_by_email") if isinstance(cfg, dict) else {}
    if isinstance(users_by_email, dict) and email and email in users_by_email and isinstance(users_by_email[email], str):
        return users_by_email[email]

    uname = (actor_username or "").strip().lower()
    users_by_username = cfg.get("users_by_username") if isinstance(cfg, dict) else {}
    if isinstance(users_by_username, dict) and uname and uname in users_by_username and isinstance(users_by_username[uname], str):
        return users_by_username[uname]

    actor = _normalize_actor(actor_name)
    users = cfg.get("users") if isinstance(cfg, dict) else {}
    if isinstance(users, dict) and actor:
        if actor in users and isinstance(users[actor], str):
            return users[actor]
        actor_low = actor.lower()
        for k, v in users.items():
            if isinstance(k, str) and isinstance(v, str) and k.strip().lower() == actor_low:
                return v
    default_role = cfg.get("default_role") if isinstance(cfg, dict) else None
    return default_role if isinstance(default_role, str) and default_role else "analyst_this_year"


def _expand_year_token(tok: str, today: _dt.date) -> Optional[int]:
    t = (tok or "").strip().lower()
    if not t:
        return None
    if t == "this_year":
        return today.year
    if t == "last_year":
        return today.year - 1
    if t.isdigit() and len(t) == 4:
        try:
            y = int(t)
            if 2000 <= y <= 2100:
                return y
        except Exception:
            return None
    return None


def allowed_years_for_actor(
    actor_name: str, *, actor_email: str = "", actor_username: str = "", today: Optional[_dt.date] = None
) -> Optional[Tuple[int, ...]]:
    """
    Returns:
    - None for allow-all (admin)
    - tuple of allowed years otherwise
    """
    cfg = _load_rbac_config()
    today = today or _dt.date.today()
    role = _role_for_actor(cfg, actor_name, actor_email, actor_username)
    roles = cfg.get("roles") if isinstance(cfg, dict) else {}
    role_def = roles.get(role) if isinstance(roles, dict) else None
    if isinstance(role_def, dict) and role_def.get("allow") == "all":
        return None
    allow_years = role_def.get("allow_years") if isinstance(role_def, dict) else None
    years: List[int] = []
    if isinstance(allow_years, list):
        for tok in allow_years:
            if not isinstance(tok, str):
                continue
            y = _expand_year_token(tok, today)
            if y is not None:
                years.append(y)
    # De-dup, stable
    years = sorted(set(years))
    return tuple(years)


def _years_in_span(span: str) -> Tuple[int, ...]:
    """
    span: 'YYYY-MM-DD..YYYY-MM-DD'
    """
    try:
        a, b = (span.split("..", 1) + [""])[:2]
        ya = int(a.split("-", 1)[0])
        yb = int(b.split("-", 1)[0])
        if ya > yb:
            ya, yb = yb, ya
        return tuple(range(ya, yb + 1))
    except Exception:
        return ()


def enforce_access_on_question(
    *,
    question: str,
    actor_name: str,
    actor_email: str = "",
    actor_username: str = "",
    today: Optional[_dt.date] = None,
    mode: str = "strict",
) -> AccessDecision:
    """
    Enforce RBAC year-based access.

    - If question has an explicit period outside the allowed years -> deny (strict) or clamp (future).
    - If question has no explicit period -> inject an allowed year window.
    """
    q = (question or "").strip()
    today = today or _dt.date.today()
    allowed = allowed_years_for_actor(actor_name, actor_email=actor_email, actor_username=actor_username, today=today)

    # allow-all role
    if allowed is None:
        return AccessDecision(allowed=True, effective_question=q, allowed_years=())

    # If no allowed years are configured, deny by default (secure).
    if not allowed:
        return AccessDecision(
            allowed=False,
            effective_question=q,
            reason="Aucune règle d’accès n’est configurée pour cet utilisateur.",
            allowed_years=(),
        )

    span = kpi_period_span_from_question(q)
    if span:
        years = _years_in_span(span)
        if years and not all(y in allowed for y in years):
            yrs = ", ".join(str(y) for y in allowed)
            return AccessDecision(
                allowed=False,
                effective_question=q,
                reason=f"Accès refusé: années autorisées = {yrs}.",
                allowed_years=allowed,
            )
        return AccessDecision(allowed=True, effective_question=q, allowed_years=allowed)

    # No explicit period -> do NOT inject a default year.
    # We prefer asking the user for a period (or using the UI-selected range),
    # otherwise answers are ambiguous ("value for which date?") and may surprise users.
    return AccessDecision(allowed=True, effective_question=q, allowed_years=allowed)


def access_denied_response(*, actor_name: str, decision: AccessDecision) -> Dict[str, Any]:
    yrs = ", ".join(str(y) for y in decision.allowed_years) if decision.allowed_years else "—"
    who = _normalize_actor(actor_name) or "Utilisateur"
    return {
        "question": decision.effective_question,
        "error": "ACCESS_DENIED",
        "source": "access:rbac",
        "message": (
            f"{who}, je ne peux pas exécuter cette demande.\n"
            f"{decision.reason}\n"
            f"Années autorisées: {yrs}."
        ),
    }

