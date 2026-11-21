"""Comparing the ways people and buildings are written across sources.

People: "GONZALEZ, MIGUEL T", "Miguel G.", "F. Berisha", "Bennett, David" all need to be compared
with an HR record (first name, last name). A name "matches" when the first and last names agree,
where an initial ("G.") is allowed to stand for a name but at least one part must be written out.

Buildings: "MERIDIAN PLZ", "Meridian 1", "Corlett Bldg", "BRAMWELL ANX" are compared with the
names in the client agreements after expanding common address abbreviations.
"""

import re
import unicodedata

from rapidfuzz import fuzz


def fold(text: str | None) -> str:
    """Uppercase, accents removed, punctuation turned into spaces: 'Fëmija, Ana-Maria' -> 'FEMIJA ANA MARIA'."""
    if not text:
        return ""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", plain.upper()).strip()


# --- people ---------------------------------------------------------------------------------------


def name_tokens(text: str | None) -> list[str]:
    """'LAST, FIRST M' is reordered to 'FIRST M LAST' before splitting."""
    if not text:
        return []
    if "," in text:
        last, _, first = text.partition(",")
        text = f"{first} {last}"
    return fold(text).split()


def _part_matches(tokens: list[str], part: str) -> str | None:
    """'full' if a token spells the name part out, 'initial' if only its initial is there."""
    words = fold(part).split()
    if not words:
        return None
    if all(w in tokens for w in words):
        return "full"
    if any(len(t) == 1 and t == words[0][0] for t in tokens):
        return "initial"
    return None


def person_match_score(text: str | None, first_name: str | None, last_name: str | None) -> int:
    """2 = first and last name both written out; 1 = one written out, the other as an initial;
    0 = no match (including a first name alone, which is not enough to identify anyone)."""
    tokens = name_tokens(text)
    first = _part_matches(tokens, first_name or "")
    last = _part_matches(tokens, last_name or "")
    if first is None or last is None:
        return 0
    if first == "full" and last == "full":
        return 2
    if "full" in (first, last):
        return 1
    return 0


# --- buildings ------------------------------------------------------------------------------------

ABBREVIATIONS = {
    "TWR": "TOWER",
    "PLZ": "PLAZA",
    "HSE": "HOUSE",
    "ANX": "ANNEX",
    "BLDG": "BUILDING",
    "BLD": "BUILDING",
    "CTR": "CENTER",
    "ST": "STREET",
    "AVE": "AVENUE",
    "1": "ONE",
    "2": "TWO",
    "3": "THREE",
    "4": "FOUR",
    "5": "FIVE",
}
# Words that describe a place but do not tell two buildings apart.
GENERIC_WORDS = {"BUILDING", "THE"}


def building_key(name: str | None) -> str:
    """'Meridian One Bldg (OLD - DO NOT USE)' -> 'MERIDIAN ONE'. Parenthesised notes are dropped."""
    without_notes = re.sub(r"\([^)]*\)", " ", name or "")
    words = [ABBREVIATIONS.get(w, w) for w in fold(without_notes).split()]
    return " ".join(w for w in words if w not in GENERIC_WORDS)


def best_building_match(
    name: str | None, candidates: list[str], min_score: float = 85, min_margin: float = 10
) -> tuple[str | None, float]:
    """Best candidate and its score (0-100), or (None, score) when no candidate is clearly best."""
    key = building_key(name)
    if not key or not candidates:
        return None, 0.0
    scored = sorted(((fuzz.token_set_ratio(key, building_key(c)), c) for c in candidates), reverse=True)
    best_score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= min_score and best_score - runner_up >= min_margin:
        return best, best_score
    return None, best_score
