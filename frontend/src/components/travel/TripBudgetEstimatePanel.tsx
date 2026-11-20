import type { CompleteBudgetCategory, CompleteTripBudget, TripBudgetEstimate } from "@/lib/api";

const formatInr = (amount: number) =>
  `₹${amount.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

const statusLabel: Record<string, string> = {
  verified: "Verified",
  user_provided: "User provided",
  estimated: "Estimated",
  partial: "Partial",
  unavailable: "Unavailable",
};

function subtotalLabel(value: number | null | undefined, emptyLabel: string) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "Unavailable";
  return value === 0 ? emptyLabel : formatInr(value);
}

function categoryAmountLabel(category: CompleteBudgetCategory) {
  if (category.status === "unavailable" || typeof category.amount !== "number")
    return "Unavailable";
  if (category.status === "partial")
    return (category.estimated_count ?? 0) > 0
      ? `${formatInr(category.amount)} available estimate · partial`
      : (category.verified_count ?? 0) > 0
        ? `${formatInr(category.amount)} verified subtotal · partial`
        : `${formatInr(category.amount)} available subtotal · partial`;
  if (category.status === "estimated") return `${formatInr(category.amount)} estimated`;
  if (category.status === "verified") return `${formatInr(category.amount)} verified`;
  if (category.status === "user_provided") return `${formatInr(category.amount)} user provided`;
  return formatInr(category.amount);
}

function miscellaneousMode(category: CompleteBudgetCategory) {
  if (category.source === "versioned_contingency_assumption") return "Automatic estimate";
  if (category.source === "User input") return "Manual amount";
  if (
    category.status === "unavailable" &&
    category.assumptions.some((assumption) => /disabled/i.test(assumption))
  )
    return "Disabled";
  return "Not available";
}

function CompleteBudgetDetails({ budget }: { budget: CompleteTripBudget }) {
  const total = budget.total_estimate;
  const budgetLimit = budget.budget_limit;
  const overrun =
    typeof total === "number" && typeof budgetLimit === "number" ? total - budgetLimit : null;

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">Complete trip budget</h2>
          <p className="text-xs text-muted-foreground">
            Whole-journey estimate · {budget.currency}
          </p>
        </div>
        <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium capitalize">
          {budget.completeness}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-lg bg-muted/50 p-3">
          <p className="text-xs text-muted-foreground">Complete trip total</p>
          <p className="mt-1 text-xl font-semibold">
            {typeof total === "number" ? formatInr(total) : "Unavailable"}
          </p>
        </div>
        <div className="rounded-lg bg-muted/50 p-3">
          <p className="text-xs text-muted-foreground">Budget status</p>
          <p className="mt-1 text-sm font-semibold">
            {budget.within_budget === true
              ? "Within budget across estimated ranges"
              : budget.within_budget === false && overrun !== null
                ? `Over budget at the upper estimate by ${formatInr(Math.max(0, (budget.total_estimate_range_max ?? total ?? 0) - budgetLimit!))}`
                : "Feasibility cannot be fully determined"}
          </p>
        </div>
      </div>

      {overrun !== null && typeof budgetLimit === "number" && overrun > 0 && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
          <p>Representative estimate over budget by {formatInr(overrun)}.</p>
          {typeof budget.total_estimate_range_max === "number" &&
            typeof budgetLimit === "number" &&
            budget.total_estimate_range_max > budgetLimit && (
              <p className="mt-1">
                Upper-range estimate over budget by{" "}
                {formatInr(budget.total_estimate_range_max - budgetLimit)}.
              </p>
            )}
        </div>
      )}

      {typeof budget.total_estimate_range_min === "number" &&
        typeof budget.total_estimate_range_max === "number" && (
          <p className="text-xs text-muted-foreground">
            Indicative total range: {formatInr(budget.total_estimate_range_min)}–
            {formatInr(budget.total_estimate_range_max)}. Budget checks use upper estimate bounds.
          </p>
        )}

      {typeof total !== "number" && (
        <p className="rounded-lg bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-200">
          A complete total is unavailable because one or more category costs are unknown or partial.
          Unknown costs are not counted as zero.
        </p>
      )}

      <dl className="grid gap-2 rounded-lg border border-border p-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs text-muted-foreground">Known subtotal</dt>
          <dd className="font-medium">
            {subtotalLabel(budget.known_subtotal, "No verified or user-entered costs")}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Estimated subtotal</dt>
          <dd className="font-medium">
            {subtotalLabel(budget.estimated_subtotal, "No estimated category costs")}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Partial subtotal</dt>
          <dd className="font-medium">
            {subtotalLabel(budget.partial_subtotal, "No known partial amount")}
          </dd>
        </div>
      </dl>

      <div className="divide-y divide-border">
        {budget.categories.map((category) => (
          <details key={category.key} className="py-2.5">
            <summary className="flex cursor-pointer flex-wrap items-center justify-between gap-2 text-sm">
              <span className="font-medium">{category.label}</span>
              <span className="flex items-center gap-2">
                <span className="rounded-full bg-muted px-2 py-0.5 text-[11px]">
                  {statusLabel[category.status] ?? category.status}
                </span>
                <strong>{categoryAmountLabel(category)}</strong>
              </span>
            </summary>
            <div className="mt-2 space-y-1 text-xs text-muted-foreground">
              <p>Source: {category.source ?? "Unavailable"}</p>
              {category.key === "attraction_fees" && (
                <>
                  <p>
                    Verified fees:{" "}
                    {category.verified_count
                      ? typeof category.verified_amount === "number"
                        ? formatInr(category.verified_amount)
                        : "Unavailable"
                      : "No verified fees"}
                  </p>
                  <p>
                    Estimated fees:{" "}
                    {category.estimated_count
                      ? typeof category.estimated_amount === "number"
                        ? formatInr(category.estimated_amount)
                        : "Unavailable"
                      : "No estimated fees"}
                    {typeof category.estimated_count === "number"
                      ? ` · ${category.estimated_count} attraction(s) covered by estimates`
                      : ""}
                  </p>
                  <p>
                    Unresolved amount:{" "}
                    {category.unresolved_count === 0
                      ? "None (0 attractions)"
                      : `Unavailable · ${category.unresolved_count ?? "unknown count"} attraction(s)`}
                  </p>
                  {typeof category.amount === "number" &&
                    typeof category.range_min === "number" &&
                    typeof category.range_max === "number" && (
                      <p>
                        Fee range: lower {formatInr(category.range_min)} · representative{" "}
                        {formatInr(category.amount)} · upper {formatInr(category.range_max)}
                      </p>
                    )}
                  {category.estimate_config_version && (
                    <p>Estimate configuration: {category.estimate_config_version}</p>
                  )}
                  {category.sources?.map((source) => (
                    <p key={source}>Fee provenance: {source}</p>
                  ))}
                </>
              )}
              {category.key === "miscellaneous" && (
                <>
                  <p>Mode: {miscellaneousMode(category)}</p>
                  {category.source === "versioned_contingency_assumption" &&
                  typeof category.amount === "number" &&
                  typeof category.range_min === "number" &&
                  typeof category.range_max === "number" ? (
                    <p>
                      Lower {formatInr(category.range_min)} · representative{" "}
                      {formatInr(category.amount)} · upper {formatInr(category.range_max)}
                    </p>
                  ) : null}
                  {category.estimate_config_version && (
                    <p>Estimate configuration: {category.estimate_config_version}</p>
                  )}
                </>
              )}
              {typeof category.range_min === "number" && typeof category.range_max === "number" && (
                <p>
                  Indicative range: {formatInr(category.range_min)}–{formatInr(category.range_max)}
                </p>
              )}
              {category.mode && <p>Mode: {category.mode.replaceAll("_", " ")}</p>}
              {category.unit_basis && <p>Rate basis: {category.unit_basis.replaceAll("_", " ")}</p>}
              {category.amount_basis && (
                <p>Amount basis: {category.amount_basis.replaceAll("_", " ")}</p>
              )}
              {category.traveler_count ? (
                <p>Traveler count used: {category.traveler_count}</p>
              ) : null}
              {typeof category.distance_km === "number" && (
                <p>
                  Modeled distance:{" "}
                  {category.distance_km.toLocaleString("en-IN", { maximumFractionDigits: 1 })} km
                </p>
              )}
              {category.estimated_at && (
                <p>Estimate created: {new Date(category.estimated_at).toLocaleString()}</p>
              )}
              {category.assumptions.map((assumption) => (
                <p key={assumption}>{assumption}</p>
              ))}
            </div>
          </details>
        ))}
      </div>

      <details className="rounded-lg border border-border p-3 text-xs text-muted-foreground">
        <summary className="cursor-pointer font-medium text-foreground">
          Assumptions and limitations
        </summary>
        <div className="mt-2 space-y-1">
          {budget.assumptions.map((assumption) => (
            <p key={assumption}>{assumption}</p>
          ))}
          {(budget.exclusions ?? []).map((exclusion) => (
            <p key={exclusion}>{exclusion}</p>
          ))}
        </div>
      </details>
    </>
  );
}

export function TripBudgetEstimatePanel({
  estimate,
  completeBudgetCurrent = true,
  estimateIsCurrent = true,
}: {
  estimate: TripBudgetEstimate | null | undefined;
  completeBudgetCurrent?: boolean;
  estimateIsCurrent?: boolean;
}) {
  const completeBudget = estimate?.complete_budget;
  if (estimate && (!estimateIsCurrent || (completeBudget && !completeBudgetCurrent))) {
    return (
      <section className="surface space-y-2 p-5" aria-label="Trip budget estimate">
        <h2 className="font-semibold">Trip budget needs refresh</h2>
        <p className="text-sm text-muted-foreground">
          Trip details changed after this estimate was created. Regenerate the itinerary to get a
          current complete-trip budget.
        </p>
      </section>
    );
  }
  if (completeBudget) {
    return (
      <section className="surface space-y-4 p-5" aria-label="Complete trip budget">
        <CompleteBudgetDetails budget={completeBudget} />
      </section>
    );
  }
  if (estimate) {
    return (
      <section className="surface space-y-3 p-5" aria-label="Legacy destination-only budget">
        <div>
          <h2 className="font-semibold">Destination-only estimate</h2>
          <p className="text-xs text-muted-foreground">
            Legacy estimate; intercity outbound and return travel are excluded.
          </p>
        </div>
        <p className="text-2xl font-semibold">
          {typeof estimate.total_estimated === "number"
            ? formatInr(estimate.total_estimated)
            : "Unavailable"}
        </p>
        <div className="divide-y divide-border">
          {estimate.categories.map((category) => (
            <p key={category.key} className="flex justify-between gap-3 py-2 text-sm">
              <span>{category.label}</span>
              <span>
                {typeof category.amount === "number" ? formatInr(category.amount) : "Unavailable"}
              </span>
            </p>
          ))}
        </div>
        {estimate.exclusions.map((exclusion) => (
          <p key={exclusion} className="text-xs text-muted-foreground">
            {exclusion}
          </p>
        ))}
      </section>
    );
  }
  return null;
}
