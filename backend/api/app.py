import os
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv

    # Charge `sonasid_project/.env` (clés API, USE_AGENT, KPI_REWRITE_LLM, etc.)
    _env_path = Path(__file__).resolve().parents[2] / ".env"
    # Override to ensure local auth/RBAC config is picked up on restart.
    load_dotenv(_env_path, override=True)
except ImportError:
    pass

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

from backend.pipeline.pipeline import process_question
from backend.rag.store import (
    add_chat_feedback,
    add_memory,
    delete_conversation,
    get_conversation_history,
    list_conversations,
)
from backend.agent.graph import run_agent
from backend.llm.llm_sql import (
    kpi_period_span_from_question,
    merge_kpi_followup_from_history,
    merge_need_period_followup_from_history,
    merge_table_format_followup_from_history,
)
from backend.security.access_control import (
    access_denied_response,
    allowed_years_for_actor,
    enforce_access_on_question,
    looks_like_kpi_question,
)
from backend.security.users_excel import load_users_from_excel
from backend.security.users_excel import update_local_code_in_excel
from backend.security.profile_store import get_profile, update_profile
from backend.security.auth import (
    microsoft_authorize_url,
    microsoft_enabled,
    microsoft_exchange_code_for_user,
    microsoft_missing_env_vars,
    mint_microsoft_oauth_state,
    parse_microsoft_oauth_state,
    verify_password,
)

_SESSION_SECRET = (os.getenv("SESSION_SECRET", "") or "dev-unsafe-secret").strip()


def _user_scope_prefix(request: Request) -> str:
    try:
        u = (request.session or {}).get("user") if hasattr(request, "session") else None
        if isinstance(u, dict) and u.get("sub"):
            return f"{str(u.get('sub')).strip()}::"
    except Exception:
        pass
    return "anon::"


def _scope_session_id(request: Request, session_id: str) -> str:
    sid = (session_id or "").strip() or "default"
    return _user_scope_prefix(request) + sid


def _unscope_session_id(prefix: str, scoped: str) -> str:
    s = str(scoped or "")
    return s[len(prefix) :] if prefix and s.startswith(prefix) else s

class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    model_name: Optional[str] = None
    actor_name: Optional[str] = None
    # Optional UI-supplied period selection. Backend decides whether to apply it.
    period_preset: Optional[str] = None  # e.g. none|ytd|7d|30d|month|custom
    period: Optional[Dict[str, str]] = None  # { start: "YYYY-MM-DD", end: "YYYY-MM-DD" }


class FeedbackRequest(BaseModel):
    """Retour utilisateur sur une réponse assistant (collecte pour qualité / futur affinage)."""

    session_id: Optional[str] = None
    rating: int  # 1 = utile, -1 = pas utile
    user_question: str
    assistant_content: str
    model_name: Optional[str] = None


class ChatRetryRequest(BaseModel):
    """Régénération après 👎 : même session / modèle, consigne de correction."""

    session_id: Optional[str] = None
    model_name: Optional[str] = None
    user_question: str
    assistant_content: str


class LocalLoginRequest(BaseModel):
    username: str
    password: str


class UpdateProfileRequest(BaseModel):
    phone: Optional[str] = None
    personal_email: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


_FATAL_CHAT_ERRORS = frozenset({"RATE_LIMIT", "INSUFFICIENT_CREDITS", "SERVER_ERROR", "Réponse pipeline invalide"})


def _build_correction_question(*, user_question: str, assistant_content: str, max_bad: int = 8000) -> str:
    uq = (user_question or "").strip()
    bad = (assistant_content or "").strip()
    if len(bad) > max_bad:
        bad = bad[: max_bad - 24].rstrip() + "\n…(tronqué)"
    return (
        "[Auto-correction KPI]\n"
        "L'utilisateur a signalé que ta réponse précédente était inutile ou incorrecte.\n\n"
        f"Question initiale (à traiter à nouveau — vérifie période, unités, KPI et cohérence des chiffres) :\n{uq}\n\n"
        "Réponse précédente rejetée (ne pas la recopier ; corrige les erreurs éventuelles) :\n"
        f"{bad}\n\n"
        "Donne une nouvelle réponse complète et vérifiable."
    )

def _infer_conso_type_from_text(text: str) -> str:
    t = (text or "").lower()
    if any(x in t for x in ["électricité", "electricite", "électrique", "electrique", "elec", "élec"]):
        return "électrique"
    if any(x in t for x in ["oxygène", "oxygene", "oxyg"]):
        return "oxygène"
    if "gpl" in t or "gaz" in t:
        return "gpl"
    if "carbone" in t or "carbon" in t:
        return "carbone"
    return ""


def _auto_disambiguate_retry_question(*, user_question: str, assistant_content: str) -> str:
    """
    Some intents are handled deterministically by the agent router (e.g. ambiguous "consommation" → clarify).
    On retry after 👎, prefer a best-effort answer instead of asking the same clarification again.
    """
    uq = (user_question or "").strip()
    ql = uq.lower()

    conso_words = ("conso", "consommation", "consommer", "consommateurs")
    conso_types = ("élec", "elec", "électrique", "electrique", "electricite", "électricité", "oxyg", "oxygene", "oxygène", "gpl", "carbone", "carbon", "gaz")

    if any(w in ql for w in conso_words) and not any(w in ql for w in conso_types):
        inferred = _infer_conso_type_from_text(uq) or _infer_conso_type_from_text(assistant_content)
        # Default to "électrique" (most common in this app) if we can't infer.
        inferred = inferred or "électrique"
        # Keep original phrasing but make it unambiguous for the router/pipeline.
        if "consommation" in ql:
            return f"{uq} {inferred}".strip()
        return f"consommation {inferred} {uq}".strip()

    return uq


def _assistant_memory_content(res: Dict[str, Any]) -> str:
    content: Optional[str] = None
    try:

        def _fmt_num(v: Any) -> str:
            try:
                if isinstance(v, bool):
                    return str(v)
                if isinstance(v, (int, float)):
                    if isinstance(v, int):
                        return f"{v:,}".replace(",", " ")
                    return f"{v:.2f}"
            except Exception:
                pass
            return str(v)

        def _format_rows_preview(rows: Any, limit: int = 5) -> Optional[str]:
            if not isinstance(rows, list) or not rows:
                return None
            first = rows[0]
            if not isinstance(first, dict):
                return None
            keys = list(first.keys())[:4]
            lines = []
            simple_period_value = ("period" in keys and "value" in keys and all(k in {"period", "value"} for k in keys))
            for i, r in enumerate(rows[:limit]):
                if not isinstance(r, dict):
                    continue
                if simple_period_value:
                    lines.append(f"{r.get('period')}: {_fmt_num(r.get('value'))}")
                else:
                    parts = [f"{k}: {_fmt_num(r.get(k))}" for k in keys]
                    lines.append(" · ".join(parts))
            return "\n".join(lines)

        # Prefer persisting SQL payloads (otherwise history loses the actual query).
        if isinstance(res.get("sql"), str) and str(res.get("sql") or "").strip():
            payload = {
                "__kind": "sql",
                "message": str(res.get("message") or "Voici la requête SQL utilisée.").strip(),
                "sql": str(res.get("sql") or "").strip(),
            }
            if isinstance(res.get("tsql"), str) and str(res.get("tsql") or "").strip():
                payload["tsql"] = str(res.get("tsql") or "").strip()
            content = json.dumps(payload, ensure_ascii=False)
        elif isinstance(res.get("sqls"), dict) and (res.get("sqls") or {}):
            sqls = res.get("sqls") or {}
            payload = {
                "__kind": "sqls",
                "message": str(res.get("message") or "Voici les requêtes SQL utilisées.").strip(),
                "sqls": {
                    "eaf": str(sqls.get("eaf") or "").strip(),
                    "lf": str(sqls.get("lf") or "").strip(),
                },
            }
            tsqls = res.get("tsqls") if isinstance(res.get("tsqls"), dict) else None
            if tsqls:
                payload["tsqls"] = {
                    "eaf": str(tsqls.get("eaf") or "").strip(),
                    "lf": str(tsqls.get("lf") or "").strip(),
                }
            content = json.dumps(payload, ensure_ascii=False)
        elif res.get("message"):
            content = str(res.get("message"))
        elif isinstance(res.get("TD_percent"), (int, float)):
            content = f"TD: {_fmt_num(res.get('TD_percent'))}%"
        elif isinstance(res.get("TR_percent"), (int, float)):
            content = f"TR: {_fmt_num(res.get('TR_percent'))}%"
        elif isinstance(res.get("Rendement_percent"), (int, float)):
            content = f"Rendement: {_fmt_num(res.get('Rendement_percent'))}%"
        elif isinstance(res.get("MTBF_secondes"), (int, float)):
            content = f"MTBF_secondes: {_fmt_num(res.get('MTBF_secondes'))}"
        elif isinstance(res.get("MTTR_secondes"), (int, float)):
            content = f"MTTR_secondes: {_fmt_num(res.get('MTTR_secondes'))}"
        elif isinstance(res.get("result"), list):
            rows = res.get("result")
            preview = _format_rows_preview(rows)
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                cap = int(os.getenv("HISTORY_ROWS_CAP", "200") or "200")
                table_payload = {
                    "__kind": "kpi_table",
                    "rows": rows[:cap],
                    "rows_total": len(rows),
                    "truncated": len(rows) > cap,
                    "preview": preview,
                }
                content = json.dumps(table_payload, ensure_ascii=False)
            else:
                content = preview or f"Résultats: {len(res['result'])} lignes"
        elif isinstance(res.get("result"), (int, float)):
            content = f"Résultat: {_fmt_num(res.get('result'))}"
        else:
            safe = {k: v for k, v in res.items() if k not in {"question", "llm_sql", "llm_reason"}}
            content = json.dumps(safe, ensure_ascii=False)[:4000]
    except Exception:
        content = None

    if not content:
        try:
            if isinstance(res.get("result"), list):
                content = f"Résultats: {len(res.get('result') or [])} lignes"
            elif res.get("message"):
                content = str(res.get("message"))
            else:
                content = json.dumps(res, ensure_ascii=False)[:2000]
        except Exception:
            content = "OK."
    return content or "OK."


def _persist_assistant_memory(*, session_id: str, res: Dict[str, Any]) -> None:
    try:
        add_memory(
            session_id=session_id or "default",
            role="assistant",
            content=_assistant_memory_content(res),
        )
    except Exception as e:
        try:
            print("WARN: add_memory assistant failed:", repr(e))
        except Exception:
            pass


def _skip_assistant_persist(res: Dict[str, Any]) -> bool:
    err = res.get("error")
    return isinstance(err, str) and err in _FATAL_CHAT_ERRORS


def _run_chat_pipeline(
    question: str,
    session_id: Optional[str],
    model_name: str,
    *,
    echo_question: str,
    actor_name: str = "",
) -> Dict[str, Any]:
    use_agent = os.getenv("USE_AGENT", "false").strip().lower() in {"1", "true", "yes", "on"}
    actor = (actor_name or "").strip()
    try:
        from backend.llm.conversational import (
            conversational_reply,
            is_pure_greeting,
            should_use_kpi_pipeline,
        )
        from backend.llm.llm_sql import normalize_user_question
        from backend.llm.sonasid_resilience import (
            should_force_kpi_pipeline,
            soften_pipeline_failure,
            try_deterministic_sonasid_reply,
        )

        question = normalize_user_question(question)

        det = try_deterministic_sonasid_reply(question)
        if det:
            res = det
        elif is_pure_greeting(question):
            res = conversational_reply(
                question,
                actor_name=actor,
                session_id=session_id,
                model_name=model_name or "",
            )
        elif use_agent:
            res = run_agent(
                question=question,
                session_id=session_id,
                model_name=model_name or "",
                actor_name=actor,
            )
        elif should_use_kpi_pipeline(question) or should_force_kpi_pipeline(question):
            res = soften_pipeline_failure(
                process_question(
                    question,
                    model_name=model_name or "",
                    session_id=session_id,
                ),
                question,
                model_name=model_name or "",
            )
        else:
            res = conversational_reply(
                question,
                actor_name=actor,
                session_id=session_id,
                model_name=model_name or "",
            )
    except Exception as e:
        msg = str(e)
        is_rate_limit = "RateLimitError" in msg or "rate limit" in msg.lower() or "Error code: 429" in msg
        is_insufficient_credits = "Error code: 402" in msg or "insufficient credits" in msg.lower()

        if is_rate_limit or is_insufficient_credits:
            requested = (model_name or "").strip().lower()
            if use_agent and requested in {"trinity"}:
                try:
                    res2 = run_agent(
                        question=question,
                        session_id=session_id,
                        model_name="flash",
                        actor_name=(actor_name or "").strip(),
                    )
                    if isinstance(res2, dict):
                        res2 = dict(res2)
                        res2.setdefault("question", echo_question)
                        res2.setdefault("notice", "Trinity indisponible. Bascule automatique sur Flash (free).")
                        return res2
                except Exception:
                    pass

            fallback = process_question(
                question,
                model_name=model_name or "",
                session_id=session_id,
            )
            if isinstance(fallback, dict):
                fallback = dict(fallback)
                fallback.setdefault("question", echo_question)
                fallback.setdefault("source", "fallback:pipeline")
                fallback.setdefault(
                    "notice",
                    "LLM indisponible (limite/crédits). Réponse générée sans LLM.",
                )
                return fallback
            if is_insufficient_credits:
                return {
                    "question": echo_question,
                    "error": "INSUFFICIENT_CREDITS",
                    "message": "Crédits OpenRouter insuffisants. Ajoute du crédit ou change de clé/modèle. Réponse impossible via LLM.",
                }
            return {
                "question": echo_question,
                "error": "RATE_LIMIT",
                "message": "Limite de requêtes atteinte côté LLM (OpenRouter). Réessaie dans quelques minutes, ou change de modèle / ajoute du crédit.",
            }
        return {"question": echo_question, "error": "SERVER_ERROR", "message": msg}
    if not isinstance(res, dict):
        return {"question": echo_question, "error": "Réponse pipeline invalide"}
    return res


app = FastAPI(title="Sonasid KPI API", version="0.1.0")

# Server-side session cookie (used for both local login and Microsoft SSO).
app.add_middleware(SessionMiddleware, secret_key=_SESSION_SECRET, same_site="lax", https_only=False)

origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
cors_origin_regex = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"^https?://(localhost|127\.0\.0\.1|\d{1,3}(?:\.\d{1,3}){3}|[\w.-]+\.cloudapp\.azure\.com)(:\d+)?$",
).strip() or None
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/chat/models")
def chat_models() -> Dict[str, Any]:
    """Modèles disponibles dans le sélecteur UI (config .env)."""
    from backend.llm.model_registry import chat_models_for_api, default_chat_model_id

    return {
        "ok": True,
        "default": default_chat_model_id(),
        "models": chat_models_for_api(),
    }


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    """Santé API + indicateurs de déploiement (vérif. règles Sonasid actives)."""
    try:
        from backend.llm import sonasid_sql as ss

        mod = getattr(ss, "__file__", "") or ""
        src = Path(mod).read_text(encoding="utf-8", errors="replace") if mod else ""
        marchandise_ok = "marchandises" in src and "_is_tonnage_importe_question" in src
    except Exception:
        marchandise_ok = False
    return {
        "status": "ok",
        "db_provider": (os.getenv("DB_PROVIDER", "") or "").strip(),
        "azure_sql_profile": (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip(),
        "sonasid_marchandise_rules": marchandise_ok,
    }


def _session_user(request: Request) -> Optional[Dict[str, Any]]:
    u = (request.session or {}).get("user") if hasattr(request, "session") else None
    return u if isinstance(u, dict) else None


@app.get("/db/status")
def db_status(request: Request) -> Dict[str, Any]:
    """État connexion Azure SQL (authentification requise)."""
    if not _session_user(request):
        return {"ok": False, "authenticated": False, "error": "AUTH_REQUIRED"}
    from backend.database.azure_sql import azure_config, db_provider, is_azure_provider, ping

    provider = db_provider()
    cfg = azure_config()
    out: Dict[str, Any] = {
        "authenticated": True,
        "provider": provider,
        "azure_profile": cfg.get("profile"),
        "server": cfg.get("server"),
        "database": cfg.get("database"),
        "user": cfg.get("user"),
        "kpi_rules": "sonasid_azure" if cfg.get("profile") in {"sonasid", "shipping", "port"} else "acierie_legacy",
    }
    if is_azure_provider(provider):
        out["connection"] = ping()
    else:
        out["connection"] = {"ok": True, "note": "SQLite local (db/sonasid.db)"}
    return out


@app.get("/db/tables")
def db_tables(request: Request, schema: str = "dbo", limit: int = 500) -> Dict[str, Any]:
    if not _session_user(request):
        return {"ok": False, "authenticated": False, "error": "AUTH_REQUIRED"}
    from backend.database.azure_sql import db_provider, is_azure_provider, list_tables

    if not is_azure_provider():
        return {"ok": False, "error": "DB_PROVIDER doit être azure pour lister les tables"}
    try:
        tables = list_tables(schema=schema, limit=limit)
        return {"ok": True, "schema": schema, "count": len(tables), "tables": tables}
    except Exception as e:
        return {"ok": False, "error": str(e) or repr(e)}


@app.get("/db/columns")
def db_columns(request: Request, table: str, schema: str = "dbo") -> Dict[str, Any]:
    if not _session_user(request):
        return {"ok": False, "authenticated": False, "error": "AUTH_REQUIRED"}
    from backend.database.azure_sql import is_azure_provider, list_columns

    if not is_azure_provider():
        return {"ok": False, "error": "DB_PROVIDER doit être azure"}
    try:
        cols = list_columns(table=table, schema=schema)
        return {"ok": True, "schema": schema, "table": table, "columns": cols}
    except Exception as e:
        return {"ok": False, "error": str(e) or repr(e)}


@app.get("/db/relations")
def db_relations(request: Request, table: str = "", schema: str = "dbo") -> Dict[str, Any]:
    """Clés étrangères Azure SQL (optionnel : filtrer par table)."""
    if not _session_user(request):
        return {"ok": False, "authenticated": False, "error": "AUTH_REQUIRED"}
    from backend.database.azure_sql import is_azure_provider, list_foreign_keys

    if not is_azure_provider():
        return {"ok": False, "error": "DB_PROVIDER doit être azure"}
    try:
        rels = list_foreign_keys(table=table.strip(), schema=schema)
        return {"ok": True, "schema": schema, "table": table or None, "count": len(rels), "relations": rels}
    except Exception as e:
        return {"ok": False, "error": str(e) or repr(e)}


@app.get("/db/schema")
def db_schema_table(request: Request, table: str, schema: str = "dbo") -> Dict[str, Any]:
    """Schéma complet d'une table : dictionnaire + colonnes + FK (pour debug / intégration)."""
    if not _session_user(request):
        return {"ok": False, "authenticated": False, "error": "AUTH_REQUIRED"}
    t = (table or "").strip()
    if not t:
        return {"ok": False, "error": "Paramètre table requis"}
    try:
        from backend.llm.sonasid_schema import build_live_table_structure_message, extract_table_name_from_question

        name = extract_table_name_from_question(f"table {t}") or t.upper()
        message = build_live_table_structure_message(name)
        from backend.database.azure_sql import is_azure_provider, list_columns, list_foreign_keys

        payload: Dict[str, Any] = {
            "ok": True,
            "table": name,
            "schema": schema,
            "message": message,
            "source": "sonasid:schema+live",
        }
        if is_azure_provider():
            try:
                payload["columns"] = list_columns(table=name, schema=schema)
                payload["relations"] = list_foreign_keys(table=name, schema=schema)
            except Exception as e:
                payload["live_error"] = str(e) or repr(e)
        return payload
    except Exception as e:
        return {"ok": False, "error": str(e) or repr(e)}


@app.get("/")
def root() -> Dict[str, Any]:
    return {
        "name": "Sonasid KPI API",
        "status": "ok",
        "endpoints": [
            "/healthz",
            "/db/status",
            "/db/tables",
            "/db/columns",
            "/db/relations",
            "/db/schema",
            "/chat",
            "/chat/retry",
        ],
    }


def _local_users() -> Dict[str, Any]:
    """
    Local auth users config (for users without Microsoft accounts).
    Recommended to set via env `LOCAL_AUTH_USERS_JSON`.
    Shape:
      { "users": { "user1": { "display_name": "...", "email": "...", "password": {pbkdf2 spec} } } }
    """
    raw = (os.getenv("LOCAL_AUTH_USERS_JSON", "") or "").strip()
    if not raw:
        return {"users": {}}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {"users": {}}
    except Exception:
        return {"users": {}}


@app.get("/auth/me")
def auth_me(request: Request) -> Dict[str, Any]:
    u = (request.session or {}).get("user") if hasattr(request, "session") else None
    if not isinstance(u, dict) or not u.get("sub"):
        return {"authenticated": False}
    return {"authenticated": True, "user": u}


@app.get("/auth/account")
def auth_account(request: Request) -> Dict[str, Any]:
    """
    Personal account info for the currently authenticated user.
    Includes RBAC scope (allowed years) for transparency in the UI.
    """
    u = (request.session or {}).get("user") if hasattr(request, "session") else None
    if not isinstance(u, dict) or not u.get("sub"):
        return {"authenticated": False}
    actor_name = str(u.get("display_name") or u.get("email") or "").strip()
    actor_email = str(u.get("email") or "").strip()
    actor_username = str(u.get("username") or "").strip()
    years = allowed_years_for_actor(actor_name, actor_email=actor_email, actor_username=actor_username)
    return {"authenticated": True, "user": u, "allowed_years": list(years or [])}


@app.get("/auth/profile")
def auth_profile(request: Request) -> Dict[str, Any]:
    u = (request.session or {}).get("user") if hasattr(request, "session") else None
    if not isinstance(u, dict) or not u.get("sub"):
        return {"authenticated": False}
    prof = get_profile(str(u.get("sub") or ""))
    return {"ok": True, "profile": prof.to_dict()}


@app.post("/auth/profile")
def auth_profile_update(payload: UpdateProfileRequest, request: Request) -> Dict[str, Any]:
    u = (request.session or {}).get("user") if hasattr(request, "session") else None
    if not isinstance(u, dict) or not u.get("sub"):
        return {"ok": False, "error": "UNAUTHENTICATED", "message": "Non connecté."}
    ok, prof = update_profile(
        str(u.get("sub") or ""), phone=payload.phone, personal_email=payload.personal_email
    )
    if not ok:
        return {"ok": False, "error": "SAVE_FAILED", "message": "Impossible d’enregistrer le profil."}
    return {"ok": True, "profile": prof.to_dict()}


@app.post("/auth/change_password")
def auth_change_password(payload: ChangePasswordRequest, request: Request) -> Dict[str, Any]:
    """
    Change password/code:
    - local_excel: updates the Excel `code` if the file is writable
    - local (PBKDF2) and microsoft: not supported here (keep it simple)
    """
    u = (request.session or {}).get("user") if hasattr(request, "session") else None
    if not isinstance(u, dict) or not u.get("sub"):
        return {"ok": False, "error": "UNAUTHENTICATED", "message": "Non connecté."}

    provider = str(u.get("auth_provider") or "")
    if provider != "local_excel":
        return {
            "ok": False,
            "error": "NOT_SUPPORTED",
            "message": "Changement de mot de passe non supporté pour ce mode de connexion.",
        }

    username = str(u.get("username") or "").strip()
    if not username:
        return {"ok": False, "error": "BAD_USER", "message": "Utilisateur invalide."}

    # Determine Excel path (same as login)
    xlsx_path = (os.getenv("RBAC_USERS_XLSX_PATH", "") or "").strip()
    if not xlsx_path:
        try:
            default_xlsx = Path(__file__).resolve().parents[2] / "backend" / "security" / "users.xlsx"
            if default_xlsx.exists():
                xlsx_path = str(default_xlsx)
        except Exception:
            xlsx_path = ""
    if not xlsx_path:
        return {"ok": False, "error": "NO_DIRECTORY", "message": "Annuaire Excel non configuré."}

    # Verify current code
    x = load_users_from_excel(xlsx_path)
    row = (x.local_users or {}).get(username.strip().lower())
    if not isinstance(row, dict) or str(row.get("code") or "").strip() != str(payload.current_password or "").strip():
        return {"ok": False, "error": "BAD_CREDENTIALS", "message": "Mot de passe actuel incorrect."}

    updated = update_local_code_in_excel(xlsx_path, username=username, new_code=payload.new_password)
    if not updated:
        return {
            "ok": False,
            "error": "UPDATE_FAILED",
            "message": "Impossible de modifier le code. Modifie l’Excel manuellement ou contacte l’admin.",
        }
    return {"ok": True}


@app.post("/auth/logout")
def auth_logout(request: Request) -> Dict[str, Any]:
    try:
        request.session.clear()
    except Exception:
        pass
    return {"ok": True}


@app.post("/auth/local/login")
def auth_local_login(payload: LocalLoginRequest, request: Request) -> Dict[str, Any]:
    # Mode B (recommended): username + code stored in Excel (RBAC_USERS_XLSX_PATH)
    # If RBAC_USERS_XLSX_PATH is set, we intentionally do NOT fall back to legacy users,
    # to avoid logging in with old usernames when Excel is the source of truth.
    xlsx_path = (os.getenv("RBAC_USERS_XLSX_PATH", "") or "").strip()
    # Safe default: if env isn't set, use the bundled template path.
    if not xlsx_path:
        try:
            default_xlsx = Path(__file__).resolve().parents[2] / "backend" / "security" / "users.xlsx"
            if default_xlsx.exists():
                xlsx_path = str(default_xlsx)
        except Exception:
            xlsx_path = ""

    if xlsx_path:
        x = load_users_from_excel(xlsx_path)
        row = (x.local_users or {}).get(str(payload.username or "").strip().lower())
        if not isinstance(row, dict):
            return {"ok": False, "error": "BAD_CREDENTIALS", "message": "Identifiants invalides."}
        code_ok = str(row.get("code") or "").strip() == str(payload.password or "").strip()
        if not code_ok:
            return {"ok": False, "error": "BAD_CREDENTIALS", "message": "Identifiants invalides."}
        user = {
            "sub": f"local:{payload.username}",
            "username": str(payload.username or ""),
            "email": str(row.get("email") or ""),
            "display_name": str(row.get("display_name") or payload.username),
            "auth_provider": "local_excel",
        }
        request.session["user"] = user
        return {"ok": True, "user": user}

    # Mode A (legacy): password hash in LOCAL_AUTH_USERS_JSON
    cfg = _local_users()
    users = cfg.get("users") if isinstance(cfg, dict) else {}
    u = users.get(payload.username) if isinstance(users, dict) else None
    if not isinstance(u, dict):
        return {"ok": False, "error": "BAD_CREDENTIALS", "message": "Identifiants invalides."}
    pw = u.get("password")
    if not isinstance(pw, dict) or not verify_password(payload.password, pw):
        return {"ok": False, "error": "BAD_CREDENTIALS", "message": "Identifiants invalides."}
    user = {
        "sub": f"local:{payload.username}",
        "username": str(payload.username or ""),
        "email": str(u.get("email") or ""),
        "display_name": str(u.get("display_name") or payload.username),
        "auth_provider": "local",
    }
    request.session["user"] = user
    return {"ok": True, "user": user}


@app.get("/auth/microsoft/login")
def auth_microsoft_login(request: Request, redirect: int = 0, return_to: str = "") -> Dict[str, Any]:
    if not microsoft_enabled():
        missing = microsoft_missing_env_vars()
        detail = "Variables manquantes: " + ", ".join(missing) if missing else "Configuration incomplète."
        return {
            "ok": False,
            "error": "SSO_DISABLED",
            "message": f"Microsoft SSO non configuré côté serveur.\n{detail}",
        }
    # OAuth state is signed (HMAC) so we do not rely on the session cookie surviving
    # the Microsoft redirect (Safari / cross-site cookie rules).
    nonce = os.urandom(16).hex()
    configured_ru = (os.getenv("AZURE_AD_REDIRECT_URI", "") or "").strip()
    if not configured_ru:
        try:
            configured_ru = str(request.url_for("auth_microsoft_callback"))
        except Exception:
            configured_ru = ""
    rt = str(return_to or "")[:500]
    st_signed = mint_microsoft_oauth_state(
        secret=_SESSION_SECRET,
        nonce=nonce,
        redirect_uri=configured_ru,
        return_to=rt,
    )
    if return_to:
        request.session["ms_return_to"] = rt
    authorize_url = microsoft_authorize_url(
        state=st_signed,
        nonce=nonce,
        redirect_uri=configured_ru or None,
    )
    if redirect:
        return RedirectResponse(url=authorize_url, status_code=302)
    return {"ok": True, "authorize_url": authorize_url}


@app.get("/auth/microsoft/callback")
def auth_microsoft_callback(code: str = "", state: str = "", request: Request = None) -> Dict[str, Any]:
    if request is None:
        return {"ok": False, "error": "BAD_REQUEST"}
    if not microsoft_enabled():
        missing = microsoft_missing_env_vars()
        detail = "Variables manquantes: " + ", ".join(missing) if missing else "Configuration incomplète."
        return {
            "ok": False,
            "error": "SSO_DISABLED",
            "message": f"Microsoft SSO non configuré côté serveur.\n{detail}",
        }
    st_data = parse_microsoft_oauth_state(state, secret=_SESSION_SECRET)
    ru: Optional[str] = None
    ret = ""
    nonce_for_token: Optional[str] = None

    if st_data:
        ru = str(st_data.get("ru") or "").strip() or None
        ret = str(st_data.get("rt") or "").strip()
        nonce_for_token = str(st_data.get("n") or "")
        if not code or not nonce_for_token:
            return {"ok": False, "error": "BAD_STATE", "message": "State invalide."}
    else:
        # Legacy: state stored in session (requires session cookie on callback).
        expected = str((request.session or {}).get("ms_state") or "")
        if not code or not state or state != expected:
            return {"ok": False, "error": "BAD_STATE", "message": "State invalide."}
        ru = str((request.session or {}).get("ms_redirect_uri") or "").strip() or None
        try:
            ret = str((request.session or {}).get("ms_return_to") or "")
        except Exception:
            ret = ""
        nonce_for_token = str((request.session or {}).get("ms_nonce") or "") or None

    try:
        user = microsoft_exchange_code_for_user(
            code,
            redirect_uri=ru,
            expected_nonce=nonce_for_token,
        )
    except Exception as e:
        return {"ok": False, "error": "SSO_FAILED", "message": str(e) or "SSO failed"}
    u = {"sub": user.sub, "email": user.email, "display_name": user.display_name, "auth_provider": "microsoft"}
    request.session["user"] = u
    # Redirect after SSO: signed state carries `rt`; legacy flow used session only.
    if not ret:
        try:
            ret = str((request.session or {}).get("ms_return_to") or "")
        except Exception:
            ret = ""
    if ret:
        try:
            request.session.pop("ms_return_to", None)
        except Exception:
            pass
        return RedirectResponse(url=ret, status_code=302)
    return {"ok": True, "user": u}


@app.post("/chat")
def chat(payload: ChatRequest, request: Request) -> Dict[str, Any]:
    prefix = _user_scope_prefix(request)
    sid = _scope_session_id(request, payload.session_id or "default")
    q_raw = (payload.question or "").strip()
    try:
        prior: List[Dict[str, Any]] = get_conversation_history(session_id=sid, limit=80)
    except Exception:
        prior = []

    # Schéma / structure table : réponse immédiate (dictionnaire + Azure), sans KPI ni LLM.
    try:
        from backend.llm.llm_sql import normalize_user_question
        from backend.llm.sonasid_schema import is_schema_metadata_question, schema_metadata_reply

        q_schema = normalize_user_question(q_raw)
        if is_schema_metadata_question(q_schema):
            try:
                add_memory(session_id=sid, role="user", content=q_raw)
            except Exception:
                pass
            res = schema_metadata_reply(q_schema)
            try:
                add_memory(session_id=sid, role="assistant", content=_assistant_memory_content(res))
            except Exception:
                pass
            return res
        from backend.llm.sonasid_schema import company_overview_reply, is_sonasid_company_question

        if is_sonasid_company_question(q_schema):
            try:
                add_memory(session_id=sid, role="user", content=q_raw)
            except Exception:
                pass
            res = company_overview_reply(q_schema)
            try:
                add_memory(session_id=sid, role="assistant", content=_assistant_memory_content(res))
            except Exception:
                pass
            return res
    except Exception:
        pass

    q_eff = merge_need_period_followup_from_history(q_raw, prior)
    q_eff = merge_kpi_followup_from_history(q_eff, prior)
    q_eff = merge_table_format_followup_from_history(q_eff, prior)
    notice_ui = None

    # If the UI provided a date range, apply it server-side ONLY for KPI-like questions.
    # This avoids the frontend "blocking" anything: the user text stays intact, and the backend
    # is the single source of truth about whether a question is a KPI question.
    def _already_dated(text: str) -> bool:
        s = (text or "").lower()
        return bool(
            re.search(r"\b20\d{2}-\d{2}-\d{2}\b", s)
            or re.search(r"\b20\d{2}-\d{2}\b", s)
            or re.search(r"\b20\d{2}\b", s)
            or re.search(r"\b(?:du|de)\s+\d{4}-\d{2}-\d{2}\s+(?:au|a|à)\s+\d{4}-\d{2}-\d{2}\b", s)
        )

    try:
        preset = (payload.period_preset or "").strip().lower()
        p = payload.period if isinstance(payload.period, dict) else None
        start = (p or {}).get("start") if isinstance(p, dict) else None
        end = (p or {}).get("end") if isinstance(p, dict) else None
        if preset and preset != "none" and start and end and looks_like_kpi_question(q_eff):
            if not _already_dated(q_eff) and not re.search(
                r"\b(?:du|de)\s+\d{4}-\d{2}-\d{2}\s+(?:au|a|à)\s+\d{4}-\d{2}-\d{2}\b", q_eff, re.I
            ):
                q_eff = f"{q_eff} du {start} au {end}"
                notice_ui = f"Période appliquée: du {start} au {end}."
    except Exception:
        pass

    # Prefer authenticated user from session over the client-provided actor_name.
    sess_user = (request.session or {}).get("user") if hasattr(request, "session") else None
    actor = ""
    actor_email = ""
    actor_username = ""
    if isinstance(sess_user, dict):
        actor = str(sess_user.get("display_name") or sess_user.get("email") or "").strip()
        actor_email = str(sess_user.get("email") or "").strip()
        actor_username = str(sess_user.get("username") or "").strip()
    actor = actor or (payload.actor_name or "").strip()

    allowed_years_tuple: Optional[Tuple[int, ...]] = None
    try:
        allowed_years_tuple = allowed_years_for_actor(
            actor, actor_email=actor_email, actor_username=actor_username
        )
    except Exception:
        allowed_years_tuple = None

    try:
        from backend.llm.sonasid_schema import is_schema_metadata_question
        from backend.llm.sonasid_sql import augment_sonasid_question_period, expand_sonasid_open_question

        if not is_schema_metadata_question(q_eff):
            q_eff, expand_notice = expand_sonasid_open_question(q_eff)
            if expand_notice:
                notice_ui = expand_notice
            q_eff, sonasid_auto = augment_sonasid_question_period(
                q_eff, allowed_years=allowed_years_tuple
            )
            if sonasid_auto:
                notice_ui = sonasid_auto
    except Exception:
        pass

    notice = notice_ui
    # Apply RBAC only for KPI-like questions. General conversation must stay natural.
    if looks_like_kpi_question(q_eff):
        before = q_eff
        decision = enforce_access_on_question(
            question=q_eff,
            actor_name=actor,
            actor_email=actor_email,
            actor_username=actor_username,
        )
        if not decision.allowed:
            res = access_denied_response(actor_name=actor, decision=decision)
            # Persist assistant response (so user sees the denial in history)
            try:
                add_memory(session_id=sid, role="assistant", content=_assistant_memory_content(res))
            except Exception:
                pass
            return res
        q_eff = decision.effective_question
        # Surface which period/year was applied so the user always understands "the value is for what?"
        try:
            if decision.effective_question != before:
                span = kpi_period_span_from_question(decision.effective_question)
                if span:
                    a, b = span.split("..", 1)
                    notice = f"Période appliquée: du {a} au {b}."
                else:
                    notice = f"Période appliquée: {decision.effective_question}."
        except Exception:
            notice = None

    # Persist user turn to memory (RAG).
    # NOTE: Now that each account has its own history, we do not store the actor tag anymore.
    try:
        add_memory(session_id=sid, role="user", content=q_eff)
    except Exception:
        pass

    res = _run_chat_pipeline(
        q_eff,
        sid,
        payload.model_name or "",
        echo_question=q_raw,
        actor_name=actor,
    )
    if isinstance(res, dict) and notice and not res.get("notice"):
        res["notice"] = notice
    if _skip_assistant_persist(res):
        return res
    _persist_assistant_memory(session_id=sid, res=res)
    return res


@app.post("/chat/stt")
async def chat_stt(audio: UploadFile = File(...)) -> Dict[str, Any]:
    """Transcription audio (Whisper via OpenRouter) — fallback quand Web Speech API indisponible."""
    from backend.llm.stt import transcribe_audio_bytes

    raw = await audio.read()
    fmt = ""
    try:
        fn = str(audio.filename or "")
        if "." in fn:
            fmt = fn.rsplit(".", 1)[-1].lower()
    except Exception:
        fmt = ""
    if not fmt:
        ct = str(audio.content_type or "").lower()
        if "webm" in ct:
            fmt = "webm"
        elif "ogg" in ct:
            fmt = "ogg"
        elif "wav" in ct:
            fmt = "wav"
        elif "mp4" in ct or "m4a" in ct:
            fmt = "m4a"
        else:
            fmt = "webm"

    text, err = transcribe_audio_bytes(raw, fmt=fmt, language="fr")
    if err:
        return {"ok": False, "error": "STT_FAILED", "message": err}
    return {"ok": True, "text": text}


@app.post("/chat/retry")
def chat_retry(payload: ChatRetryRequest, request: Request) -> Dict[str, Any]:
    uq = (payload.user_question or "").strip()
    ac = (payload.assistant_content or "").strip()
    if not uq or not ac:
        return {
            "question": uq,
            "error": "BAD_REQUEST",
            "message": "user_question et assistant_content sont requis.",
        }
    prefix = _user_scope_prefix(request)
    sid = _scope_session_id(request, payload.session_id or "default")
    try:
        add_memory(session_id=sid, role="user", content=f"Réessai (auto-correction) : {uq}"[:4000])
    except Exception:
        pass

    # Persist a compact "feedback signal" so retrieval (RAG) can help avoid repeating the same mistake.
    try:
        fb_hint = (
            "[feedback] L'utilisateur a mis 👎 sur la réponse précédente. "
            "Au retry, évite de répéter la même erreur; vérifie période, unités et cohérence."
        )
        add_memory(session_id=sid, role="assistant", content=fb_hint)
    except Exception:
        pass

    retry_q = _auto_disambiguate_retry_question(user_question=uq, assistant_content=ac)
    # Enforce access control on retry too.
    sess_user = (request.session or {}).get("user") if hasattr(request, "session") else None
    actor = ""
    if isinstance(sess_user, dict):
        actor = str(sess_user.get("display_name") or sess_user.get("email") or "").strip()
    actor_email = ""
    if isinstance(sess_user, dict):
        actor_email = str(sess_user.get("email") or "").strip()
    actor_username = ""
    if isinstance(sess_user, dict):
        actor_username = str(sess_user.get("username") or "").strip()
    if looks_like_kpi_question(retry_q):
        decision = enforce_access_on_question(
            question=retry_q,
            actor_name=actor,
            actor_email=actor_email,
            actor_username=actor_username,
        )
        if not decision.allowed:
            return access_denied_response(actor_name=actor, decision=decision)
        retry_q = decision.effective_question
    res = _run_chat_pipeline(
        retry_q,
        sid,
        payload.model_name or "",
        echo_question=uq,
    )
    if _skip_assistant_persist(res):
        return res
    res = dict(res)
    note = "Réponse régénérée après un feedback négatif (auto-correction)."
    if res.get("notice"):
        res["notice"] = f"{note} {res['notice']}"
    else:
        res["notice"] = note
    _persist_assistant_memory(session_id=sid, res=res)
    return res


@app.get("/conversations")
def conversations(request: Request) -> Dict[str, Any]:
    # Each authenticated user sees only their own conversation list.
    # We scope session_ids by user sub, but return unscoped ids to the client.
    prefix = _user_scope_prefix(request)
    rows = list_conversations(limit=100, session_prefix=prefix)
    out = []
    for r in rows:
        rsid = _unscope_session_id(prefix, str(r.get("session_id") or ""))
        out.append({**r, "session_id": rsid})
    return {"conversations": out}


@app.get("/conversations/{session_id}/history")
def conversation_history(session_id: str, request: Request) -> Dict[str, Any]:
    sid = _scope_session_id(request, session_id)
    return {"session_id": session_id, "messages": get_conversation_history(session_id=sid, limit=500)}


@app.delete("/conversations/{session_id}")
def conversation_delete(session_id: str, request: Request) -> Dict[str, Any]:
    sid = _scope_session_id(request, session_id)
    delete_conversation(session_id=sid)
    return {"status": "ok", "session_id": session_id}


@app.post("/feedback")
def post_feedback(payload: FeedbackRequest, request: Request) -> Dict[str, Any]:
    if payload.rating not in (-1, 1):
        raise HTTPException(status_code=400, detail="rating must be 1 or -1")
    uq = (payload.user_question or "").strip()
    ac = (payload.assistant_content or "").strip()
    if not uq or not ac:
        raise HTTPException(status_code=400, detail="user_question and assistant_content are required")
    try:
        meta: Dict[str, Any] = {}
        if payload.model_name:
            meta["model_name"] = (payload.model_name or "").strip()
        row_id = add_chat_feedback(
            session_id=_scope_session_id(request, payload.session_id or "default"),
            rating=payload.rating,
            user_question=uq,
            assistant_content=ac,
            meta=meta,
        )
        return {"ok": True, "id": row_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

