const CATEGORY_DEFINITIONS = [
  { key: "intercity_outbound", label: "Intercity · outbound", color: "#6366f1" },
  { key: "intercity_return", label: "Intercity · return", color: "#8b5cf6" },
  { key: "local_transport", label: "Local transportation", color: "#0ea5e9" },
  { key: "accommodation", label: "Accommodation", color: "#f97316" },
  { key: "food", label: "Food", color: "#22c55e" },
  { key: "attraction_fees", label: "Attraction fees", color: "#a855f7" },
  { key: "miscellaneous", label: "Miscellaneous", color: "#eab308" },
];

const finite = (value) => typeof value === "number" && Number.isFinite(value);

export function buildBudgetDashboard(trips) {
  const estimateFor = (trip) => trip.latest_itinerary?.budget_estimate;
  const isCurrentComplete = (trip) =>
    trip.complete_budget_current === true &&
    trip.itinerary_stale !== true &&
    Boolean(estimateFor(trip)?.complete_budget);
  const currentCompleteTrips = trips.filter(isCurrentComplete);
  const calculableTrips = currentCompleteTrips.filter((trip) =>
    finite(estimateFor(trip).complete_budget.total_estimate),
  );
  const legacyTrips = trips.filter((trip) => {
    const estimate = estimateFor(trip);
    return (
      trip.itinerary_stale !== true &&
      !estimate?.complete_budget &&
      finite(estimate?.total_estimated)
    );
  });
  const staleTrips = trips.filter((trip) => trip.itinerary_stale === true && trip.latest_itinerary);
  const estimatedCost = calculableTrips.reduce(
    (sum, trip) => sum + estimateFor(trip).complete_budget.total_estimate,
    0,
  );
  const legacyDestinationCost = legacyTrips.reduce(
    (sum, trip) => sum + estimateFor(trip).total_estimated,
    0,
  );
  const allEstimatesAvailable = trips.length === 0 || calculableTrips.length === trips.length;
  const allocatedBudget = trips.reduce(
    (sum, trip) => sum + (finite(trip.budget) ? trip.budget : 0),
    0,
  );
  const travelDays = calculableTrips.reduce((sum, trip) => {
    const start = Date.parse(`${trip.start_date}T00:00:00Z`);
    const end = Date.parse(`${trip.end_date}T00:00:00Z`);
    return (
      sum +
      (Number.isFinite(start) && Number.isFinite(end) && end >= start
        ? Math.floor((end - start) / 86_400_000) + 1
        : 0)
    );
  }, 0);

  const categoryTrips = currentCompleteTrips.length > 0 ? currentCompleteTrips : legacyTrips;
  const categoryDataScope =
    currentCompleteTrips.length > 0
      ? "complete_trip"
      : legacyTrips.length
        ? "destination_only"
        : "unavailable";
  const categorySums = new Map(CATEGORY_DEFINITIONS.map(({ key }) => [key, 0]));
  const categoryCoverage = new Map(CATEGORY_DEFINITIONS.map(({ key }) => [key, 0]));
  const categoryPartial = new Map(CATEGORY_DEFINITIONS.map(({ key }) => [key, false]));
  const attractionFeeStats = {
    originalUnknownCount: 0,
    estimatedCount: 0,
    unresolvedCount: 0,
  };
  const legacyKeyMap = {
    transportation: "local_transport",
    meals: "food",
    attractions: "attraction_fees",
  };
  for (const trip of categoryTrips) {
    const estimate = estimateFor(trip);
    const categories =
      categoryDataScope === "complete_trip"
        ? estimate?.complete_budget?.categories
        : estimate?.categories;
    if (!Array.isArray(categories)) continue;
    const unknownOriginal = estimate?.unknown_attraction_fee_count ?? 0;
    attractionFeeStats.originalUnknownCount += finite(unknownOriginal) ? unknownOriginal : 0;
    const feeCategory = categories.find((item) =>
      categoryDataScope === "complete_trip"
        ? item.key === "attraction_fees"
        : item.key === "attractions",
    );
    attractionFeeStats.estimatedCount += finite(feeCategory?.estimated_count)
      ? feeCategory.estimated_count
      : 0;
    const unresolved =
      estimate?.unresolved_attraction_fee_count ??
      feeCategory?.unresolved_count ??
      (finite(feeCategory?.estimated_count) && finite(unknownOriginal)
        ? Math.max(0, unknownOriginal - feeCategory.estimated_count)
        : unknownOriginal);
    attractionFeeStats.unresolvedCount += finite(unresolved) ? unresolved : 0;
    for (const category of categories) {
      const key =
        categoryDataScope === "complete_trip"
          ? category.key
          : (legacyKeyMap[category.key] ?? category.key);
      if (!categorySums.has(key)) continue;
      if (finite(category.amount)) {
        categorySums.set(key, categorySums.get(key) + category.amount);
        categoryCoverage.set(key, categoryCoverage.get(key) + 1);
      }
      if (category.status === "partial" || category.status === "unavailable")
        categoryPartial.set(key, true);
      if (key === "attraction_fees") {
        const unresolvedCount =
          typeof category.unresolved_count === "number"
            ? category.unresolved_count
            : (estimate?.unresolved_attraction_fee_count ??
              (finite(category.estimated_count) && finite(estimate?.unknown_attraction_fee_count)
                ? Math.max(0, estimate.unknown_attraction_fee_count - category.estimated_count)
                : estimate?.unknown_attraction_fee_count) ??
              0);
        if (unresolvedCount > 0) categoryPartial.set(key, true);
      }
    }
  }
  const categories = CATEGORY_DEFINITIONS.map((definition) => ({
    ...definition,
    amount: categoryCoverage.get(definition.key) ? categorySums.get(definition.key) : null,
    coverage: categoryCoverage.get(definition.key),
    partial:
      categoryCoverage.get(definition.key) < categoryTrips.length ||
      categoryPartial.get(definition.key),
    percentage:
      categorySums.get(definition.key) > 0
        ? (categorySums.get(definition.key) /
            Math.max(
              1,
              [...categorySums.values()].reduce((sum, amount) => sum + amount, 0),
            )) *
          100
        : 0,
  }));

  const dailyTrips = trips.flatMap((trip) => {
    if (trip.itinerary_stale === true) return [];
    const days = trip.latest_itinerary?.days;
    if (!Array.isArray(days)) return [];
    const dailyFees = estimateFor(trip)?.daily_attraction_fees;
    const feesByDay = new Map(
      (Array.isArray(dailyFees) ? dailyFees : []).map((day) => [day.day_number, day]),
    );
    const breakdownAvailable = Array.isArray(dailyFees);
    const mappedDays = days.map((day) => {
      const feeDay = feesByDay.get(day.day_number);
      if (!feeDay) {
        return {
          dayNumber: day.day_number,
          date: day.date,
          cost: null,
          verifiedAmount: null,
          estimatedAmount: null,
          estimatedLower: null,
          estimatedUpper: null,
          knownCount: 0,
          estimatedCount: 0,
          unknownCount: 0,
          scheduledUniqueCount: new Set((day.stops ?? []).map((stop) => stop.attraction_id)).size,
          status: "unavailable",
          assumptions: [],
        };
      }
      const feeRecords = Array.isArray(feeDay.attractions) ? feeDay.attractions : [];
      const knownCount = feeRecords.filter((fee) => fee.status === "verified").length;
      const estimatedCount = feeRecords.filter((fee) => fee.status === "estimated").length;
      const verifiedAmount = feeDay.verified_fee_total;
      const estimatedAmount = feeDay.estimated_fee_representative_total;
      const hasResolvedFee = knownCount + estimatedCount > 0;
      const cost =
        feeDay.status === "no_attractions"
          ? 0
          : feeDay.status === "already_counted"
            ? null
            : hasResolvedFee
              ? feeDay.representative_total
              : null;
      return {
        dayNumber: feeDay.day_number,
        date: feeDay.date,
        cost,
        verifiedAmount,
        estimatedAmount,
        estimatedLower: feeDay.estimated_fee_lower_total,
        estimatedUpper: feeDay.estimated_fee_upper_total,
        knownCount,
        estimatedCount,
        unknownCount: feeDay.unresolved_attraction_count,
        scheduledUniqueCount: feeDay.scheduled_unique_attraction_count,
        status: feeDay.status,
        assumptions: feeDay.assumptions ?? [],
      };
    });
    return [
      {
        tripId: trip.id,
        tripName: trip.name || trip.destination,
        destination: trip.destination,
        breakdownAvailable,
        hasFeeData: mappedDays.some((day) => day.knownCount > 0 || day.estimatedCount > 0),
        days: mappedDays,
      },
    ];
  });

  return {
    tripCount: trips.length,
    estimatedTripCount: calculableTrips.length,
    estimatedCost,
    legacyDestinationCost,
    legacyEstimateTripCount: legacyTrips.length,
    incompleteBudgetTripCount: currentCompleteTrips.length - calculableTrips.length,
    staleTripCount: staleTrips.length,
    allocatedBudget,
    allEstimatesAvailable,
    categoryEstimateTripCount: categoryTrips.length,
    categoryDataScope,
    attractionFeeStats,
    remainingBudget: allEstimatesAvailable ? allocatedBudget - estimatedCost : null,
    dailyAverage: travelDays > 0 ? estimatedCost / travelDays : null,
    categories,
    dailyTrips,
  };
}

export function budgetStatus(estimated, allocated) {
  if (!finite(estimated) || !finite(allocated) || allocated <= 0) return null;
  const used = (estimated / allocated) * 100;
  if (used > 100) return { label: "Over Budget", used, tone: "danger" };
  if (used >= 80) return { label: "Near Budget Limit", used, tone: "warning" };
  return { label: "Within Budget", used, tone: "success" };
}

export { CATEGORY_DEFINITIONS };
