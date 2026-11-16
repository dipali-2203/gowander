import { create } from "zustand";
import type { Destination } from "@/data/destinations";
import type {
  AttractionInput,
  GeneratedItinerary,
  ParetoAlternative,
  PlanningResult,
} from "@/lib/api";

type TripState = {
  selected: Destination[];
  add: (d: Destination) => void;
  remove: (id: string) => void;
  generated: GeneratedItinerary | null;
  generatedDestination: string | null;
  alternatives: ParetoAlternative[];
  planningAttractions: AttractionInput[];
  planningStartLocation: [number, number] | null;
  planningBudget: number | null;
  annealing: PlanningResult["annealing"] | null;
  setGenerated: (
    itinerary: GeneratedItinerary,
    destination: string,
    alternatives: ParetoAlternative[],
    attractions: AttractionInput[],
    startLocation: [number, number],
    budget: number,
    annealing: PlanningResult["annealing"] | null,
  ) => void;
  clear: () => void;
};

const initialTripState = {
  selected: [],
  generated: null,
  generatedDestination: null,
  alternatives: [],
  planningAttractions: [],
  planningStartLocation: null,
  planningBudget: null,
  annealing: null,
};

export const useTripStore = create<TripState>((set) => ({
  ...initialTripState,
  add: (d) =>
    set((s) => (s.selected.some((x) => x.id === d.id) ? s : { selected: [...s.selected, d] })),
  remove: (id) => set((s) => ({ selected: s.selected.filter((x) => x.id !== id) })),
  setGenerated: (
    generated,
    generatedDestination,
    alternatives,
    planningAttractions,
    planningStartLocation,
    planningBudget,
    annealing,
  ) =>
    set({
      generated,
      generatedDestination,
      alternatives,
      planningAttractions,
      planningStartLocation,
      planningBudget,
      annealing,
    }),
  clear: () => set(initialTripState),
}));
