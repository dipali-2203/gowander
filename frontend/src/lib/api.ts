import { readableErrorMessage } from "./error-message.js";

export type AttractionInput = {
  id: string;
  name: string;
  category: string;
  latitude: number;
  longitude: number;
  cost: number;
  visit_minutes: number;
  preference_score: number;
  weather_risk: number;
  crowd_risk: number;
  availability_risk: number;
  weather_risk_known?: boolean;
  crowd_risk_known?: boolean;
  availability_risk_known?: boolean;
  risk_metadata?: Record<string, Record<string, unknown>>;
  opening_minute: number;
  closing_minute: number;
  cost_known?: boolean;
  catalog_category?: string | null;
  opening_hours?: string | null;
  opening_window_known?: boolean;
  visit_duration_known?: boolean;
  data_source?: string | null;
  provider_name?: string | null;
  external_provider_id?: string | null;
  source_url?: string | null;
  license_name?: string | null;
  attribution?: string | null;
  verification_status?: string | null;
  last_fetched_at?: string | null;
  last_verified_at?: string | null;
  data_freshness?: string | null;
  raw_tags?: Record<string, string>;
  source_dataset?: string | null;
  priority_score?: number;
  priority_reasons?: string[];
};

export type AttractionCatalog = {
  destination: string;
  data_source: "osm" | "synthetic" | "user_supplied" | "mixed" | "unavailable";
  catalog_status: "available" | "synthetic_fallback" | "not_ingested";
  message: string | null;
  start_location: [number, number] | null;
  attribution: string | null;
  attractions: AttractionInput[];
};

export type GeneratedItinerary = {
  trip_id: number;
  algorithm: string;
  days: Array<{
    day_number: number;
    date: string;
    total_cost: number;
    total_travel_minutes: number;
    total_visit_minutes: number;
    reserved_break_minutes: number;
    meal_breaks: Array<{ start_minute: number; duration_minutes: number }>;
    feasible: boolean;
    warnings: string[];
    stops: Array<{
      attraction_id: string;
      name: string;
      arrival_minute: number;
      departure_minute: number;
      travel_minutes_before: number;
      wait_minutes: number;
      wait_reason?: string | null;
      cost: number;
      preference_score: number;
      risk_score: number | null;
      risk_data_status?: "verified" | "assumed" | "partial" | "unavailable" | "not_applicable";
      weather_assessment?: WeatherRiskAssessment;
    }>;
  }>;
  total_cost: number;
  total_travel_minutes: number;
  total_visit_minutes: number;
  satisfaction: number;
  risk_score: number | null;
  risk_data_status: "verified" | "assumed" | "partial" | "unavailable" | "not_applicable";
  feasible: boolean;
  warnings: string[];
  data_source: "synthetic" | "user_supplied" | "osm";
  budget_estimate?: TripBudgetEstimate | null;
};

export type TripBudgetEstimate = {
  currency: "INR";
  total_estimated: number;
  per_person: number;
  daily_average: number;
  budget_limit: number;
  remaining_budget: number;
  within_budget: boolean;
  is_complete: boolean;
  unknown_attraction_fee_count: number;
  categories: Array<{
    key: string;
    label: string;
    amount: number;
    source: string;
    confidence: string;
    range_min: number;
    range_max: number;
    assumptions: string[];
  }>;
  exclusions: string[];
  last_updated: string | null;
};

export type ParetoAlternative = {
  objectives: { cost: number; time_proxy_minutes: number; risk_proxy: number; utility: number };
  itinerary: {
    optimization_scope?: "single_day";
    total_cost: number;
    total_travel_minutes: number;
    satisfaction: number;
    risk_score: number | null;
    risk_data_status?: "verified" | "assumed" | "partial" | "unavailable" | "not_applicable";
  };
  risk_data_status: "verified" | "assumed" | "partial" | "unavailable" | "not_applicable";
};

export type PlanningResult = {
  itinerary: GeneratedItinerary;
  alternatives: ParetoAlternative[];
  attractions: AttractionInput[];
  startLocation: [number, number];
  budget: number;
  annealing: {
    optimization_scope?: "single_day";
    total_cost: number;
    total_travel_minutes: number;
    satisfaction: number;
    risk_score: number | null;
    risk_data_status?: "verified" | "assumed" | "partial" | "unavailable" | "not_applicable";
  };
};

export type ScenarioResult = {
  stops: Array<{ name: string; cost: number; travel_minutes_before: number }>;
  total_cost: number;
  total_travel_minutes: number;
  satisfaction: number;
  risk_score: number | null;
  risk_data_status?: "verified" | "assumed" | "partial" | "unavailable" | "not_applicable";
  feasible: boolean;
  warnings: string[];
  disruptions_applied: string[];
  retained_planned_attraction_ids: string[];
  change_count: number;
};

export type ReliabilityResult = {
  scenarios: number;
  seed: number;
  completion_probability: number | null;
  expected_disruptions: number | null;
  risk_data_status: "verified" | "assumed" | "partial" | "unavailable";
  assumption: string;
};

export type ConditionsResult = {
  source: "estimated" | "live";
  conditions: Array<{
    attraction_id: string;
    weather_risk: number | null;
    crowd_risk: number | null;
    availability_risk: number | null;
    weather_risk_known: boolean;
    crowd_risk_known: boolean;
    availability_risk_known: boolean;
    risk_data_status: "verified" | "assumed" | "partial" | "unavailable";
    risk_metadata: Record<string, Record<string, unknown>>;
  }>;
};

export type AuthUser = {
  id: number;
  name: string;
  email: string;
  role: string;
  google_connected: boolean;
  google_email: string | null;
  password_login_enabled: boolean;
  first_name: string;
  last_name: string;
  phone_number: string | null;
  onboarding_completed: boolean;
  onboarding_skipped: boolean;
  travel_preferences: UserTravelPreferences;
};

export type UserTravelPreferences = {
  interests: string[];
  styles: string[];
  budget_preference: "budget" | "moderate" | "premium" | "luxury" | "flexible" | null;
  daily_budget_inr: number | null;
  transportation: string | null;
  accommodation: string | null;
  preferred_trip_duration_days: number | null;
  travel_pace: "relaxed" | "balanced" | "fast" | null;
};

export type AccountTrip = {
  id: number;
  name: string;
  origin: string;
  destination: string;
  start_date: string;
  end_date: string;
  budget: number;
  preferences: Record<string, unknown>;
  planning_options: TripPlanningOptions;
  optimization_results: {
    pareto?: ParetoAlternative[];
    simulated_annealing?: {
      optimization_scope?: "single_day";
      total_cost: number;
      total_travel_minutes: number;
      satisfaction: number;
      risk_score: number;
      feasible: boolean;
    };
  };
  latest_itinerary: GeneratedItinerary | null;
  created_at: string | null;
  updated_at: string | null;
  itinerary_stale: boolean;
  itinerary_revision: number;
  completed_attraction_ids: string[];
  pending_itinerary_revision: WeatherReplanProposal | null;
  itinerary_history?: Array<{ revision: number; saved_at: string; itinerary: GeneratedItinerary }>;
};

export type WeatherReplanProposal = {
  proposal_id: string;
  base_revision: number;
  mode: "forecast";
  day_number: number;
  date: string;
  provider: string;
  retrieved_at: string;
  attribution: string;
  forecast_available: boolean;
  can_accept: boolean;
  original_stops: GeneratedItinerary["days"][number]["stops"];
  revised_stops: GeneratedItinerary["days"][number]["stops"];
  weather_summary: Array<{
    attraction_id: string;
    name: string;
    scheduled_time: string | null;
    risk: WeatherRiskAssessment;
  }>;
  changes: Array<{
    status: string;
    original: Record<string, unknown>;
    revised: Record<string, unknown>;
    reason: string;
    additional_travel_minutes: number;
    additional_cost: number;
    weather_risk?: WeatherRiskAssessment;
    alternative_weather_risk?: WeatherRiskAssessment;
  }>;
  revised_itinerary: GeneratedItinerary;
  additional_travel_minutes: number;
  additional_cost: number;
  within_budget: boolean;
  warnings: string[];
};

export type WeatherRiskAssessment = {
  known: boolean;
  score: number | null;
  level: "low" | "moderate" | "high" | "unavailable";
  advisory_score: number | null;
  provider: string;
  data_kind: "forecast" | "observation" | "scenario";
  forecast_time: string | null;
  retrieved_at: string;
  confidence: "forecast" | "partial" | "unavailable";
  condition: string | null;
  condition_kind:
    | "sun"
    | "partly_cloudy"
    | "cloud"
    | "fog"
    | "drizzle"
    | "rain"
    | "snow"
    | "thunderstorm"
    | "unknown";
  variables: Partial<
    Record<
      | "precipitation_probability"
      | "precipitation"
      | "temperature_2m"
      | "apparent_temperature"
      | "wind_speed_10m"
      | "weather_code",
      number
    >
  >;
  advisories: Array<{ type: string; description: string; score: number }>;
  explanation: string[];
  outdoor_suitability_assumed: boolean;
};

export type TripPlanningOptions = {
  traveler_count: number;
  transportation_mode: string;
  accommodation_category: "budget" | "standard" | "premium" | "luxury";
  luxury_level?: number;
  meal_preferences: string[];
  miscellaneous_budget: number;
};

export type TripDetails = AccountTrip & {
  start_latitude: number;
  start_longitude: number;
  available_minutes_per_day: number;
  planning_inputs: {
    attractions: AttractionInput[];
    meal_breaks: Array<{ start_minute: number; duration_minutes: number }>;
    confirmed_activities: Array<{
      attraction_id: string;
      day_number: number;
      start_minute: number;
    }>;
    data_source: "synthetic" | "user_supplied" | "osm";
  } | null;
};

export type SharedItinerary = {
  title: string;
  origin: string;
  destination: string;
  start_date: string;
  end_date: string;
  traveler_count: number | null;
  days: Array<{
    day_number: number;
    date: string;
    stops: Array<{
      name: string;
      arrival_minute: number;
      departure_minute: number;
      visit_minutes: number;
      travel_minutes_before: number;
      weather_advisories: Array<{
        type: string;
        description: string;
        condition: string | null;
        forecast_time: string | null;
      }>;
    }>;
    meal_breaks: Array<{ start_minute: number; duration_minutes: number }>;
    total_travel_minutes: number;
  }>;
  budget_estimate: {
    currency: "INR";
    total_estimated: number | null;
    per_person: number | null;
    daily_average: number | null;
    categories: Array<{ label: string | null; amount: number | null }>;
    exclusions: string[];
  } | null;
  attributions: string[];
};

const apiBaseUrl = import.meta.env["VITE_API_BASE_URL"] ?? "http://localhost:8000";
export const googleSignInStartUrl = `${apiBaseUrl}/api/v1/auth/google/start`;

export async function startGoogleAccountLink() {
  return request<{ authorization_url: string }>("/api/v1/auth/google/link/start", {
    method: "POST",
  });
}

export async function disconnectGoogleAccount() {
  return request<{ ok: boolean }>("/api/v1/auth/google/link", {
    method: "DELETE",
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}${path}`, {
      headers: { "content-type": "application/json", ...init?.headers },
      credentials: "include",
      ...init,
    });
  } catch {
    throw new Error(
      `Cannot reach the trip service at ${apiBaseUrl}. Check that the backend is running and allows this frontend origin.`,
    );
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new Error(
      readableErrorMessage(
        body,
        `The planning service could not complete the request (HTTP ${response.status}).`,
      ),
    );
  }
  return response.json() as Promise<T>;
}

export async function signUp(input: { name: string; email: string; password: string }) {
  return request<{ user: AuthUser }>("/api/v1/auth/signup", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function signIn(input: { email: string; password: string }) {
  return request<{ user: AuthUser }>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function currentUser() {
  return request<{ user: AuthUser }>("/api/v1/auth/me");
}

export async function getProfile() {
  return request<{ profile: AuthUser }>("/api/v1/account/profile");
}

export async function updateProfile(input: {
  first_name: string;
  last_name: string;
  phone_number: string | null;
}) {
  return request<{ profile: AuthUser }>("/api/v1/account/profile", {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function getTravelPreferences() {
  return request<{
    preferences: UserTravelPreferences;
    onboarding_completed: boolean;
    onboarding_skipped: boolean;
  }>("/api/v1/account/preferences");
}

export async function saveTravelPreferences(preferences: UserTravelPreferences) {
  return request<{ preferences: UserTravelPreferences; onboarding_completed: boolean }>(
    "/api/v1/account/preferences",
    { method: "PUT", body: JSON.stringify(preferences) },
  );
}

export async function completeOnboarding(preferences: UserTravelPreferences) {
  return request<{ ok: boolean; onboarding_completed: boolean; user: AuthUser }>(
    "/api/v1/account/onboarding/complete",
    { method: "POST", body: JSON.stringify(preferences) },
  );
}

export async function skipOnboarding(preferences?: UserTravelPreferences) {
  return request<{ ok: boolean; onboarding_completed: boolean; onboarding_skipped: boolean }>(
    "/api/v1/account/onboarding/skip",
    { method: "POST", body: preferences ? JSON.stringify(preferences) : "{}" },
  );
}

export async function getBookmarks() {
  return request<{ items: Array<{ destination_id: string }> }>("/api/v1/account/bookmarks");
}

export async function addBookmark(destinationId: string) {
  return request<{ destination_id: string }>(
    `/api/v1/account/bookmarks/${encodeURIComponent(destinationId)}`,
    {
      method: "POST",
    },
  );
}

export async function removeBookmark(destinationId: string) {
  return request<{ ok: boolean }>(
    `/api/v1/account/bookmarks/${encodeURIComponent(destinationId)}`,
    {
      method: "DELETE",
    },
  );
}

export async function getUserTrips() {
  return request<AccountTrip[]>("/api/v1/trips");
}

export async function getTrip(tripId: number) {
  return request<TripDetails>(`/api/v1/trips/${tripId}`);
}

export function createTripShareLink(tripId: number) {
  return request<{ token: string; reused: boolean }>(`/api/v1/trips/${tripId}/share-link`, {
    method: "POST",
  });
}

export function revokeTripShareLink(tripId: number) {
  return request<{ revoked: boolean }>(`/api/v1/trips/${tripId}/share-link`, {
    method: "DELETE",
  });
}

export function getSharedItinerary(token: string) {
  return request<SharedItinerary>(`/api/v1/shared/${encodeURIComponent(token)}`, {
    credentials: "omit",
    referrerPolicy: "no-referrer",
  });
}

export async function downloadTripPdf(tripId: number) {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/api/v1/trips/${tripId}/export.pdf`, {
      credentials: "include",
      headers: { accept: "application/pdf" },
    });
  } catch {
    throw new Error(
      `Cannot reach the trip service at ${apiBaseUrl}. Check that the backend is running and allows this frontend origin.`,
    );
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new Error(
      readableErrorMessage(
        body,
        `The itinerary PDF could not be downloaded (HTTP ${response.status}).`,
      ),
    );
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1];
  anchor.href = objectUrl;
  anchor.download = filename || "gowander-itinerary.pdf";
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}

export function getAttractionCatalog(destination: string) {
  const key = destination.toLowerCase();
  const cached = attractionCatalogCache.get(key);
  if (cached && cached.expiresAt > Date.now()) return cached.promise;
  const promise = request<AttractionCatalog>(
    `/api/v1/attractions/catalog/${encodeURIComponent(destination)}`,
  );
  attractionCatalogCache.set(key, { promise, expiresAt: Date.now() + 5 * 60_000 });
  promise.catch(() => attractionCatalogCache.delete(key));
  return promise;
}

const attractionCatalogCache = new Map<
  string,
  { promise: Promise<AttractionCatalog>; expiresAt: number }
>();

export async function updateTrip(
  tripId: number,
  input: Partial<
    Pick<
      TripDetails,
      | "name"
      | "origin"
      | "destination"
      | "start_date"
      | "end_date"
      | "budget"
      | "available_minutes_per_day"
      | "preferences"
      | "planning_options"
    >
  >,
) {
  return request<{ trip: TripDetails }>(`/api/v1/trips/${tripId}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function duplicateTrip(tripId: number) {
  return request<{ id: number; name: string }>(`/api/v1/trips/${tripId}/duplicate`, {
    method: "POST",
  });
}

export async function deleteTrip(tripId: number) {
  return request<{ ok: boolean }>(`/api/v1/trips/${tripId}`, { method: "DELETE" });
}

export async function regenerateTrip(tripId: number) {
  return request<GeneratedItinerary>(`/api/v1/trips/${tripId}/regenerate`, {
    method: "POST",
  });
}

export async function signOut() {
  return request<{ ok: boolean }>("/api/v1/auth/logout", { method: "POST" });
}

export async function requestPasswordReset(email: string) {
  return request<{ message: string }>("/api/v1/auth/password-reset/request", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function confirmPasswordReset(token: string, password: string) {
  return request<{ ok: boolean }>("/api/v1/auth/password-reset/confirm", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });
}

export async function createAndOptimizeTrip(input: {
  origin: string;
  destination: string;
  days: number;
  budget: number;
  travelerCount: number;
  accommodationCategory: TripPlanningOptions["accommodation_category"];
  luxuryLevel: number;
  miscellaneousBudget: number;
  mealPreferences: string[];
  interests: string[];
  preferences: {
    riskTolerance: number;
    walkingTolerance: number;
    crowdTolerance: number;
    pace: number;
    transport: string;
  };
}): Promise<PlanningResult> {
  const catalog = await request<{
    attractions: AttractionInput[];
    data_source: "osm" | "synthetic" | "user_supplied" | "mixed" | "unavailable";
    catalog_status: AttractionCatalog["catalog_status"];
    message: string | null;
    start_location: [number, number] | null;
  }>(`/api/v1/attractions/catalog/${encodeURIComponent(input.destination)}`);
  if (catalog.attractions.length === 0) {
    throw new Error(
      catalog.message ?? `No attraction catalog is available for ${input.destination} yet.`,
    );
  }
  const [startLatitude, startLongitude] = catalog.start_location ?? [26.9124, 75.7873];

  const start = new Date();
  const end = new Date(start);
  end.setDate(start.getDate() + Math.max(0, input.days - 1));
  const toIsoDate = (value: Date) =>
    `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  const interestMap = Object.fromEntries(
    input.interests.map((interest) => [interest.toLowerCase(), 1]),
  );

  const trip = await request<{ id: number }>("/api/v1/trips", {
    method: "POST",
    body: JSON.stringify({
      name: `${input.origin} to ${input.destination}`,
      origin: input.origin,
      destination: input.destination,
      start_date: toIsoDate(start),
      end_date: toIsoDate(end),
      budget: input.budget,
      // Planner timestamps are minutes from midnight: 09:00 start, 19:00 cutoff.
      available_minutes_per_day: 1140,
      start_latitude: startLatitude,
      start_longitude: startLongitude,
      preferences: {
        interests: interestMap,
        risk_tolerance: input.preferences.riskTolerance,
        walking_tolerance: input.preferences.walkingTolerance,
        crowd_tolerance: input.preferences.crowdTolerance,
        budget_sensitivity: 1 - input.preferences.pace,
        travel_pace: input.preferences.pace,
        preferred_transport: input.preferences.transport,
      },
      planning_options: {
        traveler_count: input.travelerCount,
        transportation_mode: input.preferences.transport,
        accommodation_category: input.accommodationCategory,
        luxury_level: input.luxuryLevel,
        meal_preferences: input.mealPreferences,
        miscellaneous_budget: input.miscellaneousBudget,
      },
    }),
  });

  const itinerary = await request<GeneratedItinerary>(
    `/api/v1/trips/${trip.id}/optimize-multiday`,
    {
      method: "POST",
      body: JSON.stringify({
        attractions: catalog.attractions,
        algorithm: "greedy",
        data_source: catalog.data_source === "mixed" ? "user_supplied" : catalog.data_source,
        meal_breaks: [{ start_minute: 780, duration_minutes: 60 }],
        confirmed_activities: [],
      }),
    },
  );
  const pareto = await request<{ alternatives: ParetoAlternative[] }>(
    `/api/v1/trips/${trip.id}/pareto`,
    {
      method: "POST",
      body: JSON.stringify({
        attractions: catalog.attractions,
        algorithm: "nsga2",
        seed: 42,
        max_alternatives: 3,
      }),
    },
  );
  const annealing = await request<PlanningResult["annealing"]>(`/api/v1/trips/${trip.id}/anneal`, {
    method: "POST",
    body: JSON.stringify({
      attractions: catalog.attractions,
      algorithm: "simulated_annealing",
      seed: 42,
    }),
  });
  return {
    itinerary,
    alternatives: pareto.alternatives,
    attractions: catalog.attractions,
    startLocation: [startLatitude, startLongitude],
    budget: input.budget,
    annealing,
  };
}

export function replanScenario(
  tripId: number,
  attractions: AttractionInput[],
  disruptions: Array<{
    kind: "rainfall" | "traffic" | "crowding" | "closure";
    severity: number;
    affected_attraction_ids?: string[];
  }>,
  remainingBudget = 60000,
  remainingMinutes = 1200,
  previousPlannedAttractionIds: string[] = [],
  completedAttractionIds: string[] = [],
  currentLocation: [number, number] = [26.9124, 75.7873],
) {
  return request<ScenarioResult>(`/api/v1/trips/${tripId}/replan-scenario`, {
    method: "POST",
    body: JSON.stringify({
      attractions,
      disruptions,
      current_latitude: currentLocation[0],
      current_longitude: currentLocation[1],
      remaining_budget: remainingBudget,
      remaining_minutes: remainingMinutes,
      completed_attraction_ids: completedAttractionIds,
      closed_attraction_ids: [],
      previous_planned_attraction_ids: previousPlannedAttractionIds,
      data_source: "synthetic",
    }),
  });
}

export function proposeWeatherReplan(tripId: number, dayNumber: number) {
  return request<WeatherReplanProposal>(`/api/v1/trips/${tripId}/replan/weather`, {
    method: "POST",
    body: JSON.stringify({ day_number: dayNumber }),
  });
}

export function saveCompletedActivities(
  tripId: number,
  completedAttractionIds: string[],
  itineraryRevision: number,
) {
  return request<{ completed_attraction_ids: string[]; itinerary_revision: number }>(
    `/api/v1/trips/${tripId}/completed-activities`,
    {
      method: "PUT",
      body: JSON.stringify({
        completed_attraction_ids: completedAttractionIds,
        itinerary_revision: itineraryRevision,
      }),
    },
  );
}

export function acceptWeatherReplan(tripId: number, proposal: WeatherReplanProposal) {
  return request<{
    latest_itinerary: GeneratedItinerary;
    itinerary_revision: number;
    completed_attraction_ids: string[];
  }>(`/api/v1/trips/${tripId}/replan/weather/accept`, {
    method: "POST",
    body: JSON.stringify({
      proposal_id: proposal.proposal_id,
      base_revision: proposal.base_revision,
    }),
  });
}

export function rejectWeatherReplan(tripId: number, proposal: WeatherReplanProposal) {
  return request<{ rejected: boolean; itinerary_revision: number }>(
    `/api/v1/trips/${tripId}/replan/weather/reject`,
    {
      method: "POST",
      body: JSON.stringify({
        proposal_id: proposal.proposal_id,
        base_revision: proposal.base_revision,
      }),
    },
  );
}

export function simulateReliability(tripId: number, attractions: AttractionInput[]) {
  return request<ReliabilityResult>(`/api/v1/trips/${tripId}/risk-simulation`, {
    method: "POST",
    body: JSON.stringify({ attractions, scenarios: 1000, seed: 42 }),
  });
}

export function loadConditions(tripId: number, attractions: AttractionInput[]) {
  return request<ConditionsResult>(`/api/v1/trips/${tripId}/conditions`, {
    method: "POST",
    body: JSON.stringify({ attractions }),
  });
}

export function submitPreferenceFeedback(
  tripId: number,
  events: Array<{ category: string; rating?: number; skipped?: boolean }>,
) {
  return request(`/api/v1/trips/${tripId}/preference-feedback`, {
    method: "POST",
    body: JSON.stringify({ events }),
  });
}
