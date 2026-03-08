export type RunSummaryRow = {
  run_id: string;
  run_dir: string;
  dataset_name: string;
  dataset_spec_version: string;
  model_version: string;
  started_at: string | null;
  ended_at: string | null;
  items_total: number;
  eval_passed: number;
  failures_total: number;
  pass_rate: number;
};

export type EventRow = {
  ts: string;
  run_id: string;
  stage: string;
  status: "start" | "ok" | "fail";
  item_id: string;
  failure_code: string;
  message: string;
  ref?: Record<string, unknown>;
};

export type ResultRow = {
  item_id: string;
  verdict: "pass" | "fail";
  score: number;
  error_type: string;
  evidence: unknown[];
  task_type: string;
  eval_method: string;
  model_version: string;
  created_at: string;
};

export type ClusterRow = {
  error_type: string;
  count: number;
  sample_item_ids: string[];
  owner: string;
  recommended_action: string;
};

export function formatPassRate(value: number | null | undefined) {
  if (value == null) return "—";
  return `${(value * 100).toFixed(value === 1 || value === 0 ? 0 : 1)}%`;
}

export type RunStatus = "PASS" | "FAIL" | "PARTIAL" | "WATCH" | "BLOCKED";

export function getRunStatus(
  run: Pick<RunSummaryRow, "failures_total" | "items_total" | "eval_passed">,
  blockedPreExecution?: boolean,
): RunStatus {
  if (blockedPreExecution) return "BLOCKED";
  if (run.items_total <= 0) return "FAIL";
  if (run.failures_total === 0 && run.items_total > 0) return "PASS";
  if (run.eval_passed === 0 && run.failures_total > 0) return "FAIL";
  return "PARTIAL";
}

export function shortRunId(runId: string): string {
  if (runId.length <= 24) return runId;
  return `${runId.slice(0, 12)}...${runId.slice(-8)}`;
}

export function formatRunTime(endedAt: string | null, startedAt: string | null): string {
  const raw = endedAt ?? startedAt;
  if (!raw) return "—";
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "—";

  const now = Date.now();
  const diffMs = now - date.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMs / 3_600_000);
  const diffDays = Math.floor(diffMs / 86_400_000);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins} min ago`;
  if (diffHours < 24) return `${diffHours} hr ago`;
  if (diffDays < 7) return `${diffDays} day ago`;

  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatMs(value: number | null | undefined) {
  if (value == null) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(2)} s`;
}

function safeTs(value: string): number | null {
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms;
}

function mostCommon(values: string[]): string | null {
  const counts = new Map<string, number>();
  for (const value of values) {
    if (!value) continue;
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }
  let best: string | null = null;
  let bestCount = -1;
  for (const [key, count] of counts) {
    if (count > bestCount) {
      best = key;
      bestCount = count;
    }
  }
  return best;
}

export type StageRow = {
  agent: string;
  stage: string;
  label: string;
  inputCount: number;
  okCount: number;
  failCount: number;
  avgLatencyMs: number | null;
  topFailureCode: string | null;
};

const RUN_LEVEL_STAGES = new Set([
  "INIT",
  "PLAN",
  "DIAGNOSE",
  "DATA_REQUESTS",
  "PACKAGE",
  "END",
]);

const STAGE_META: Array<{ agent: string; stage: string; label: string }> = [
  { agent: "A0", stage: "INIT", label: "Initialize" },
  { agent: "A0", stage: "PLAN", label: "Plan batch" },
  { agent: "A1", stage: "GENERATE_ITEM", label: "Generate item" },
  { agent: "A1b", stage: "BUILD_ORACLE", label: "Build oracle" },
  { agent: "A4", stage: "QA_GATE", label: "QA gate" },
  { agent: "SUT", stage: "RUN_MODEL", label: "Run model" },
  { agent: "A2", stage: "VERIFY", label: "Verify" },
  { agent: "A3", stage: "DIAGNOSE", label: "Diagnose" },
  { agent: "A6", stage: "DATA_REQUESTS", label: "Data requests" },
  { agent: "A5", stage: "PACKAGE", label: "Package" },
];

export function buildStageRows(events: EventRow[], results: ResultRow[]): StageRow[] {
  const sorted = [...events].sort((a, b) => {
    const at = safeTs(a.ts) ?? 0;
    const bt = safeTs(b.ts) ?? 0;
    return at - bt;
  });

  const startTimestampsByStage = new Map<string, number[]>();
  const durationMap = new Map<string, number[]>();
  const okMap = new Map<string, number>();
  const failMap = new Map<string, number>();
  const failureCodesMap = new Map<string, string[]>();

  for (const event of sorted) {
    const t = safeTs(event.ts);

    if (event.status === "start" && t != null) {
      if (!startTimestampsByStage.has(event.stage)) startTimestampsByStage.set(event.stage, []);
      startTimestampsByStage.get(event.stage)!.push(t);
    }

    if (event.status === "ok" || event.status === "fail") {
      const starts = startTimestampsByStage.get(event.stage);
      if (t != null && starts && starts.length > 0) {
        const started = starts.shift()!;
        const duration = t - started;
        if (!durationMap.has(event.stage)) durationMap.set(event.stage, []);
        durationMap.get(event.stage)!.push(duration);
      }
      if (event.status === "ok") {
        okMap.set(event.stage, (okMap.get(event.stage) ?? 0) + 1);
      } else {
        failMap.set(event.stage, (failMap.get(event.stage) ?? 0) + 1);
        if (!failureCodesMap.has(event.stage)) failureCodesMap.set(event.stage, []);
        if (event.failure_code) failureCodesMap.get(event.stage)!.push(event.failure_code);
      }
    }
  }

  const hasDataRequestsEvents = events.some((e) => e.stage === "DATA_REQUESTS");

  const rows: StageRow[] = [];
  for (const { agent, stage, label } of STAGE_META) {
    if (stage === "DATA_REQUESTS" && !hasDataRequestsEvents) continue;

    const startCount = events.filter((e) => e.stage === stage && e.status === "start").length;
    const okCount = okMap.get(stage) ?? 0;
    const failCount = failMap.get(stage) ?? 0;

    let inputCount = startCount;
    if (RUN_LEVEL_STAGES.has(stage) && inputCount === 0 && (okCount > 0 || failCount > 0)) {
      inputCount = 1;
    }

    const durations = durationMap.get(stage) ?? [];
    const avgLatencyMs =
      durations.length > 0
        ? durations.reduce((sum, value) => sum + value, 0) / durations.length
        : null;

    const topFailureCode =
      mostCommon(failureCodesMap.get(stage) ?? []) ??
      (stage === "VERIFY" ? mostCommon(results.map((r) => r.error_type).filter(Boolean)) : null);

    rows.push({
      agent,
      stage,
      label,
      inputCount,
      okCount,
      failCount,
      avgLatencyMs,
      topFailureCode,
    });
  }
  return rows;
}

export type ReleaseDecision = {
  gate: "PASS" | "WATCH" | "BLOCKED";
  passRateDelta: number | null;
  recoveredClusters: string[];
  introducedClusters: string[];
  summary: string;
};

export function buildReleaseDecision(args: {
  current: RunSummaryRow;
  currentClusters: ClusterRow[];
  previous?: RunSummaryRow | null;
  previousClusters?: ClusterRow[];
}): ReleaseDecision {
  const { current, currentClusters, previous, previousClusters = [] } = args;

  if (current.items_total <= 0) {
    return {
      gate: "BLOCKED",
      passRateDelta: null,
      recoveredClusters: [],
      introducedClusters: currentClusters.map((c) => c.error_type),
      summary:
        "No evaluated items were produced in this run. Release decision is not allowed.",
    };
  }

  if (current.pass_rate <= 0) {
    const previousTypes = new Set(previousClusters.map((c) => c.error_type));
    const currentTypes = new Set(currentClusters.map((c) => c.error_type));
    const recoveredClusters = [...previousTypes].filter((x) => !currentTypes.has(x));
    const introducedClusters = [...currentTypes].filter((x) => !previousTypes.has(x));
    return {
      gate: "BLOCKED",
      passRateDelta: previous ? current.pass_rate - previous.pass_rate : null,
      recoveredClusters: previous ? recoveredClusters : [],
      introducedClusters: previous ? introducedClusters : currentClusters.map((c) => c.error_type),
      summary: "This run did not meet the release threshold.",
    };
  }

  if (!previous) {
    return {
      gate: current.failures_total === 0 ? "PASS" : "WATCH",
      passRateDelta: null as number | null,
      recoveredClusters: [] as string[],
      introducedClusters: currentClusters.map((c) => c.error_type),
      summary:
        current.failures_total === 0
          ? "No earlier comparable run found. Current run is clean."
          : "No earlier comparable run found. Review current failures before ship.",
    };
  }

  const previousTypes = new Set(previousClusters.map((c) => c.error_type));
  const currentTypes = new Set(currentClusters.map((c) => c.error_type));

  const recoveredClusters = [...previousTypes].filter((x) => !currentTypes.has(x));
  const introducedClusters = [...currentTypes].filter((x) => !previousTypes.has(x));
  const passRateDelta = current.pass_rate - previous.pass_rate;

  const gate =
    introducedClusters.length === 0 &&
    current.failures_total <= previous.failures_total &&
    current.pass_rate >= previous.pass_rate
      ? "PASS"
      : "BLOCKED";

  return {
    gate,
    passRateDelta,
    recoveredClusters,
    introducedClusters,
    summary:
      gate === "PASS"
        ? "Candidate is equal or better than the previous comparable run."
        : "Candidate introduces regressions or worsens failure profile versus the previous comparable run.",
  };
}
