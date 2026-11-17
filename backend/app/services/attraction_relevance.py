"""Interest matching for the available POI catalog, without demand/popularity data."""
from __future__ import annotations

from app.schemas import AttractionInput, Preferences


_ALIASES = {
    "history": "heritage", "heritage and history": "heritage",
    "mountains and trekking": "mountains", "nature and wildlife": "nature",
    "spiritual and cultural travel": "spiritual", "road trips": "road trips",
    "food and culinary experiences": "food", "relaxation and wellness": "wellness",
}


def _affinity(interest: str, category: str, tags: dict[str, str]) -> float:
    interest = _ALIASES.get(interest.strip().lower(), interest.strip().lower())
    category = category.strip().lower()
    tags = {str(key).lower(): str(value).lower() for key, value in tags.items()}
    if interest == "heritage":
        if tags.get("historic") or tags.get("heritage") or tags.get("wikidata") or tags.get("wikipedia"):
            return 1.0
        return {"historical": 1.0, "museum": 0.9, "cultural": 0.8}.get(category, 0.0)
    if interest == "spiritual":
        return 1.0 if category == "religious" or tags.get("amenity") == "place_of_worship" else 0.0
    if interest in {"mountains", "nature"}:
        if tags.get("natural") in {"peak", "cliff", "water", "lake", "wood", "beach"}:
            return 1.0 if interest == "mountains" and tags.get("natural") in {"peak", "cliff"} else 0.9
        return {"viewpoint": 0.9, "park": 0.75}.get(category, 0.0)
    if interest == "adventure":
        if any(tags.get(key) for key in ("sport", "climbing", "sac_scale", "via_ferrata_scale", "route")):
            return 1.0
        return {"viewpoint": 0.6, "entertainment": 0.55, "park": 0.4}.get(category, 0.0)
    if interest == "road trips":
        # Road trips are a travel style, not a destination POI category.
        return 0.0
    if interest == "photography":
        return {"viewpoint": 0.9, "historical": 0.55, "museum": 0.45, "cultural": 0.55}.get(category, 0.0)
    if interest == "food":
        return 1.0 if tags.get("amenity") in {"restaurant", "cafe", "food_court"} else 0.0
    if interest == "wellness":
        return 1.0 if tags.get("amenity") in {"spa", "massage"} else 0.0
    if interest == "shopping":
        return 1.0 if tags.get("shop") or tags.get("amenity") == "marketplace" else 0.0
    if interest == "nightlife":
        return 0.8 if tags.get("amenity") in {"bar", "pub", "nightclub"} else 0.0
    if interest == "beaches":
        return 1.0 if tags.get("natural") == "beach" else 0.0
    return 0.0


def interest_match(attraction: AttractionInput, interests: dict[str, float]) -> float:
    """Weighted match in [0,1], averaged across selected interests."""
    active = [(key, max(0.0, float(weight))) for key, weight in interests.items() if weight > 0]
    if not active:
        return 0.5
    category = attraction.catalog_category or attraction.category
    tags = attraction.raw_tags or {}
    denominator = sum(weight for _, weight in active)
    return sum(weight * _affinity(key, category, tags) for key, weight in active) / denominator


def category_diversity_factor(attraction: AttractionInput, category_counts: dict[str, int]) -> float:
    category = (attraction.catalog_category or attraction.category).lower()
    # Soft diminishing returns allow repeats where the catalog has no alternatives.
    return 1.0 / (1.0 + 0.7 * category_counts.get(category, 0))


def balanced_interest_utility(attractions: list[AttractionInput], preferences: Preferences) -> float:
    """Set utility shared by set-selection optimizers with diminishing category returns."""
    counts: dict[str, int] = {}
    total = 0.0
    ordered = sorted(attractions, key=lambda item: (-(item.priority_score if item.priority_score is not None else item.preference_score), item.id))
    for attraction in ordered:
        category = (attraction.catalog_category or attraction.category).lower()
        match = interest_match(attraction, preferences.interests)
        priority = attraction.priority_score if attraction.priority_score is not None else attraction.preference_score
        total += attraction.preference_score * (0.7 + 0.6 * match) * category_diversity_factor(attraction, counts) * (0.75 + 0.5 * priority)
        counts[category] = counts.get(category, 0) + 1
    return total


def unsupported_interests(attractions: list[AttractionInput], interests: dict[str, float]) -> list[str]:
    """List selected interest dimensions with no tagged/category match in this catalog."""
    candidates = attractions or []
    unavailable = []
    for key, weight in interests.items():
        if weight <= 0:
            continue
        if not candidates or max(_affinity(key, item.catalog_category or item.category, item.raw_tags or {}) for item in candidates) <= 0:
            unavailable.append(key.replace("_", " ").title())
    return unavailable


def inferred_walking_effort(attraction: AttractionInput) -> float:
    """A planning heuristic from category and explicit activity tags, not a measured effort."""
    tags = {str(key).lower(): str(value).lower() for key, value in (attraction.raw_tags or {}).items()}
    if any(tags.get(key) for key in ("sac_scale", "via_ferrata_scale", "climbing")):
        return 0.9
    if tags.get("natural") in {"peak", "cliff"} or tags.get("sport") in {"hiking", "climbing"}:
        return 0.85
    category = (attraction.catalog_category or attraction.category).lower()
    return {"park": 0.55, "viewpoint": 0.65, "religious": 0.35, "museum": 0.25,
            "historical": 0.4, "cultural": 0.35, "entertainment": 0.55}.get(category, 0.5)
