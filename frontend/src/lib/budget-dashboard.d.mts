import type { DailyAttractionFees } from "./api";

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
      unresolved_attraction_fee_count?: number;
      daily_attraction_fees?: DailyAttractionFees[];
      categories?: Array<{
        key: string;
        amount: number | null;
        status?: string;
        estimated_count?: number;
        unresolved_count?: number;
      }>;
      complete_budget?: {
        total_estimate: number | null;
        categories: Array<{
          key: string;
          amount: number | null;
          status?: string;
          estimated_count?: number;
          unresolved_count?: number;
        }>;
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
export function buildBudgetDashboard(trips: BudgetTrip[]): {
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
  attractionFeeStats: {
    originalUnknownCount: number;
    estimatedCount: number;
    unresolvedCount: number;
  };
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
    breakdownAvailable: boolean;
    hasFeeData: boolean;
    days: Array<{
      dayNumber: number;
      date: string;
      cost: number | null;
      verifiedAmount: number | null;
      estimatedAmount: number | null;
      estimatedLower: number | null;
      estimatedUpper: number | null;
      knownCount: number;
      estimatedCount: number;
      unknownCount: number;
      scheduledUniqueCount: number;
      status:
        "verified" | "estimated" | "partial" | "unavailable" | "no_attractions" | "already_counted";
      assumptions: string[];
    }>;
  }>;
};
export function budgetStatus(
  estimated: number,
  allocated: number,
): { label: string; used: number; tone: "danger" | "warning" | "success" } | null;
export const CATEGORY_DEFINITIONS: Array<{ key: string; label: string; color: string }>;
