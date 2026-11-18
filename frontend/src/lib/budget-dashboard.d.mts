export type BudgetTrip = {
  id: number;
  name?: string;
  budget: number;
  destination: string;
  start_date: string;
  end_date: string;
  latest_itinerary?: {
    budget_estimate?: {
      total_estimated?: number | null;
      unknown_attraction_fee_count?: number;
      categories?: Array<{ key: string; amount: number | null }>;
      complete_budget?: {
        total_estimate: number | null;
        categories: Array<{ key: string; amount: number | null; status?: string }>;
      } | null;
    } | null;
    days?: Array<{
      day_number: number;
      date: string;
      total_cost: number;
      stops?: Array<{ attraction_id: string; cost: number }>;
    }>;
  } | null;
  complete_budget_current?: boolean;
  itinerary_stale?: boolean;
};
export type BudgetTripDetail = {
  id: number;
  planning_inputs?: {
    attractions?: Array<{ id: string; cost: number; cost_known?: boolean | null }> | null;
  } | null;
};
export function buildBudgetDashboard(
  trips: BudgetTrip[],
  tripDetails?: BudgetTripDetail[],
): {
  tripCount: number;
  estimatedTripCount: number;
  estimatedCost: number;
  legacyDestinationCost: number;
  legacyEstimateTripCount: number;
  incompleteBudgetTripCount: number;
  staleTripCount: number;
  allocatedBudget: number;
  allEstimatesAvailable: boolean;
  remainingBudget: number | null;
  dailyAverage: number | null;
  categoryEstimateTripCount: number;
  categoryDataScope: "complete_trip" | "destination_only" | "unavailable";
  categories: Array<{
    key: string;
    label: string;
    color: string;
    amount: number | null;
    coverage: number;
    percentage: number;
    partial: boolean;
  }>;
  dailyTrips: Array<{
    tripId: number;
    tripName: string;
    destination: string;
    days: Array<{
      dayNumber: number;
      date: string;
      cost: number | null;
      knownCount: number;
      unknownCount: number;
      status: "available" | "partial" | "unavailable";
    }>;
  }>;
};
export function budgetStatus(
  estimated: number,
  allocated: number,
): { label: string; used: number; tone: "danger" | "warning" | "success" } | null;
export const CATEGORY_DEFINITIONS: Array<{ key: string; label: string; color: string }>;
