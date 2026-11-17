"""Itinerary-only duplicate filtering for provider-backed attraction candidates.

Catalog records remain untouched. This layer only chooses one representative for
likely duplicate physical places while building an itinerary.
"""
from __future__ import annotations

import os
import re
import unicodedata
from difflib import SequenceMatcher
from math import asin, cos, radians, sin, sqrt

from app.schemas import AttractionInput


def _configured_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, value))


EXACT_NAME_DISTANCE_METERS = _configured_float(
    "ITINERARY_DUPLICATE_EXACT_DISTANCE_METERS", 125.0, 1.0, 1000.0
)
SIMILAR_NAME_DISTANCE_METERS = _configured_float(
    "ITINERARY_DUPLICATE_SIMILAR_DISTANCE_METERS", 75.0, 1.0, 500.0
)
SIMILAR_NAME_THRESHOLD = _configured_float(
    "ITINERARY_DUPLICATE_NAME_SIMILARITY", 0.86, 0.5, 1.0
)

_CATEGORY_FAMILIES = (
    {"historical", "history", "museum", "cultural", "heritage"},
    {"viewpoint", "nature", "park", "sightseeing"},
    {"religious", "spiritual"},
)
_GENERIC_VIEW_WORDS = re.compile(r"\b(viewpoint|view point|view|lookout|overlook)\b")


def _normalized_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", " ", decomposed.lower()).strip()
    return _GENERIC_VIEW_WORDS.sub("viewpoint", value)


def _distance_meters(left: AttractionInput, right: AttractionInput) -> float:
    lat1, lon1, lat2, lon2 = map(
        radians, (left.latitude, left.longitude, right.latitude, right.longitude)
    )
    value = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(min(1.0, max(0.0, value))))


def _same_provider_identity(left: AttractionInput, right: AttractionInput) -> bool:
    same_external_id = bool(
        left.external_provider_id
        and right.external_provider_id
        and left.external_provider_id.strip().lower() == right.external_provider_id.strip().lower()
    )
    if same_external_id and left.data_source == right.data_source == "osm":
        return True
    return bool(
        left.provider_name
        and right.provider_name
        and left.provider_name.lower() == right.provider_name.lower()
        and same_external_id
    )


def _compatible_categories(left: AttractionInput, right: AttractionInput) -> bool:
    left_category = (left.catalog_category or left.category).lower()
    right_category = (right.catalog_category or right.category).lower()
    if left_category == right_category:
        return True
    return any(left_category in family and right_category in family for family in _CATEGORY_FAMILIES)


def _likely_same_place(left: AttractionInput, right: AttractionInput) -> bool:
    if left.id == right.id:
        return True
    if _same_provider_identity(left, right):
        return True
    if not _compatible_categories(left, right):
        return False
    # Name-and-distance heuristics are intentionally limited to records sharing
    # a provider, or two OSM records. We do not merge unrelated user data.
    same_osm_catalog = (
        left.data_source == right.data_source == "osm"
        or bool(left.provider_name and left.provider_name == right.provider_name)
    )
    if not same_osm_catalog:
        return False
    distance = _distance_meters(left, right)
    left_name, right_name = _normalized_name(left.name), _normalized_name(right.name)
    if left_name == right_name:
        return distance <= EXACT_NAME_DISTANCE_METERS
    similarity = SequenceMatcher(None, left_name, right_name).ratio()
    return distance <= SIMILAR_NAME_DISTANCE_METERS and similarity >= SIMILAR_NAME_THRESHOLD


def _quality(attraction: AttractionInput) -> tuple[int, int, int, float, int]:
    tags = attraction.raw_tags or {}
    return (
        int(attraction.verification_status == "manually_verified"),
        len(tags),
        len(_normalized_name(attraction.name).split()),
        attraction.priority_score if attraction.priority_score is not None else attraction.preference_score,
        len(attraction.external_provider_id or ""),
    )


def deduplicate_itinerary_candidates(
    attractions: list[AttractionInput],
) -> tuple[list[AttractionInput], list[str]]:
    """Return preferred representatives and a concise disclosure, without writes."""
    ranked = sorted(attractions, key=lambda item: (_quality(item), item.id), reverse=True)
    kept: list[AttractionInput] = []
    dropped = 0
    for attraction in ranked:
        if any(_likely_same_place(attraction, existing) for existing in kept):
            dropped += 1
            continue
        kept.append(attraction)
    kept.sort(key=lambda item: item.id)
    warnings = (
        [f"{dropped} likely duplicate attraction representation(s) were omitted from this itinerary; catalog records were preserved."]
        if dropped
        else []
    )
    return kept, warnings


def remap_matrix_for_candidates(matrix, original: list[AttractionInput], kept: list[AttractionInput]):
    """Select rows/columns for the retained attractions in a start-plus-POIs matrix."""
    if len(original) == len(kept) and all(a.id == b.id for a, b in zip(original, kept)):
        return matrix
    index_by_id = {item.id: index + 1 for index, item in enumerate(original)}
    indices = [0, *(index_by_id[item.id] for item in kept)]
    return [[matrix[row][column] for column in indices] for row in indices]
