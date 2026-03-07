import Link from "next/link";
import { apiGet } from "@/lib/api";

type RunSummary = {
  run_id: string;
  run_dir: string;
  started_at?: string | null;
  ended_at?: string | null;
  dataset_name: string;
  dataset_spec_version: string;
  model_version: string;
  model_versions?: string[];
  pass_rate: number;
  failures_total: number;
  items_total: number;
  eval_passed: number;
  artifacts_dir?: string;
};

type FilesResponse = {
  content: {
    run_id: string;
    run_dir: string;
    root_files: string[];
    artifact_files: string[];
  };
};

type EventsResponse = {
  content: {
    run_id: string;
    events: Array<{
      ts: string;
      run_id: string;
      stage: string;
      status: string;
      item_id: string;
      failure_code: string;
      message: string;
      ref?: unknown;
    }>;
    total: number;
  };
};

type ResultsResponse = {
  content: {
    run_id: string;
    results: Array<{
      item_id: string;
      verdict: string;
      score: number;
      error_type: string;
      evidence: unknown[];
      task_type: string;
      eval_method: string;
      model_version: string;
      created_at: string;
    }>;
    total: number;
  };
};

type ClustersResponse = {
  content: {
    run_id: string;
    clusters: Array<{
      error_type: string;
      count: number;
      sample_item_ids: string[];
      owner: string;
      recommended_action: string;
    }>;
    clusters_count: number;
  };
};

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;

  const [summary, files, events, results, clusters] = await Promise.all([
    apiGet<RunSummary>(`/runs/${runId}`),
    apiGet<FilesResponse>(`/runs/${runId}/files`),
    apiGet<EventsResponse>(`/runs/${runId}/events?limit=200`),
    apiGet<ResultsResponse>(`/runs/${runId}/results?limit=200`),
    apiGet<ClustersResponse>(`/runs/${runId}/clusters`),
  ]);

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100 p-8">
      <div className="mx-auto max-w-7xl space-y-8">
        <div>
          <Link href="/" className="text-sm text-neutral-400 underline">
            ← Back
          </Link>
          <h1 className="mt-3 text-3xl font-semibold">{runId}</h1>
          <p className="mt-2 text-neutral-400">
            {summary.dataset_name} · {summary.model_version}
          </p>
        </div>

        <section className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
          <h2 className="mb-4 text-xl font-medium">Summary</h2>
          <pre className="overflow-x-auto whitespace-pre-wrap text-sm">
{JSON.stringify(summary, null, 2)}
          </pre>
        </section>

        <section className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
          <h2 className="mb-4 text-xl font-medium">Failure Clusters</h2>
          {"error" in clusters ? (
            <p className="text-neutral-400">{String((clusters as { error?: { message?: string } }).error?.message ?? "Failed to load clusters")}</p>
          ) : clusters.content.clusters.length === 0 ? (
            <p className="text-neutral-400">No failure clusters for this run.</p>
          ) : (
            <div className="space-y-4">
              {clusters.content.clusters.map((cluster) => (
                <div key={cluster.error_type} className="rounded-xl border border-neutral-800 p-4">
                  <div className="font-medium">{cluster.error_type}</div>
                  <div className="mt-1 text-sm text-neutral-400">
                    count={cluster.count} · owner={cluster.owner}
                  </div>
                  <div className="mt-2 text-sm">{cluster.recommended_action}</div>
                  {cluster.sample_item_ids.length > 0 && (
                    <div className="mt-3 text-sm">
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
        </section>

        <section className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
          <h2 className="mb-4 text-xl font-medium">Results</h2>
          <div className="space-y-3">
            {"error" in results ? (
              <p className="text-neutral-400">{String((results as { error?: { message?: string } }).error?.message ?? "Failed to load results")}</p>
            ) : (
              results.content.results.map((result) => (
              <Link
                key={result.item_id}
                href={`/run/${runId}/item/${result.item_id}`}
                className="block rounded-xl border border-neutral-800 p-4 transition hover:bg-neutral-800/40"
              >
                <div className="font-medium">{result.item_id}</div>
                <div className="mt-1 text-sm text-neutral-400">
                  {result.task_type} · {result.eval_method}
                </div>
                <div className="mt-1 text-sm">
                  verdict={result.verdict} · score={result.score} · error_type={result.error_type || "(none)"}
                </div>
              </Link>
            ))
            )}
          </div>
        </section>

        <section className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
          <h2 className="mb-4 text-xl font-medium">Files</h2>
          <pre className="overflow-x-auto whitespace-pre-wrap text-sm">
            {"content" in files ? JSON.stringify(files.content, null, 2) : JSON.stringify(files, null, 2)}
          </pre>
        </section>

        <section className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
          <h2 className="mb-4 text-xl font-medium">Events</h2>
          <pre className="overflow-x-auto whitespace-pre-wrap text-sm">
            {"content" in events ? JSON.stringify(events.content.events, null, 2) : JSON.stringify(events, null, 2)}
          </pre>
        </section>
      </div>
    </main>
  );
}
