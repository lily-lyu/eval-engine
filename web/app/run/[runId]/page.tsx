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

type RunSummary = RunSummaryRow & {
  model_versions?: string[];
  artifacts_dir?: string;
  tool_snapshot_hash?: string;
  seed?: number;
};

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

  const [summary, eventsRes, resultsRes, clustersRes, runsRes] = await Promise.all([
    apiGet(`/runs/${runId}`) as Promise<RunSummary>,
    apiGet(`/runs/${runId}/events?limit=500`) as Promise<EventsResponse>,
    apiGet(`/runs/${runId}/results?limit=500`) as Promise<ResultsResponse>,
    apiGet(`/runs/${runId}/clusters`) as Promise<ClustersResponse>,
    apiGet(`/runs?limit=20`) as Promise<RunsResponse>,
  ]);

  const events = eventsRes.content?.events ?? [];
  const results = resultsRes.content?.results ?? [];
  const clusters = clustersRes.content?.clusters ?? [];
  const stageRows = buildStageRows(events, results);
  const status = getRunStatus(summary);

  const previousComparableRun =
    runsRes.runs.find(
      (r) => r.run_id !== runId && r.dataset_name === summary.dataset_name && r.model_version === summary.model_version,
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
    current: summary,
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
              {summary.dataset_name} · {summary.model_version}
            </div>
            <div className="mt-1 font-mono text-xs text-neutral-500">{runId}</div>
          </div>
          <StatusBadge status={status} />
        </div>

        <div className="mb-8 grid gap-4 md:grid-cols-4">
          <StatCard label="Pass rate" value={formatPassRate(summary.pass_rate)} />
          <StatCard label="Failures" value={String(summary.failures_total)} />
          <StatCard label="Items" value={String(summary.items_total)} />
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
                      {(summary.model_versions ?? [summary.model_version]).join(", ")}
                    </div>
                  </div>

                  <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">
                      Tool snapshot hash
                    </div>
                    <div className="mt-2 font-mono text-xs text-neutral-300">
                      {summary.tool_snapshot_hash ?? "—"}
                    </div>
                  </div>

                  <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-4">
                    <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">
                      Seed
                    </div>
                    <div className="mt-2 text-sm text-neutral-200">{String(summary.seed ?? "—")}</div>
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
