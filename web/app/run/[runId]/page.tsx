import Link from "next/link";
import { apiGet } from "@/lib/api";
import { GateBanner, JsonBlock, SectionCard, StatCard, StatusBadge } from "@/components/run-primitives";
import { PipelineStrip } from "@/components/pipeline-strip";
import {
  buildReleaseDecision,
  buildStageRows,
  formatMs,
  formatPassRate,
  getRunStatus,
  type ClusterRow,
  type EventRow,
  type ResultRow,
  type RunSummaryRow,
} from "@/lib/run-view";

/** Raw run summary from API (run_summary.json or run_record.json); may lack RunSummaryRow fields. */
type RunSummaryRaw = Record<string, unknown> & {
  run_id?: string;
  run_dir?: string;
  dataset_name?: string;
  dataset_spec_version?: string;
  model_version?: string;
  model_versions?: string[];
  started_at?: string | null;
  ended_at?: string | null;
  counts?: { items_total?: number; eval_passed?: number; eval_failed?: number; qa_passed_evaluated?: number };
  metrics?: { items_total?: number; eval_passed?: number; failures_total?: number };
  artifacts_dir?: string;
  tool_snapshot_hash?: string;
  seed?: number;
};

/** Normalize API response + events/results into RunSummaryRow and detect blocked-before-execution. */
function normalizeRunSummary(
  runId: string,
  summaryRaw: RunSummaryRaw,
  events: EventRow[],
  results: ResultRow[],
): { summary: RunSummaryRow; blockedPreExecution: boolean } {
  const counts = summaryRaw.counts ?? {};
  const metrics = summaryRaw.metrics ?? {};
  let items_total =
    (typeof summaryRaw.items_total === "number" ? summaryRaw.items_total : undefined) ??
    counts.items_total ??
    metrics.items_total ??
    0;
  let eval_passed =
    (typeof summaryRaw.eval_passed === "number" ? summaryRaw.eval_passed : undefined) ??
    counts.eval_passed ??
    metrics.eval_passed ??
    0;
  let failures_total =
    (typeof summaryRaw.failures_total === "number" ? summaryRaw.failures_total : undefined) ??
    metrics.failures_total ??
    counts.eval_failed ??
    0;

  if (results.length > 0) {
    items_total = results.length;
    eval_passed = results.filter((r) => r.verdict === "pass").length;
    failures_total = items_total - eval_passed;
  } else if (events.length > 0) {
    const generateStarts = events.filter((e) => e.stage === "GENERATE_ITEM" && e.status === "start").length;
    const qaFails = events.filter((e) => e.stage === "QA_GATE" && e.status === "fail").length;
    const runModelStarts = events.filter((e) => e.stage === "RUN_MODEL" && e.status === "start").length;
    if (items_total === 0 && generateStarts > 0) {
      items_total = generateStarts;
      eval_passed = 0;
      failures_total = qaFails > 0 ? qaFails : runModelStarts === 0 ? items_total : 0;
    }
  }

  const pass_rate = items_total > 0 ? eval_passed / items_total : 0;

  const hasQaFail = events.some((e) => e.stage === "QA_GATE" && e.status === "fail");
  const hasRunModel = events.some((e) => e.stage === "RUN_MODEL");
  const hasVerify = events.some((e) => e.stage === "VERIFY");
  const blockedPreExecution = hasQaFail && !hasRunModel && !hasVerify;

  const sortedTs = events.map((e) => e.ts).filter(Boolean).sort();
  const started_at = summaryRaw.started_at ?? (sortedTs[0] ?? null);
  const ended_at = summaryRaw.ended_at ?? (sortedTs[sortedTs.length - 1] ?? null);

  const summary: RunSummaryRow = {
    run_id: runId,
    run_dir: String(summaryRaw.run_dir ?? ""),
    dataset_name: String(summaryRaw.dataset_name ?? ""),
    dataset_spec_version: String(summaryRaw.dataset_spec_version ?? ""),
    model_version: String(summaryRaw.model_version ?? (summaryRaw.model_versions as string[])?.[0] ?? ""),
    started_at: started_at ?? null,
    ended_at: ended_at ?? null,
    items_total,
    eval_passed,
    failures_total,
    pass_rate,
  };
  return { summary, blockedPreExecution };
}

type EventsResponse = {
  content: {
    run_id: string;
    events: EventRow[];
    total: number;
  };
};

type ResultsResponse = {
  content: {
    run_id: string;
    results: ResultRow[];
    total: number;
  };
};

type ClustersResponse = {
  content: {
    run_id: string;
    clusters: ClusterRow[];
    clusters_count: number;
  };
};

type RunsResponse = {
  runs: RunSummaryRow[];
};

const TABS = ["overview", "pipeline", "items", "release"] as const;
type Tab = (typeof TABS)[number];

function tabHref(runId: string, tab: Tab) {
  return `/run/${runId}?tab=${tab}`;
}

export default async function RunDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ runId: string }>;
  searchParams?: Promise<{ tab?: string }>;
}) {
  const { runId } = await params;
  const sp = (await searchParams) ?? {};
  const activeTab: Tab = TABS.includes((sp.tab as Tab) ?? "overview")
    ? ((sp.tab as Tab) ?? "overview")
    : "overview";

  const [summaryRaw, eventsRes, resultsRes, clustersRes, runsRes] = await Promise.all([
    apiGet(`/runs/${runId}`) as Promise<RunSummaryRaw>,
    apiGet(`/runs/${runId}/events?limit=500`) as Promise<EventsResponse>,
    apiGet(`/runs/${runId}/results?limit=500`) as Promise<ResultsResponse>,
    apiGet(`/runs/${runId}/clusters`) as Promise<ClustersResponse>,
    apiGet(`/runs?limit=20`) as Promise<RunsResponse>,
  ]);

  const events = eventsRes.content?.events ?? [];
  const results = resultsRes.content?.results ?? [];
  const clusters = clustersRes.content?.clusters ?? [];
  const { summary: normalizedCurrentRun, blockedPreExecution } = normalizeRunSummary(
    runId,
    summaryRaw ?? {},
    events,
    results,
  );
  const stageRows = buildStageRows(events, results);
  const status = getRunStatus(normalizedCurrentRun, blockedPreExecution);

  const previousComparableRun =
    runsRes.runs.find(
      (r) =>
        r.run_id !== runId &&
        r.dataset_name === normalizedCurrentRun.dataset_name &&
        r.model_version === normalizedCurrentRun.model_version,
    ) ?? null;

  let previousClusters: ClusterRow[] = [];
  if (previousComparableRun) {
    try {
      const prevClustersRes = (await apiGet(
        `/runs/${previousComparableRun.run_id}/clusters`,
      )) as ClustersResponse;
      previousClusters = prevClustersRes.content?.clusters ?? [];
    } catch {
      previousClusters = [];
    }
  }

  const release = buildReleaseDecision({
    current: normalizedCurrentRun,
    currentClusters: clusters,
    previous: previousComparableRun,
    previousClusters,
  });

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100">
      <div className="mx-auto max-w-7xl px-6 py-8">
        <div className="mb-6 flex items-center justify-between gap-4">
          <div>
            <Link href="/" className="text-sm text-neutral-400 hover:text-neutral-200">
              ← Back
            </Link>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white">
              Mission Control
            </h1>
            <div className="mt-2 text-sm text-neutral-400">
              {normalizedCurrentRun.dataset_name || "—"} · {normalizedCurrentRun.model_version || "—"}
            </div>
            <div className="mt-1 font-mono text-xs text-neutral-500">{runId}</div>
          </div>
          <StatusBadge status={status} />
        </div>

        <div className="mb-8 grid gap-4 md:grid-cols-4">
          <StatCard
            label="Pass rate"
            value={formatPassRate(normalizedCurrentRun.pass_rate ?? null)}
          />
          <StatCard
            label="Failures"
            value={String(normalizedCurrentRun.failures_total ?? 0)}
          />
          <StatCard label="Items" value={String(normalizedCurrentRun.items_total ?? 0)} />
          <StatCard
            label="Release gate"
            value={release.gate}
            hint={release.summary}
          />
        </div>

        <div className="mb-8 flex flex-wrap gap-2 rounded-2xl border border-neutral-800 bg-neutral-900/80 p-2">
          {TABS.map((tab) => (
            <Link
              key={tab}
              href={tabHref(runId, tab)}
              className={`rounded-xl px-4 py-2 text-sm capitalize ${
                activeTab === tab
                  ? "bg-white text-black"
                  : "text-neutral-300 hover:bg-neutral-950"
              }`}
            >
              {tab}
            </Link>
          ))}
        </div>

        {activeTab === "overview" && (
          <div className="space-y-6">
            <SectionCard title="Pipeline health">
              <PipelineStrip stages={stageRows} />
            </SectionCard>

            <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
              <SectionCard title="Top failure clusters">
                {clusters.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-neutral-800 p-6 text-neutral-400">
                    No failure clusters for this run.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {clusters.map((cluster) => (
                      <div
                        key={cluster.error_type}
                        className="rounded-2xl border border-neutral-800 bg-neutral-950/70 p-4"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-medium text-white">{cluster.error_type}</div>
                          <div className="text-sm text-neutral-400">count={cluster.count}</div>
                        </div>
                        <div className="mt-2 text-sm text-neutral-400">
                          owner={cluster.owner}
                        </div>
                        <div className="mt-3 text-sm text-neutral-200">
                          {cluster.recommended_action}
                        </div>
                        {cluster.sample_item_ids.length > 0 && (
                          <div className="mt-3 text-sm text-neutral-400">
                            Sample items:{" "}
                            {cluster.sample_item_ids.map((itemId, idx) => (
                              <span key={itemId}>
                                <Link className="underline" href={`/run/${runId}/item/${itemId}`}>
                                  {itemId}
                                </Link>
                                {idx < cluster.sample_item_ids.length - 1 ? ", " : ""}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </SectionCard>

              <SectionCard title="Run metadata">
                <div className="grid gap-3">
                  <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">
                      Model versions
                    </div>
                    <div className="mt-2 text-sm text-neutral-200">
                      {(summaryRaw.model_versions ?? [normalizedCurrentRun.model_version]).join(", ")}
                    </div>
                  </div>

                  <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">
                      Tool snapshot hash
                    </div>
                    <div className="mt-2 font-mono text-xs text-neutral-300">
                      {summaryRaw.tool_snapshot_hash ?? "—"}
                    </div>
                  </div>

                  <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">
                      Seed
                    </div>
                    <div className="mt-2 text-sm text-neutral-200">
                      {String(summaryRaw.seed ?? "—")}
                    </div>
                  </div>
                </div>
              </SectionCard>
            </div>
          </div>
        )}

        {activeTab === "pipeline" && (
          <div className="space-y-6">
            <SectionCard title="Agent pipeline">
              <PipelineStrip stages={stageRows} />
            </SectionCard>

            <SectionCard title="Raw stage events">
              <JsonBlock data={events} />
            </SectionCard>
          </div>
        )}

        {activeTab === "items" && (
          <SectionCard title="Item results">
            <div className="overflow-x-auto">
              <table className="min-w-full border-separate border-spacing-y-2 text-sm">
                <thead>
                  <tr className="text-left text-neutral-400">
                    <th className="px-3 py-2">Item</th>
                    <th className="px-3 py-2">Task</th>
                    <th className="px-3 py-2">Method</th>
                    <th className="px-3 py-2">Verdict</th>
                    <th className="px-3 py-2">Score</th>
                    <th className="px-3 py-2">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((result) => (
                    <tr key={result.item_id} className="rounded-2xl bg-neutral-900/70">
                      <td className="rounded-l-2xl px-3 py-3">
                        <Link className="underline" href={`/run/${runId}/item/${result.item_id}`}>
                          {result.item_id}
                        </Link>
                      </td>
                      <td className="px-3 py-3">{result.task_type}</td>
                      <td className="px-3 py-3">{result.eval_method}</td>
                      <td className="px-3 py-3">{result.verdict}</td>
                      <td className="px-3 py-3">{result.score}</td>
                      <td className="rounded-r-2xl px-3 py-3 text-neutral-400">
                        {result.error_type || "(none)"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </SectionCard>
        )}

        {activeTab === "release" && (
          <div className="space-y-6">
            <SectionCard title="Release decision">
              <GateBanner gate={release.gate} message={release.summary} />
              <div className="mt-5 grid gap-4 md:grid-cols-3">
                <StatCard
                  label="Pass rate delta"
                  value={
                    release.passRateDelta == null
                      ? "—"
                      : `${release.passRateDelta >= 0 ? "+" : ""}${(release.passRateDelta * 100).toFixed(1)} pts`
                  }
                />
                <StatCard label="Recovered clusters" value={String(release.recoveredClusters.length)} />
                <StatCard label="Introduced clusters" value={String(release.introducedClusters.length)} />
              </div>
            </SectionCard>

            <div className="grid gap-6 lg:grid-cols-2">
              <SectionCard title="Recovered clusters">
                {release.recoveredClusters.length === 0 ? (
                  <div className="text-neutral-400">None.</div>
                ) : (
                  <ul className="space-y-2 text-sm text-neutral-200">
                    {release.recoveredClusters.map((cluster) => (
                      <li key={cluster} className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-3">
                        {cluster}
                      </li>
                    ))}
                  </ul>
                )}
              </SectionCard>

              <SectionCard title="Introduced clusters">
                {release.introducedClusters.length === 0 ? (
                  <div className="text-neutral-400">None.</div>
                ) : (
                  <ul className="space-y-2 text-sm text-neutral-200">
                    {release.introducedClusters.map((cluster) => (
                      <li key={cluster} className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-3">
                        {cluster}
                      </li>
                    ))}
                  </ul>
                )}
              </SectionCard>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
