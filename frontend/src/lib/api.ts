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
  opening_minute: number;
  closing_minute: number;
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
    feasible: boolean;
    warnings: string[];
    stops: Array<{
      attraction_id: string;
      name: string;
      arrival_minute: number;
      departure_minute: number;
      travel_minutes_before: number;
      wait_minutes: number;
      cost: number;
      preference_score: number;
      risk_score: number;
    }>;
  }>;
  total_cost: number;
  total_travel_minutes: number;
  total_visit_minutes: number;
  satisfaction: number;
  risk_score: number;
  feasible: boolean;
  warnings: string[];
  data_source: "synthetic" | "user_supplied";
};

export type ParetoAlternative = {
  objectives: { cost: number; time_proxy_minutes: number; risk_proxy: number; utility: number };
  itinerary: {
    total_cost: number;
    total_travel_minutes: number;
    satisfaction: number;
    risk_score: number;
  };
};

export type PlanningResult = {
  itinerary: GeneratedItinerary;
  alternatives: ParetoAlternative[];
  attractions: AttractionInput[];
  annealing: {
    total_cost: number;
    total_travel_minutes: number;
    satisfaction: number;
    risk_score: number;
  };
};

export type ScenarioResult = {
  stops: Array<{ name: string; cost: number; travel_minutes_before: number }>;
  total_cost: number;
  total_travel_minutes: number;
  satisfaction: number;
  risk_score: number;
  feasible: boolean;
  warnings: string[];
  disruptions_applied: string[];
  retained_planned_attraction_ids: string[];
  change_count: number;
};

export type ReliabilityResult = {
  scenarios: number;
  seed: number;
  completion_probability: number;
  expected_disruptions: number;
  assumption: string;
};

export type ConditionsResult = {
  source: "estimated" | "live";
  conditions: Array<{
    attraction_id: string;
    weather_risk: number;
    crowd_risk: number;
    availability_risk: number;
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
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: { "content-type": "application/json", ...init?.headers },
    credentials: "include",
    ...init,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? "The planning service could not complete the request.");
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
  destination: string;
  days: number;
  budget: number;
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
    data_source: "synthetic";
    start_location: [number, number] | null;
  }>(`/api/v1/attractions/catalog/${encodeURIComponent(input.destination)}`);
  if (catalog.attractions.length === 0) {
    throw new Error(`No local planning catalog is available for ${input.destination} yet.`);
  }
  const [startLatitude, startLongitude] = catalog.start_location ?? [26.9124, 75.7873];

  const start = new Date();
  const end = new Date(start);
  end.setDate(start.getDate() + Math.max(0, input.days - 1));
  const toIsoDate = (value: Date) => value.toISOString().slice(0, 10);
  const interestMap = Object.fromEntries(
    input.interests.map((interest) => [
      interest === "Heritage" ? "history" : interest.toLowerCase(),
      1,
    ]),
  );

  const trip = await request<{ id: number }>("/api/v1/trips", {
    method: "POST",
    body: JSON.stringify({
      destination: input.destination,
      start_date: toIsoDate(start),
      end_date: toIsoDate(end),
      budget: input.budget,
      available_minutes_per_day: 720,
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
    }),
  });

  const itinerary = await request<GeneratedItinerary>(
    `/api/v1/trips/${trip.id}/optimize-multiday`,
    {
      method: "POST",
      body: JSON.stringify({
        attractions: catalog.attractions,
        algorithm: "greedy",
        data_source: "synthetic",
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
  remainingMinutes = 720,
  previousPlannedAttractionIds: string[] = [],
) {
  return request<ScenarioResult>(`/api/v1/trips/${tripId}/replan-scenario`, {
    method: "POST",
    body: JSON.stringify({
      attractions,
      disruptions,
      current_latitude: 26.9124,
      current_longitude: 75.7873,
      remaining_budget: remainingBudget,
      remaining_minutes: remainingMinutes,
      completed_attraction_ids: [],
      closed_attraction_ids: [],
      previous_planned_attraction_ids: previousPlannedAttractionIds,
      data_source: "synthetic",
    }),
  });
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
