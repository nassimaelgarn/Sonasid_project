"""
Correction déterministe des fautes courantes (Sonasid port / arrivages).
Appliquée avant routage KPI, brief et moteur SQL — sans LLM.
"""
from __future__ import annotations

import re
import unicodedata


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)
    )


# (pattern, replacement) — insensible à la casse
_SONASID_TYPO_PAIRS: tuple[tuple[str, str], ...] = (
    (r"\bkip\b", "kpi"),
    (r"\bkips\b", "kpi"),
    (r"\barivages?\b", "arrivages"),
    (r"\barivage\b", "arrivage"),
    (r"\bfourniseurs?\b", "fournisseur"),
    (r"\bfournisseures?\b", "fournisseur"),
    (r"\bfournissuers?\b", "fournisseur"),
    (r"\btonage\b", "tonnage"),
    (r"\btonages\b", "tonnages"),
    (r"\btonnages\b", "tonnage"),
    (r"\bnavir\b", "navire"),
    (r"\bnaviers\b", "navires"),
    (r"\bnaviress?\b", "navires"),
    (r"\bqualitee\b", "qualite"),
    (r"\bqualitée\b", "qualite"),
    (r"\bqualites\b", "qualite"),
    (r"\bresumer\b", "resume"),
    (r"\bresumé\b", "resume"),
    (r"\brésumer\b", "resume"),
    (r"\brésume\b", "resume"),
    (r"\brecapitulatif\b", "recap"),
    (r"\brécapitulatif\b", "recap"),
    (r"\banalise\b", "analyse"),
    (r"\banalysse\b", "analyse"),
    (r"\banalyser\b", "analyse"),
    (r"\banalyzes?\b", "analyse"),
    (r"\bmarchandize\b", "marchandise"),
    (r"\bmarchandises\b", "marchandise"),
    (r"\bdechagement\b", "dechargement"),
    (r"\bdéchagement\b", "dechargement"),
    (r"\bdecharg\b", "dechargement"),
    (r"\btranfert\b", "transfert"),
    (r"\btransfere\b", "transfere"),
    (r"\btransfér\b", "transfert"),
    (r"\bindicatuers?\b", "indicateurs"),
    (r"\bindicateus\b", "indicateurs"),
    (r"\bindicatifs\b", "indicateurs"),
    (r"\bpricipaux\b", "principaux"),
    (r"\bprincipau\b", "principaux"),
    (r"\bclassements?\b", "classement"),
    (r"\bimportee\b", "importe"),
    (r"\bimportees\b", "importe"),
    (r"\bimportées\b", "importe"),
    (r"\bimportés\b", "importe"),
    (r"\baccostages?\b", "accostage"),
    (r"\bdemurage\b", "demurrage"),
    (r"\bdémurage\b", "demurrage"),
    (r"\bsurestaries\b", "surestarie"),
    (r"\bcommandes\b", "commande"),
    (r"\bactifs\b", "actif"),
    (r"\bactives\b", "actif"),
    (r"\btout les\b", "tous les"),
    (r"\btoute les\b", "toutes les"),
    (r"\bcombient\b", "combien"),
    (r"\bcombiens\b", "combien"),
    (r"\bquelle est\b", "quels"),
    (r"\bquel est\b", "quels"),
    (r"\bdonne moi\b", "donne-moi"),
    (r"\bdonnes?\b", "donne"),
    (r"\bveux avoir\b", "veux un"),
    (r"\bje veux un\b", "je veux"),
)


def apply_sonasid_typos(text: str) -> str:
    q = unicodedata.normalize("NFKC", (text or "")).strip()
    q = re.sub(r"\s+", " ", q)
    for pat, rep in _SONASID_TYPO_PAIRS:
        q = re.sub(pat, rep, q, flags=re.IGNORECASE)
    return q.strip()


def fuzzy_contains(haystack: str, word: str, *, max_dist: int = 1) -> bool:
    """
    True si `word` apparaît tel quel ou avec une faute légère (1 caractère).
    Utilisé pour mots-clés courts (kpi, port…).
    """
    w = (word or "").lower()
    h = _strip_accents((haystack or "").lower())
    if w in h:
        return True
    if len(w) < 4:
        return False
    # sous-chaîne proche : tolère 1 substitution sur mots >= 5 lettres
    for token in re.findall(r"[a-z0-9]+", h):
        if token == w:
            return True
        if abs(len(token) - len(w)) > max_dist:
            continue
        diff = sum(1 for a, b in zip(token, w) if a != b) + abs(len(token) - len(w))
        if diff <= max_dist:
            return True
    return False
