import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, Send, Sparkles, User, X } from "lucide-react";
import { EmptyState, PageHeader } from "@/components/travel/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  acceptAssistantProposal,
  getAssistantProposal,
  getUserTrips,
  rejectAssistantProposal,
  sendAssistantMessage,
  type AccountTrip,
  type AssistantTripProposal,
} from "@/lib/api";
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

type Message = {
  id: number;
  role: "user" | "assistant";
  text: string;
  proposal?: AssistantTripProposal | null;
};

type RetryableMessage = {
  message: string;
  requestId: string;
  tripId: number | null;
  history: Array<{ role: "user" | "assistant"; content: string }>;
};

const prompts = [
  "Make my trip more relaxed",
  "Change my trip budget",
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
      text: "I can answer travel questions and prepare trip-change proposals. Nothing changes until you accept a proposal.",
    },
  ]);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [proposalActionId, setProposalActionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryableMessage, setRetryableMessage] = useState<RetryableMessage | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const requestInFlightRef = useRef(false);
  const nextMessageId = useRef(2);
  const tripSelectionInitialized = useRef(false);
  const selectedTrip = savedTrips.find((trip) => trip.id === selectedTripId) ?? null;
  const previewItinerary =
    selectedTrip?.latest_itinerary ??
    (selectedTripId === generated?.trip_id
      ? generated
      : selectedTripId === null
        ? generated
        : null);

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

  const send = async (text: string, retry?: RetryableMessage) => {
    if (requestInFlightRef.current) return;
    const message = retry?.message ?? text.trim();
    if (!message) return;
    const history =
      retry?.history ??
      (() => {
        const historyItems = messages.slice(-6);
        while (historyItems[0]?.role === "assistant") historyItems.shift();
        return historyItems.map((item) => ({ role: item.role, content: item.text }));
      })();
    const request = retry ?? {
      message,
      requestId: crypto.randomUUID(),
      tripId: selectedTripId,
      history,
    };
    requestInFlightRef.current = true;
    setRetryableMessage(request);
    if (!retry) {
      setMessages((items) => [
        ...items,
        { id: nextMessageId.current++, role: "user", text: message },
      ]);
      setInput("");
    }
    setTyping(true);
    setError(null);
    try {
      const result = await sendAssistantMessage({
        message,
        trip_id: request.tripId,
        request_id: request.requestId,
        conversation_history: history,
      });
      setRetryableMessage(null);
      setMessages((items) => [
        ...items,
        {
          id: nextMessageId.current++,
          role: "assistant",
          text: result.response,
          proposal: result.proposal,
        },
      ]);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The assistant could not respond. Please try again.",
      );
    } finally {
      requestInFlightRef.current = false;
      setTyping(false);
    }
  };

  const updateProposalMessage = (proposalId: string, proposal: AssistantTripProposal) => {
    setMessages((items) =>
      items.map((item) =>
        item.proposal?.proposal_id === proposalId ? { ...item, proposal } : item,
      ),
    );
  };

  const handleProposal = async (proposal: AssistantTripProposal, action: "accept" | "reject") => {
    if (proposalActionId || proposal.status !== "pending") return;
    setProposalActionId(proposal.proposal_id);
    setError(null);
    try {
      if (action === "accept") {
        const result = await acceptAssistantProposal(proposal.proposal_id);
        updateProposalMessage(proposal.proposal_id, result.proposal);
        let previewRefreshFailed = false;
        try {
          setSavedTrips(await getUserTrips());
        } catch {
          previewRefreshFailed = true;
        }
        setMessages((items) => [
          ...items,
          {
            id: nextMessageId.current++,
            role: "assistant",
            text: previewRefreshFailed
              ? "Your itinerary has been updated and saved. Reload the page if the preview does not refresh."
              : "Your itinerary has been updated and saved. The current trip preview is refreshed.",
          },
        ]);
      } else {
        const result = await rejectAssistantProposal(proposal.proposal_id);
        updateProposalMessage(proposal.proposal_id, result.proposal);
        setMessages((items) => [
          ...items,
          {
            id: nextMessageId.current++,
            role: "assistant",
            text: "No changes were made. Your original itinerary remains unchanged.",
          },
        ]);
      }
    } catch (cause) {
      try {
        const refreshedProposal = await getAssistantProposal(proposal.proposal_id);
        updateProposalMessage(proposal.proposal_id, refreshedProposal);
      } catch {
        // Keep the locally visible proposal if its status cannot be refreshed.
      }
      setError(
        cause instanceof Error
          ? cause.message
          : "The proposal could not be processed. Please try again.",
      );
    } finally {
      setProposalActionId(null);
    }
  };

  const changeTripContext = (value: string) => {
    setSelectedTripId(value ? Number(value) : null);
    setMessages([
      {
        id: nextMessageId.current++,
        role: "assistant",
        text: "What would you like to know? I can prepare trip-change proposals for your review.",
      },
    ]);
    setError(null);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="AI Assistant"
        description="Ask travel questions or review a proposed change to your saved trip. Nothing is applied without your approval."
      />

      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="assistant-trip" className="text-sm font-medium">
          Trip context
        </label>
        <select
          id="assistant-trip"
          className="h-10 min-w-56 rounded-md border border-input bg-background px-3 text-sm"
          value={selectedTripId ?? ""}
          disabled={typing || retryableMessage !== null || !savedTripsLoaded}
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
                  <div className="max-w-[92%] space-y-3">
                    <div
                      className={
                        item.role === "user"
                          ? "rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm text-primary-foreground"
                          : "whitespace-pre-wrap rounded-2xl rounded-bl-md bg-muted px-4 py-2.5 text-sm"
                      }
                    >
                      {item.text}
                    </div>
                    {item.role === "assistant" && item.proposal && (
                      <AssistantProposalCard
                        proposal={item.proposal}
                        busy={proposalActionId === item.proposal.proposal_id}
                        anyBusy={proposalActionId !== null}
                        onAccept={() => void handleProposal(item.proposal!, "accept")}
                        onReject={() => void handleProposal(item.proposal!, "reject")}
                      />
                    )}
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
                  <p>{error} Your message is preserved.</p>
                  {retryableMessage && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="mt-2"
                      disabled={typing}
                      onClick={() => void send(retryableMessage.message, retryableMessage)}
                    >
                      Retry message
                    </Button>
                  )}
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
                    disabled={typing || retryableMessage !== null}
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
                disabled={typing || retryableMessage !== null}
                placeholder="Ask anything about travel…"
                aria-label="Message the AI assistant"
                maxLength={2_000}
              />
              <Button
                type="submit"
                size="icon"
                aria-label="Send message"
                disabled={typing || retryableMessage !== null || !input.trim()}
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

function AssistantProposalCard({
  proposal,
  busy,
  anyBusy,
  onAccept,
  onReject,
}: {
  proposal: AssistantTripProposal;
  busy: boolean;
  anyBusy: boolean;
  onAccept: () => void;
  onReject: () => void;
}) {
  const comparison = proposal.itinerary_comparison;
  const beforeCounts = new Map(
    proposal.original_itinerary.days.map((day) => [day.day_number, day.stops.length]),
  );
  const afterCounts = new Map(
    proposal.proposed_itinerary.days.map((day) => [day.day_number, day.stops.length]),
  );
  const changedDays = [...new Set([...beforeCounts.keys(), ...afterCounts.keys()])].filter(
    (day) => beforeCounts.get(day) !== afterCounts.get(day),
  );
  const money = (amount: number | undefined | null) =>
    typeof amount === "number" ? `₹${amount.toLocaleString("en-IN")}` : "Unavailable";
  const statusLabel: Record<AssistantTripProposal["status"], string> = {
    pending: "Awaiting your decision",
    accepted: "Applied",
    rejected: "Rejected · no changes made",
    expired: "Expired",
    stale: "Out of date · create a new proposal",
  };
  const changeLabel = (field: string) =>
    field === "travel_pace" ? "Travel pace" : field === "budget_inr" ? "Trip budget" : field;
  const changeValue = (field: string, value: string | number) =>
    field === "budget_inr" && typeof value === "number" ? money(value) : String(value);

  return (
    <section
      className="rounded-xl border border-primary/20 bg-background p-4 shadow-sm"
      aria-label="Trip change proposal"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-primary">
            Proposed itinerary change
          </p>
          <h3 className="mt-1 font-semibold">{proposal.summary}</h3>
        </div>
        <Badge variant={proposal.status === "pending" ? "secondary" : "outline"}>
          {statusLabel[proposal.status]}
        </Badge>
      </div>

      {proposal.changes.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm">
          {proposal.changes.map((change) => (
            <li key={change.field}>
              {changeLabel(change.field)}: {changeValue(change.field, change.before)} →{" "}
              {changeValue(change.field, change.after)}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 border-t border-border pt-3">
        <h4 className="text-sm font-medium">Itinerary comparison</h4>
        {changedDays.length > 0 ? (
          <ul className="mt-1 space-y-1 text-sm text-muted-foreground">
            {changedDays.map((day) => (
              <li key={day}>
                Day {day}: {beforeCounts.get(day) ?? 0} → {afterCounts.get(day) ?? 0} activities
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">No day activity counts changed.</p>
        )}
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>{comparison.retained_stops.length} retained</span>
          <span>{comparison.moved_stops.length} moved</span>
          <span>{comparison.added_stops.length} added</span>
          <span>{comparison.removed_stops.length} removed</span>
        </div>
        {comparison.added_stops.length +
          comparison.removed_stops.length +
          comparison.moved_stops.length >
          0 && (
          <ul className="mt-2 space-y-1 text-xs">
            {comparison.added_stops.map((stop) => (
              <li key={`add-${stop.attraction_id}`}>
                Added to Day {stop.day_number}: {stop.name}
              </li>
            ))}
            {comparison.removed_stops.map((stop) => (
              <li key={`remove-${stop.attraction_id}`}>
                Removed from Day {stop.day_number}: {stop.name}
              </li>
            ))}
            {comparison.moved_stops.map((move) => (
              <li key={`move-${move.before.attraction_id}`}>
                Moved: {move.before.name}, Day {move.before.day_number} → Day{" "}
                {move.after.day_number}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-4 border-t border-border pt-3 text-sm">
        <h4 className="font-medium">Estimated budget impact</h4>
        <p className="mt-1 text-muted-foreground">
          Before: {money(proposal.budget_comparison.before?.total_estimated)} · After:{" "}
          {money(proposal.budget_comparison.after?.total_estimated)}
          {proposal.budget_comparison.estimated_difference !== null &&
            ` · Change: ${money(proposal.budget_comparison.estimated_difference)}`}
        </p>
        {proposal.budget_comparison.before?.unknown_attraction_fee_count ||
        proposal.budget_comparison.after?.unknown_attraction_fee_count ? (
          <p className="mt-1 text-xs text-amber-700">
            Some attraction fees are unknown; these are partial estimates, not verified totals.
          </p>
        ) : null}
      </div>

      {proposal.warnings.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-700">
          {proposal.warnings.map((warning, index) => (
            <li key={`${index}-${warning}`}>{warning}</li>
          ))}
        </ul>
      )}
      {!proposal.validation.valid && proposal.validation.issues.length > 0 && (
        <p className="mt-2 text-xs text-destructive">
          This proposal did not pass validation and cannot be applied.
        </p>
      )}

      {proposal.status === "pending" && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            size="sm"
            onClick={onAccept}
            disabled={busy || anyBusy || !proposal.validation.valid}
          >
            <Check className="mr-1 h-4 w-4" />
            {busy ? "Saving…" : "Accept changes"}
          </Button>
          <Button size="sm" variant="outline" onClick={onReject} disabled={busy || anyBusy}>
            <X className="mr-1 h-4 w-4" />
            {busy ? "Processing…" : "Reject"}
          </Button>
        </div>
      )}
    </section>
  );
}
