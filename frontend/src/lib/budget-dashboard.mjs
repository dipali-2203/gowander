const CATEGORY_DEFINITIONS = [
  { key: "accommodation", label: "Accommodation", color: "#f97316" },
  { key: "transportation", label: "Transport", color: "#0ea5e9" },
  { key: "meals", label: "Food", color: "#22c55e" },
  { key: "attractions", label: "Tickets / Attractions", color: "#a855f7" },
  { key: "miscellaneous", label: "Miscellaneous", color: "#eab308" },
];

const finite = (value) => typeof value === "number" && Number.isFinite(value);

export function buildBudgetDashboard(trips, tripDetails = []) {
  const estimatedTrips = trips.filter((trip) =>
    finite(trip.latest_itinerary?.budget_estimate?.total_estimated),
  );
  const estimatedCost = estimatedTrips.reduce(
    (sum, trip) => sum + trip.latest_itinerary.budget_estimate.total_estimated,
    0,
  );
  const allEstimatesAvailable = estimatedTrips.length === trips.length;
  const allocatedBudget = trips.reduce(
    (sum, trip) => sum + (finite(trip.budget) ? trip.budget : 0),
    0,
  );
  const travelDays = estimatedTrips.reduce((sum, trip) => {
    const start = Date.parse(`${trip.start_date}T00:00:00Z`);
    const end = Date.parse(`${trip.end_date}T00:00:00Z`);
    return (
      sum +
      (Number.isFinite(start) && Number.isFinite(end) && end >= start
        ? Math.floor((end - start) / 86_400_000) + 1
        : 0)
    );
  }, 0);

  const categorySums = new Map(CATEGORY_DEFINITIONS.map(({ key }) => [key, 0]));
  const categoryCoverage = new Map(CATEGORY_DEFINITIONS.map(({ key }) => [key, 0]));
  for (const trip of estimatedTrips) {
    const categories = trip.latest_itinerary?.budget_estimate?.categories;
    if (!Array.isArray(categories)) continue;
    for (const category of categories) {
      if (categorySums.has(category.key) && finite(category.amount)) {
        categorySums.set(category.key, categorySums.get(category.key) + category.amount);
        categoryCoverage.set(category.key, categoryCoverage.get(category.key) + 1);
      }
    }
  }
  const categories = CATEGORY_DEFINITIONS.map((definition) => ({
    ...definition,
    amount: categoryCoverage.get(definition.key) ? categorySums.get(definition.key) : null,
    coverage: categoryCoverage.get(definition.key),
    partial:
      categoryCoverage.get(definition.key) < estimatedTrips.length ||
      (definition.key === "attractions" &&
        estimatedTrips.some(
          (trip) => (trip.latest_itinerary?.budget_estimate?.unknown_attraction_fee_count ?? 0) > 0,
        )),
    percentage: estimatedCost > 0 ? (categorySums.get(definition.key) / estimatedCost) * 100 : 0,
  }));

  const detailById = new Map(tripDetails.map((trip) => [trip.id, trip]));
  const dailyTrips = trips.flatMap((trip) => {
    const days = trip.latest_itinerary?.days;
    if (!Array.isArray(days)) return [];
    const detail = detailById.get(trip.id);
    const attractions = new Map(
      (detail?.planning_inputs?.attractions ?? []).map((attraction) => [attraction.id, attraction]),
    );
    return [
      {
        tripId: trip.id,
        tripName: trip.name || trip.destination,
        destination: trip.destination,
        days: days.map((day) => {
          if (!Array.isArray(day.stops)) {
            return {
              dayNumber: day.day_number,
              date: day.date,
              cost: null,
              knownCount: 0,
              unknownCount: 0,
              status: "unavailable",
            };
          }
          let availableCost = 0;
          let knownCount = 0;
          let unknownCount = 0;
          for (const stop of day.stops ?? []) {
            const attraction = attractions.get(stop.attraction_id);
            if (attraction?.cost_known === true && finite(attraction.cost)) {
              availableCost += finite(stop.cost) ? stop.cost : attraction.cost;
              knownCount += 1;
            } else {
              unknownCount += 1;
            }
          }
          const cost = unknownCount === 0 ? availableCost : knownCount > 0 ? availableCost : null;
          return {
            dayNumber: day.day_number,
            date: day.date,
            cost,
            knownCount,
            unknownCount,
            status: cost === null ? "unavailable" : unknownCount > 0 ? "partial" : "available",
          };
        }),
      },
    ];
  });

  return {
    tripCount: trips.length,
    estimatedTripCount: estimatedTrips.length,
    estimatedCost,
    allocatedBudget,
    allEstimatesAvailable,
    categoryEstimateTripCount: estimatedTrips.length,
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
