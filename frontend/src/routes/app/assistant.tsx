import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Send, Sparkles, User } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/travel/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { getUserTrips, sendAssistantMessage, type AccountTrip } from "@/lib/api";
import { useTripStore } from "@/store/trip";

export const Route = createFileRoute("/app/assistant")({
  head: () => ({
    meta: [
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { title: "AI Assistant · GoWander" },
      { name: "description", content: "Ask GoWander about travel and your saved trip." },
      { property: "og:title", content: "AI Assistant · GoWander" },
      { property: "og:description", content: "A conversational travel-planning companion." },
    ],
  }),
  component: Assistant,
});

type Message = { id: number; role: "user" | "assistant"; text: string };

const prompts = [
  "Suggest a lower-cost alternative",
  "Change the trip pace",
  "Add a food stop",
  "Suggest places nearby",
  "What should I pack?",
];

function Assistant() {
  const generated = useTripStore((state) => state.generated);
  const [savedTrips, setSavedTrips] = useState<AccountTrip[]>([]);
  const [savedTripsLoaded, setSavedTripsLoaded] = useState(false);
  const [selectedTripId, setSelectedTripId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 1,
      role: "assistant",
      text: "I can answer travel questions and discuss possible trip changes. I will not modify or save your trip in this chat.",
    },
  ]);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const nextMessageId = useRef(2);
  const tripSelectionInitialized = useRef(false);
  const selectedTrip = savedTrips.find((trip) => trip.id === selectedTripId) ?? null;
  const previewItinerary =
    selectedTripId === generated?.trip_id
      ? generated
      : (selectedTrip?.latest_itinerary ?? (selectedTripId === null ? generated : null));

  useEffect(() => {
    let active = true;
    getUserTrips()
      .then((trips) => {
        if (active) {
          setSavedTrips(trips);
          setSavedTripsLoaded(true);
        }
      })
      .catch(() => {
        // General travel chat remains available if the trip list cannot be loaded.
        if (active) setSavedTripsLoaded(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!savedTripsLoaded || tripSelectionInitialized.current) return;
    tripSelectionInitialized.current = true;
    if (generated?.trip_id && savedTrips.some((trip) => trip.id === generated.trip_id)) {
      setSelectedTripId(generated.trip_id);
    } else if (savedTrips.length === 1) {
      setSelectedTripId(savedTrips[0]?.id ?? null);
    }
  }, [generated?.trip_id, savedTrips, savedTripsLoaded]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, typing, error]);

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || typing) return;
    const historyItems = messages.slice(-6);
    while (historyItems[0]?.role === "assistant") historyItems.shift();
    const history = historyItems.map((item) => ({
      role: item.role,
      content: item.text,
    }));
    setMessages((items) => [
      ...items,
      { id: nextMessageId.current++, role: "user", text: message },
    ]);
    setInput("");
    setTyping(true);
    setError(null);
    try {
      const result = await sendAssistantMessage({
        message,
        trip_id: selectedTripId,
        conversation_history: history,
      });
      setMessages((items) => [
        ...items,
        { id: nextMessageId.current++, role: "assistant", text: result.response },
      ]);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The assistant could not respond. Please try again.",
      );
    } finally {
      setTyping(false);
    }
  };

  const changeTripContext = (value: string) => {
    setSelectedTripId(value ? Number(value) : null);
    setMessages([
      {
        id: nextMessageId.current++,
        role: "assistant",
        text: "What would you like to know? I will not modify or save your trip.",
      },
    ]);
    setError(null);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="AI Assistant"
        description="Ask travel questions or discuss your saved trip. This assistant does not apply trip changes."
      />

      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="assistant-trip" className="text-sm font-medium">
          Trip context
        </label>
        <select
          id="assistant-trip"
          className="h-10 min-w-56 rounded-md border border-input bg-background px-3 text-sm"
          value={selectedTripId ?? ""}
          disabled={typing || !savedTripsLoaded}
          onChange={(event) => changeTripContext(event.target.value)}
        >
          <option value="">General travel chat</option>
          {savedTrips.map((trip) => (
            <option key={trip.id} value={trip.id}>
              {trip.name} · {trip.destination}
            </option>
          ))}
        </select>
        {selectedTripId !== null && (
          <span className="text-xs text-muted-foreground">
            Trip details load securely from your account
            {selectedTrip ? ` · ${selectedTrip.destination}` : ""}.
          </span>
        )}
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section className="surface flex h-[calc(100dvh-270px)] min-h-[520px] flex-col">
          <ScrollArea className="flex-1 p-5">
            <ul className="space-y-4">
              {messages.map((item) => (
                <motion.li
                  key={item.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={item.role === "user" ? "flex justify-end" : "flex gap-3"}
                >
                  {item.role === "assistant" && (
                    <span className="gradient-primary grid h-8 w-8 shrink-0 place-items-center rounded-xl text-primary-foreground">
                      <Sparkles className="h-4 w-4" />
                    </span>
                  )}
                  <div
                    className={
                      item.role === "user"
                        ? "max-w-[80%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm text-primary-foreground"
                        : "max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-bl-md bg-muted px-4 py-2.5 text-sm"
                    }
                  >
                    {item.text}
                  </div>
                  {item.role === "user" && (
                    <span className="ml-3 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-muted">
                      <User className="h-4 w-4" />
                    </span>
                  )}
                </motion.li>
              ))}
              <AnimatePresence>
                {typing && (
                  <motion.li
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="flex gap-3"
                    aria-label="Assistant is responding"
                  >
                    <span className="gradient-primary grid h-8 w-8 place-items-center rounded-xl text-primary-foreground">
                      <Sparkles className="h-4 w-4" />
                    </span>
                    <span className="flex items-center gap-1 rounded-2xl bg-muted px-4 py-3">
                      {[0, 1, 2].map((index) => (
                        <motion.span
                          key={index}
                          className="h-1.5 w-1.5 rounded-full bg-muted-foreground"
                          animate={{ opacity: [0.3, 1, 0.3] }}
                          transition={{ repeat: Infinity, duration: 1, delay: index * 0.18 }}
                        />
                      ))}
                    </span>
                  </motion.li>
                )}
              </AnimatePresence>
              {error && (
                <li
                  role="alert"
                  className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive"
                >
                  {error} Your message is still here; you can try again.
                </li>
              )}
            </ul>
            <div ref={endRef} />
          </ScrollArea>

          <div className="space-y-3 border-t border-border p-4">
            <ul className="flex flex-wrap gap-2">
              {prompts.map((prompt) => (
                <li key={prompt}>
                  <button
                    type="button"
                    onClick={() => void send(prompt)}
                    disabled={typing}
                    className="rounded-full border border-border px-3 py-1.5 text-xs transition-colors hover:bg-muted disabled:opacity-50"
                  >
                    {prompt}
                  </button>
                </li>
              ))}
            </ul>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void send(input);
              }}
              className="flex gap-2"
            >
              <Input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask anything about travel…"
                aria-label="Message the AI assistant"
                maxLength={2_000}
              />
              <Button
                type="submit"
                size="icon"
                aria-label="Send message"
                disabled={typing || !input.trim()}
              >
                <Send className="h-4 w-4" />
              </Button>
            </form>
          </div>
        </section>

        <aside className="surface-static space-y-3 p-5 lg:sticky lg:top-24 lg:self-start">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">Itinerary preview</h2>
            <Badge variant="secondary">{previewItinerary ? "Current plan" : "No plan"}</Badge>
          </div>
          {previewItinerary ? (
            <ol className="space-y-3">
              {previewItinerary.days.map((day) => (
                <li key={day.day_number} className="rounded-xl border border-border p-3">
                  <div className="flex items-center justify-between gap-2 text-sm">
                    <span className="font-medium">
                      Day {day.day_number} · {day.date}
                    </span>
                    <span className="text-muted-foreground">
                      ₹{day.total_cost.toLocaleString("en-IN")}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                    {day.stops.map((stop) => stop.name).join(" · ") || "No stops in this day"}
                  </p>
                </li>
              ))}
            </ol>
          ) : (
            <EmptyState
              title="No itinerary yet."
              description="Create a trip to see your itinerary here."
              action={
                <Button asChild size="sm">
                  <Link to="/app/planner">Open Trip Planner</Link>
                </Button>
              }
            />
          )}
        </aside>
      </div>
    </div>
  );
}
