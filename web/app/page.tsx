"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { SectionCard, StatCard, StatusBadge } from "@/components/run-primitives";
import { API_BASE, apiGet, apiPost } from "@/lib/api";
import {
  formatPassRate,
  formatRunTime,
  getRunStatus,
  shortRunId,
  type RunSummaryRow,
} from "@/lib/run-view";

type RunsResponse = {
  runs: RunSummaryRow[];
};

type RunCreateResponse = {
  run_id: string;
  run_dir?: string;
  job_id?: string;
  metrics?: Record<string, unknown>;
};

type DemoCasesResponse = { cases: string[] };

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
  const [quota, setQuota] = useState(1);
  const [demoCase, setDemoCase] = useState<string>("wrong_email");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [latestRunId, setLatestRunId] = useState("");
  const [latestFailedCluster, setLatestFailedCluster] = useState<string | null>(null);
  const [demoCases, setDemoCases] = useState<Array<{ value: string; label: string }>>([
    { value: "wrong_email", label: "wrong_email" },
  ]);

  const loadDemoCases = useCallback(async () => {
    try {
      const data = await apiGet<DemoCasesResponse>("/demo/cases");
      if (Array.isArray(data.cases) && data.cases.length > 0) {
        setDemoCases(data.cases.map((c) => ({ value: c, label: c })));
        setDemoCase((prev) => (data.cases.includes(prev) ? prev : data.cases[0]));
      }
    } catch {
      // keep default demo cases on failure
    }
  }, []);

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
    loadDemoCases();
  }, [loadDemoCases]);

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
        quota,
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
      const res = await fetch(`${API_BASE}/demo/failure`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_name: demoCase }),
        cache: "no-store",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = typeof body.detail === "string" ? body.detail : body.message || res.statusText || "Demo run failed";
        setError(msg);
        return;
      }
      const runId = body.run_id;
      if (!runId) {
        setError("Server did not return a run_id");
        return;
      }
      setLatestRunId(runId);
      await loadRuns();
      router.push(`/run/${runId}`);
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
  const featuredRun = runs.find((r) => r.failures_total > 0) ?? runs[0] ?? null;

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100">
      <div className="mx-auto max-w-7xl px-6 py-10">
        <div className="mb-8">
          <div className="text-xs uppercase tracking-[0.2em] text-neutral-500">
            Schema-first evaluation control room
          </div>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-white">
            Evaluation Engine
          </h1>
          <p className="mt-3 max-w-3xl text-lg text-neutral-400">
            Trace every evaluation stage, inspect typed failures, and turn failure clusters into owned
            remediation work.
          </p>
        </div>

        <div className="mb-8 grid gap-4 md:grid-cols-4">
          <StatCard label="Recent runs" value={String(runs.length)} />
          <StatCard
            label="Latest pass rate"
            value={runs.length ? formatPassRate(runs[0].pass_rate) : "—"}
          />
          <StatCard
            label="Most recent failure"
            value={latestFailedCluster ?? (failedRunsCount > 0 ? "…" : "—")}
          />
          <StatCard
            label="Failed runs"
            value={String(failedRunsCount)}
            hint={failedRunsCount > 0 ? "Investigate in mission control" : "No recent failures"}
          />
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
          <SectionCard title="Launch a run">
            <div className="mb-5 flex gap-2 rounded-2xl border border-neutral-800 bg-neutral-950 p-1">
              <button
                onClick={() => setRunSectionMode("quick")}
                className={`flex-1 rounded-xl px-3 py-2 text-sm ${
                  runSectionMode === "quick"
                    ? "bg-white text-black"
                    : "text-neutral-300 hover:bg-neutral-900"
                }`}
              >
                Quick
              </button>
              <button
                onClick={() => setRunSectionMode("advanced")}
                className={`flex-1 rounded-xl px-3 py-2 text-sm ${
                  runSectionMode === "advanced"
                    ? "bg-white text-black"
                    : "text-neutral-300 hover:bg-neutral-900"
                }`}
              >
                Advanced
              </button>
            </div>

            {runSectionMode === "quick" ? (
              <div className="space-y-4">
                <div>
                  <label className="mb-2 block text-sm text-neutral-300">Failure demo case</label>
                  <select
                    value={demoCase}
                    onChange={(e) => setDemoCase(e.target.value)}
                    className="w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm"
                  >
                    {demoCases.map(({ value, label }) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex flex-wrap gap-3">
                  <button
                    onClick={handleFailureDemo}
                    disabled={loading}
                    className="rounded-xl bg-white px-4 py-2 text-black disabled:opacity-50"
                  >
                    {loading ? "Running..." : "Run Failure Demo"}
                  </button>

                  <button
                    onClick={handleRegression}
                    disabled={loading}
                    className="rounded-xl border border-neutral-700 px-4 py-2 text-neutral-100 disabled:opacity-50"
                  >
                    Run Golden Regression
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div>
                  <button
                    type="button"
                    onClick={() => setAdvancedOptionsOpen((o) => !o)}
                    className="text-sm text-neutral-400 underline hover:text-neutral-300"
                  >
                    {advancedOptionsOpen ? "▼" : "▶"} Advanced options
                  </button>

                  {advancedOptionsOpen && (
                    <div className="mt-3">
                      <label className="mb-2 block text-sm text-neutral-300">SUT URL</label>
                      <input
                        value={sutUrl}
                        onChange={(e) => setSutUrl(e.target.value)}
                        className="w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-sm"
                        placeholder="http://127.0.0.1:8000/run"
                      />
                    </div>
                  )}
                </div>

                <div>
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
                    className="w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm"
                  >
                    {SPEC_PRESETS.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
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
                      className="mt-3 h-48 w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-sm"
                    />
                  )}
                </div>

                <div>
                  <label className="mb-2 block text-sm text-neutral-300">Quota</label>
                  <input
                    type="number"
                    min={1}
                    max={500}
                    value={quota}
                    onChange={(e) => setQuota(Number(e.target.value) || 1)}
                    className="w-32 rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2"
                  />
                </div>

                <button
                  onClick={handleRunBatch}
                  disabled={loading}
                  className="rounded-xl bg-white px-4 py-2 text-black disabled:opacity-50"
                >
                  {loading ? "Running..." : "Run Custom Batch"}
                </button>
              </div>
            )}

            {latestRunId && (
              <p className="mt-4 text-sm text-emerald-400">
                Latest run:{" "}
                <Link className="underline" href={`/run/${latestRunId}`}>
                  {latestRunId}
                </Link>
              </p>
            )}

            {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
          </SectionCard>

          <div className="space-y-6">
            <SectionCard title="Featured run">
              {featuredRun ? (
                <Link
                  href={`/run/${featuredRun.run_id}`}
                  className="block rounded-2xl border border-neutral-800 bg-neutral-950/80 p-5 transition hover:border-neutral-700 hover:bg-neutral-950"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm text-neutral-400">{featuredRun.dataset_name}</div>
                      <div className="mt-1 font-mono text-sm text-neutral-200" title={featuredRun.run_id}>
                        {shortRunId(featuredRun.run_id)}
                      </div>
                    </div>
                    <StatusBadge status={getRunStatus(featuredRun)} />
                  </div>

                  <div className="mt-4 grid grid-cols-3 gap-3">
                    <StatCard label="Pass rate" value={formatPassRate(featuredRun.pass_rate)} />
                    <StatCard label="Failures" value={String(featuredRun.failures_total)} />
                    <StatCard
                      label="Updated"
                      value={formatRunTime(featuredRun.ended_at, featuredRun.started_at)}
                    />
                  </div>

                  <div className="mt-4 text-sm text-neutral-400">
                    Open mission control to inspect pipeline stages, item traces, and release status.
                  </div>
                </Link>
              ) : (
                <div className="rounded-2xl border border-dashed border-neutral-800 p-6 text-neutral-400">
                  No runs yet.
                </div>
              )}
            </SectionCard>

            <SectionCard title="Recent runs">
              <div className="space-y-3">
                {runs.slice(0, 8).map((run) => {
                  const status = getRunStatus(run);
                  return (
                    <Link
                      key={run.run_id}
                      href={`/run/${run.run_id}`}
                      className="block rounded-xl border border-neutral-800 bg-neutral-950/50 p-4 transition hover:bg-neutral-900"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="font-medium text-white" title={run.run_id}>
                            {shortRunId(run.run_id)}
                          </div>
                          <div className="mt-1 text-sm text-neutral-400">
                            {run.dataset_name} · {run.model_version}
                          </div>
                        </div>
                        <StatusBadge status={status} />
                      </div>

                      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-neutral-400">
                        <span>{formatPassRate(run.pass_rate)}</span>
                        <span>{run.failures_total} failures</span>
                        <span>{run.items_total} items</span>
                        <span>{formatRunTime(run.ended_at, run.started_at)}</span>
                      </div>
                    </Link>
                  );
                })}
              </div>
            </SectionCard>
          </div>
        </div>
      </div>
    </main>
  );
}
