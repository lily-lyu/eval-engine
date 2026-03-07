"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { API_BASE, apiGet, apiPost } from "@/lib/api";

type RunSummaryRow = {
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

type RunsResponse = {
  runs: RunSummaryRow[];
};

type RunCreateResponse = {
  run_id: string;
  run_dir?: string;
  job_id?: string;
  metrics?: Record<string, unknown>;
};

function formatPassRate(value: number | null | undefined) {
  if (value == null) return "—";
  return `${(value * 100).toFixed(value === 1 || value === 0 ? 0 : 1)}%`;
}

function getRunStatus(run: RunSummaryRow): "PASS" | "FAIL" | "PARTIAL" {
  if (run.failures_total === 0 && run.items_total > 0) return "PASS";
  if (run.eval_passed === 0 && run.failures_total > 0) return "FAIL";
  return "PARTIAL";
}

function shortRunId(runId: string): string {
  if (runId.length <= 24) return runId;
  return `${runId.slice(0, 12)}...${runId.slice(-8)}`;
}

function formatRunTime(endedAt: string | null, startedAt: string | null): string {
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
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

const DEMO_CASES = [
  { value: "wrong_email", label: "wrong_email" },
  { value: "wrong_sentiment", label: "wrong_sentiment" },
  { value: "wrong_math", label: "wrong_math" },
  { value: "traj_arg_bad", label: "traj_arg_bad" },
  { value: "traj_binding_mismatch", label: "traj_binding_mismatch" },
] as const;

const SMOKE_SPEC = {
  dataset_name: "mcp_smoke",
  dataset_spec_version: "1.0.0",
  allowed_domain_tags: ["extraction"],
  capability_targets: [
    {
      target_id: "t_email_easy",
      domain_tags: ["extraction"],
      difficulty: "easy",
      task_type: "json_extract_email",
      quota_weight: 1,
    },
  ],
  defaults: { max_prompt_length: 20000, max_retries_per_stage: 2, seed: 42 },
};

const WRONG_EMAIL_SPEC = {
  dataset_name: "demo_wrong_email",
  dataset_spec_version: "1.0.0",
  allowed_domain_tags: ["extraction"],
  capability_targets: [
    {
      target_id: "demo_wrong_email",
      domain_tags: ["extraction"],
      difficulty: "easy",
      task_type: "json_extract_email",
      quota_weight: 1,
    },
  ],
  defaults: { max_prompt_length: 20000, max_retries_per_stage: 2, seed: 42 },
};

const TRAJECTORY_ARG_BAD_SPEC = {
  dataset_name: "demo_trajectory_arg_bad",
  dataset_spec_version: "1.0.0",
  allowed_domain_tags: ["trajectory"],
  capability_targets: [
    {
      target_id: "demo_trajectory",
      domain_tags: ["trajectory"],
      difficulty: "easy",
      task_type: "trajectory_email_then_answer",
      quota_weight: 1,
    },
  ],
  defaults: { max_prompt_length: 20000, max_retries_per_stage: 2, seed: 42 },
};

const SPEC_PRESETS = [
  { value: "smoke", label: "Smoke test", spec: SMOKE_SPEC },
  { value: "wrong_email", label: "Wrong email demo", spec: WRONG_EMAIL_SPEC },
  { value: "trajectory_arg_bad", label: "Trajectory arg bad demo", spec: TRAJECTORY_ARG_BAD_SPEC },
  { value: "advanced", label: "Advanced (custom JSON)", spec: null },
] as const;

const DEFAULT_SPEC = JSON.stringify(SMOKE_SPEC, null, 2);

type ClustersResponse = {
  content?: { clusters: Array<{ error_type: string }> };
  error?: unknown;
};

export default function HomePage() {
  const router = useRouter();
  const [runs, setRuns] = useState<RunSummaryRow[]>([]);
  const [specJson, setSpecJson] = useState(DEFAULT_SPEC);
  const [specPreset, setSpecPreset] = useState<string>("smoke");
  const [advancedJsonOpen, setAdvancedJsonOpen] = useState(false);
  const [advancedOptionsOpen, setAdvancedOptionsOpen] = useState(false);
  const [runSectionMode, setRunSectionMode] = useState<"quick" | "advanced">("quick");
  const [sutUrl, setSutUrl] = useState(`${API_BASE}/sut/run`);
  const [demoCase, setDemoCase] = useState<string>("wrong_email");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [latestRunId, setLatestRunId] = useState("");
  const [latestFailedCluster, setLatestFailedCluster] = useState<string | null>(null);

  async function loadRuns() {
    try {
      const data = await apiGet<RunsResponse>("/runs?limit=8");
      setRuns(data.runs);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load runs");
    }
  }

  useEffect(() => {
    loadRuns();
  }, []);

  // Fetch latest failed cluster from most recent run that has failures
  useEffect(() => {
    const failedRun = runs.find((r) => r.failures_total > 0);
    if (!failedRun) {
      setLatestFailedCluster(null);
      return;
    }
    let cancelled = false;
    apiGet<ClustersResponse>(`/runs/${failedRun.run_id}/clusters`)
      .then((res) => {
        if (cancelled || !res.content?.clusters?.length) return;
        setLatestFailedCluster(res.content.clusters[0].error_type);
      })
      .catch(() => setLatestFailedCluster(null));
    return () => {
      cancelled = true;
    };
  }, [runs]);

  async function handleRunBatch() {
    setLoading(true);
    setError("");
    try {
      const res = await apiPost<RunCreateResponse>("/runs", {
        spec_json: specJson,
        quota: 1,
        sut: "http",
        sut_url: sutUrl,
        sut_timeout: 30,
        model_version: "http-sut-local",
      });
      setLatestRunId(res.run_id);
      await loadRuns();
      router.push(`/run/${res.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run batch");
    } finally {
      setLoading(false);
    }
  }

  async function handleFailureDemo() {
    setLoading(true);
    setError("");
    try {
      const res = await apiPost<RunCreateResponse>("/demo/failure", {
        case_name: demoCase,
      });
      setLatestRunId(res.run_id);
      await loadRuns();
      router.push(`/run/${res.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run failure demo");
    } finally {
      setLoading(false);
    }
  }

  async function handleRegression() {
    setLoading(true);
    setError("");
    try {
      const res = await apiPost<Record<string, unknown>>("/regression", {
        suite_path: "examples/golden_suite.jsonl",
        sut_url: sutUrl,
        sut_timeout: 30,
        min_pass_rate: 0.95,
      });
      alert(`Regression finished: ${JSON.stringify(res, null, 2)}`);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run regression");
    } finally {
      setLoading(false);
    }
  }

  const failedRunsCount = runs.filter((r) => r.failures_total > 0).length;

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100 p-8">
      <div className="mx-auto max-w-7xl space-y-8">
        <div>
          <h1 className="text-3xl font-semibold">Evaluation Engine</h1>
          <p className="mt-2 text-neutral-400">
            Run automated evaluations, inspect failures, and convert them into actionable remediation plans.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
            <div className="text-sm text-neutral-400">Recent runs</div>
            <div className="mt-1 text-2xl font-semibold">{runs.length}</div>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
            <div className="text-sm text-neutral-400">Latest run pass rate</div>
            <div className="mt-1 text-2xl font-semibold">
              {runs.length ? formatPassRate(runs[0].pass_rate) : "—"}
            </div>
          </div>
          <div className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
            <div className="text-sm text-neutral-400">Most recent failure type</div>
            <div className="mt-1 text-2xl font-semibold">
              {latestFailedCluster ?? (failedRunsCount > 0 ? "…" : "—")}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <section className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
            <h2 className="mb-4 text-xl font-medium">Start a Run</h2>

            <div className="mb-4">
              <button
                type="button"
                onClick={() => setAdvancedOptionsOpen((o) => !o)}
                className="text-sm text-neutral-400 underline hover:text-neutral-300"
              >
                {advancedOptionsOpen ? "▼" : "▶"} Advanced options
              </button>
              {advancedOptionsOpen && (
                <div className="mt-2">
                  <label className="mb-1 block text-sm text-neutral-300">SUT URL</label>
                  <input
                    value={sutUrl}
                    onChange={(e) => setSutUrl(e.target.value)}
                    className="w-full rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-sm"
                    placeholder="http://127.0.0.1:8000/run"
                  />
                </div>
              )}
            </div>

            <label className="mb-2 block text-sm text-neutral-300">Dataset spec</label>
            <select
              value={specPreset}
              onChange={(e) => {
                const v = e.target.value;
                setSpecPreset(v);
                const preset = SPEC_PRESETS.find((p) => p.value === v);
                if (preset?.spec) setSpecJson(JSON.stringify(preset.spec, null, 2));
                if (v === "advanced") setAdvancedJsonOpen(true);
              }}
              className="mb-3 w-full rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2 text-neutral-100"
            >
              {SPEC_PRESETS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>

            <div className="mb-4">
              <button
                type="button"
                onClick={() => setAdvancedJsonOpen((o) => !o)}
                className="text-sm text-neutral-400 underline hover:text-neutral-300"
              >
                {advancedJsonOpen ? "▼" : "▶"} Advanced JSON
              </button>
              {advancedJsonOpen && (
                <textarea
                  value={specJson}
                  onChange={(e) => {
                    setSpecJson(e.target.value);
                    setSpecPreset("advanced");
                  }}
                  className="mt-2 h-48 w-full rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-sm"
                />
              )}
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                onClick={handleFailureDemo}
                disabled={loading}
                className="rounded-xl bg-white px-4 py-2 text-black disabled:opacity-50"
              >
                {loading ? "Running..." : "Run Failure Demo"}
              </button>
              <button
                onClick={handleRunBatch}
                disabled={loading}
                className="rounded-xl border border-neutral-700 px-4 py-2 disabled:opacity-50"
              >
                {loading ? "Running..." : "Run Custom Batch"}
              </button>
              <button
                onClick={handleRegression}
                disabled={loading}
                className="rounded-xl border border-neutral-700 px-4 py-2 disabled:opacity-50"
              >
                Run Golden Regression
              </button>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <label className="text-sm text-neutral-300">Failure demo case:</label>
              <select
                value={demoCase}
                onChange={(e) => setDemoCase(e.target.value)}
                className="rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm text-neutral-100"
              >
                {DEMO_CASES.map(({ value, label }) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            {latestRunId && (
              <p className="mt-4 text-sm text-emerald-400">
                Latest run:{" "}
                <Link className="underline" href={`/run/${latestRunId}`}>
                  {latestRunId}
                </Link>
              </p>
            )}

            {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
          </section>

          <section className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
            <h2 className="mb-4 text-xl font-medium">Recent Runs</h2>
            <div className="space-y-3">
              {runs.slice(0, 8).map((run) => {
                const status = getRunStatus(run);
                const badgeClass =
                  status === "PASS"
                    ? "bg-emerald-500/20 text-emerald-400 border-emerald-500/40"
                    : status === "FAIL"
                      ? "bg-red-500/20 text-red-400 border-red-500/40"
                      : "bg-amber-500/20 text-amber-400 border-amber-500/40";
                return (
                  <Link
                    key={run.run_id}
                    href={`/run/${run.run_id}`}
                    className="block rounded-xl border border-neutral-800 p-4 transition hover:bg-neutral-800/40"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium" title={run.run_id}>
                        {shortRunId(run.run_id)}
                      </span>
                      <span className={`rounded px-2 py-0.5 text-xs font-medium border ${badgeClass}`}>
                        {status}
                      </span>
                    </div>
                    <div className="mt-1 text-sm text-neutral-400">
                      {run.dataset_name} · {run.model_version}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0 text-sm text-neutral-400">
                      <span>
                        {formatPassRate(run.pass_rate)} · {run.failures_total} failures · {run.items_total} items
                      </span>
                      <span className="text-neutral-500">
                        {formatRunTime(run.ended_at, run.started_at)}
                      </span>
                    </div>
                  </Link>
                );
              })}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}
