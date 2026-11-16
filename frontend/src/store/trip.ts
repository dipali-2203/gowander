import { create } from "zustand";
import type { Destination } from "@/data/destinations";
import type { AttractionInput, GeneratedItinerary, ParetoAlternative, PlanningResult } from "@/lib/api";

type TripState = {
  selected: Destination[];
  add: (d: Destination) => void;
  remove: (id: string) => void;
  generated: GeneratedItinerary | null;
  generatedDestination: string | null;
  alternatives: ParetoAlternative[];
  planningAttractions: AttractionInput[];
  annealing: PlanningResult["annealing"] | null;
  setGenerated: (itinerary: GeneratedItinerary, destination: string, alternatives: ParetoAlternative[], attractions: AttractionInput[], annealing: PlanningResult["annealing"]) => void;
};

export const useTripStore = create<TripState>((set) => ({
  selected: [],
  add: (d) =>
    set((s) => (s.selected.some((x) => x.id === d.id) ? s : { selected: [...s.selected, d] })),
  remove: (id) => set((s) => ({ selected: s.selected.filter((x) => x.id !== id) })),
  generated: null,
  generatedDestination: null,
  alternatives: [],
  planningAttractions: [],
  annealing: null,
  setGenerated: (generated, generatedDestination, alternatives, planningAttractions, annealing) => set({ generated, generatedDestination, alternatives, planningAttractions, annealing }),
}));
