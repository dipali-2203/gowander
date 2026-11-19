import type { AttractionInput } from "@/lib/api";

/** Soft preference only: all feasibility checks and optimizer constraints remain authoritative. */
export function boostBookmarkedAttractions(
  attractions: AttractionInput[],
  bookmarkedIds: ReadonlySet<string>,
  amount = 0.12,
): AttractionInput[] {
  if (bookmarkedIds.size === 0 || amount <= 0) return attractions;
  return attractions.map((attraction) => {
    if (!bookmarkedIds.has(attraction.id)) return attraction;
    const priority = attraction.priority_score ?? attraction.preference_score;
    return {
      ...attraction,
      preference_score: Math.min(1, attraction.preference_score + amount),
      priority_score: Math.min(1, priority + amount),
    };
  });
}
