"""Transparent itinerary relevance heuristic; it is not a popularity score."""
from __future__ import annotations

import re
import os


_CATEGORY_BASE = {
    "historical": 0.86, "museum": 0.88, "cultural": 0.76,
    "viewpoint": 0.70, "entertainment": 0.66, "religious": 0.50,
    "park": 0.58, "other": 0.44,
}

# Small manually curated set of locally iconic Udaipur landmarks supplied for
# validation. These are relevance anchors, not ratings or popularity claims.
_UDAIPUR_LANDMARKS = {
    "city palace", "lake pichola", "sajjan garh monsoon palace", "monsoon palace",
    "bagore ki haveli", "jagdish temple", "jagdish mandir", "fateh sagar lake",
    "saheliyon ki bari",
}


def attraction_priority(category: str | None, name: str, tags: dict | None = None,
                        verification_status: str | None = None) -> tuple[float, list[str]]:
    """Return 0..1 planning relevance with reasons based only on available tags."""
    tags = tags or {}
    normalized_tags = {str(k).lower(): str(v).lower() for k, v in tags.items()}
    category_key = (category or "other").lower()
    try:
        configured_base = float(os.getenv(f"GOWANDER_PRIORITY_{category_key.upper()}"))
    except (TypeError, ValueError):
        configured_base = _CATEGORY_BASE.get(category_key, 0.5)
    score = min(1.0, max(0.0, configured_base))
    reasons = [f"{category_key.title()} category"]
    if any(key in normalized_tags for key in ("heritage", "wikipedia", "wikidata")):
        score += 0.12
        reasons.append("heritage or linked reference tag")
    if normalized_tags.get("historic"):
        score += 0.14
        reasons.append("mapped historic feature tag")
    if normalized_tags.get("tourism") in {"attraction", "museum", "gallery", "viewpoint"}:
        score += 0.08
        reasons.append("tourism feature tag")
    if verification_status == "manually_verified":
        score += 0.08
        reasons.append("manually verified record")
    generic = re.search(r"\b(block|sector|colony|neighbourhood|neighborhood|cabs?|taxis?|travel agency|hostel|school|office|service center)\b", name.lower())
    if generic or re.fullmatch(r"(?:the )?(?:park|temple|garden|lake|viewpoint)", name.strip().lower()):
        score -= 0.20
        reasons.append("generic place name")
    if category_key == "park" and any(key in normalized_tags for key in ("addr:housenumber", "operator")) and re.search(r"\b(cabs?|taxis?|hostel|service)\b", name.lower()):
        score -= 0.20
        reasons.append("name or address tags conflict with attraction category")
    if re.search(r"\b(circle|gate|viewing platform|sunset point|pol)\b|pol$", name.lower()):
        score -= 0.18
        reasons.append("generic city feature name")
    normalized_name = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    if normalized_name in _UDAIPUR_LANDMARKS:
        score = max(score, 0.99)
        reasons.append("manually curated Udaipur landmark")
    return round(min(1.0, max(0.0, score)), 3), reasons
