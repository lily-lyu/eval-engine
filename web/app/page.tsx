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

// —— Quick: canned demos (case names from API; no spec picker) —————————————
// QUICK_DEMO_CASES: options for "Failure demo case" dropdown; labels populated from API or fallback.
const QUICK_DEMO_CASES_FALLBACK = [
  { value: "wrong_email", label: "wrong_email" },
];

// —— Advanced: neutral dataset templates for real runs (no demo wording) —————
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

const EMAIL_EXTRACTION_TEMPLATE = {
  dataset_name: "email_extraction",
  dataset_spec_version: "1.0.0",
  allowed_domain_tags: ["extraction"],
  capability_targets: [
    {
      target_id: "email_extraction_easy",
      domain_tags: ["extraction"],
      difficulty: "easy",
      task_type: "json_extract_email",
      quota_weight: 1,
    },
  ],
  defaults: { max_prompt_length: 20000, max_retries_per_stage: 2, seed: 42 },
};

const TRAJECTORY_TEMPLATE = {
  dataset_name: "trajectory_tool_use",
  dataset_spec_version: "1.0.0",
  allowed_domain_tags: ["trajectory"],
  capability_targets: [
    {
      target_id: "trajectory_email_answer",
      domain_tags: ["trajectory"],
      difficulty: "easy",
      task_type: "trajectory_email_then_answer",
      quota_weight: 1,
    },
  ],
  defaults: { max_prompt_length: 20000, max_retries_per_stage: 2, seed: 42 },
};

const ADVANCED_SPEC_PRESETS = [
  { value: "smoke_template", label: "Smoke test template", spec: SMOKE_SPEC },
  { value: "email_template", label: "Email extraction template", spec: EMAIL_EXTRACTION_TEMPLATE },
  { value: "trajectory_template", label: "Trajectory tool-use template", spec: TRAJECTORY_TEMPLATE },
  { value: "custom", label: "Custom JSON", spec: null },
] as const;

const DEFAULT_SPEC = JSON.stringify(SMOKE_SPEC, null, 2);

// —— Intent mode: high-level intent -> compiled plan —————————————————————
const DEFAULT_INTENT_SPEC = {
  intent_name: "extraction_and_trajectory",
  intent_spec_version: "1.0.0",
  evaluation_goal: "Evaluate email extraction and trajectory tool-use capability.",
  target_domain: ["extraction", "trajectory"],
  capability_focus: ["extraction", "trajectory"],
  batch_size: 4,
  defaults: { seed: 42, max_prompt_length: 20000, max_retries_per_stage: 2 },
};
const DEFAULT_INTENT_JSON = JSON.stringify(DEFAULT_INTENT_SPEC, null, 2);

type ClustersResponse = {
  content?: { clusters: Array<{ error_type: string }> };
  error?: unknown;
};

type PlannerStatusResponse = {
  planner_mode: string;
  gemini_configured: boolean;
};

export default function HomePage() {
  const router = useRouter();
  const [runs, setRuns] = useState<RunSummaryRow[]>([]);
  const [specJson, setSpecJson] = useState(DEFAULT_SPEC);
  const [specPreset, setSpecPreset] = useState<string>("smoke_template");
  const [advancedJsonOpen, setAdvancedJsonOpen] = useState(false);
  const [advancedMode, setAdvancedMode] = useState<"custom_json" | "intent">("custom_json");
  const [intentJson, setIntentJson] = useState(DEFAULT_INTENT_JSON);
  const [compilePreview, setCompilePreview] = useState<Record<string, unknown> | null>(null);
  const [compileError, setCompileError] = useState("");
  const [runtimeOptionsOpen, setRuntimeOptionsOpen] = useState(false);
  const [runSectionMode, setRunSectionMode] = useState<"quick" | "advanced">("quick");
  const [sutUrl, setSutUrl] = useState(`${API_BASE}/sut/run`);
  const [quota, setQuota] = useState(1);
  const [demoCase, setDemoCase] = useState<string>("wrong_email");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [latestRunId, setLatestRunId] = useState("");
  const [latestFailedCluster, setLatestFailedCluster] = useState<string | null>(null);
  const [demoCases, setDemoCases] = useState<Array<{ value: string; label: string }>>(QUICK_DEMO_CASES_FALLBACK);
  const [plannerMode, setPlannerMode] = useState<string>("deterministic");
  const [plannerModel, setPlannerModel] = useState("");
  const [plannerTemperature, setPlannerTemperature] = useState<number | "">("");
  const [showRawPlannerOutputs, setShowRawPlannerOutputs] = useState(false);
  const [plannerStatus, setPlannerStatus] = useState<PlannerStatusResponse | null>(null);

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

  useEffect(() => {
    apiGet<PlannerStatusResponse>("/planner-status")
      .then(setPlannerStatus)
      .catch(() => setPlannerStatus(null));
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
      const body: Record<string, unknown> = {
        quota,
        sut: "http",
        sut_url: sutUrl,
        sut_timeout: 30,
        model_version: "http-sut-local",
      };
      if (advancedMode === "intent") {
        body.intent_json = intentJson;
        body.planner_mode = plannerMode;
        if (plannerModel) body.planner_model = plannerModel;
        if (plannerTemperature !== "") body.planner_temperature = Number(plannerTemperature);
        body.save_raw_planner_outputs = showRawPlannerOutputs;
      } else {
        body.spec_json = specJson;
      }
      const res = await apiPost<RunCreateResponse>("/runs", body);
      setLatestRunId(res.run_id);
      await loadRuns();
      router.push(`/run/${res.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run batch");
    } finally {
      setLoading(false);
    }
  }

  async function handleCompilePreview() {
    setCompileError("");
    setCompilePreview(null);
    try {
      const body: Record<string, unknown> = {
        intent_json: intentJson,
        planner_mode: plannerMode,
        save_raw_planner_outputs: showRawPlannerOutputs,
      };
      if (plannerModel) body.planner_model = plannerModel;
      if (plannerTemperature !== "") body.planner_temperature = Number(plannerTemperature);
      const res = await apiPost<Record<string, unknown>>("/compile", body);
      setCompilePreview(res);
    } catch (err) {
      setCompileError(err instanceof Error ? err.message : "Compile failed");
    }
  }

  const geminiUnavailable = Boolean(
    plannerStatus &&
      !plannerStatus.gemini_configured &&
      (plannerMode === "llm" || plannerMode === "hybrid")
  );

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
                <p className="text-sm text-neutral-400">
                  One-click canned runs for validating the pipeline and showing failure handling.
                </p>
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
                <p className="text-sm text-neutral-400">
                  Configure a real batch run against your SUT using a template or custom dataset JSON.
                </p>

                <div>
                  <label className="mb-2 block text-sm text-neutral-300">SUT URL</label>
                  <input
                    value={sutUrl}
                    onChange={(e) => setSutUrl(e.target.value)}
                    className="w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-sm"
                    placeholder="http://127.0.0.1:8000/sut/run"
                  />
                </div>

                <div>
                  <label className="mb-2 block text-sm text-neutral-300">Advanced input</label>
                  <div className="mb-2 flex gap-2 rounded-2xl border border-neutral-800 bg-neutral-950 p-1">
                    <button
                      type="button"
                      onClick={() => setAdvancedMode("custom_json")}
                      className={`flex-1 rounded-xl px-3 py-2 text-sm ${
                        advancedMode === "custom_json"
                          ? "bg-white text-black"
                          : "text-neutral-400 hover:bg-neutral-900"
                      }`}
                    >
                      Custom JSON
                    </button>
                    <button
                      type="button"
                      onClick={() => setAdvancedMode("intent")}
                      className={`flex-1 rounded-xl px-3 py-2 text-sm ${
                        advancedMode === "intent"
                          ? "bg-white text-black"
                          : "text-neutral-400 hover:bg-neutral-900"
                      }`}
                    >
                      Intent
                    </button>
                  </div>
                </div>

                {advancedMode === "custom_json" ? (
                  <>
                    <div>
                      <label className="mb-2 block text-sm text-neutral-300">Dataset template</label>
                      <select
                        value={specPreset}
                        onChange={(e) => {
                          const v = e.target.value;
                          setSpecPreset(v);
                          const preset = ADVANCED_SPEC_PRESETS.find((p) => p.value === v);
                          if (preset?.spec) setSpecJson(JSON.stringify(preset.spec, null, 2));
                          if (v === "custom") setAdvancedJsonOpen(true);
                        }}
                        className="w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm"
                      >
                        {ADVANCED_SPEC_PRESETS.map((p) => (
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
                        {advancedJsonOpen ? "▼" : "▶"} Custom JSON
                      </button>
                      {advancedJsonOpen && (
                        <textarea
                          value={specJson}
                          onChange={(e) => {
                            setSpecJson(e.target.value);
                            setSpecPreset("custom");
                          }}
                          className="mt-3 h-48 w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-sm"
                        />
                      )}
                    </div>
                  </>
                ) : (
                  <>
                    <p className="text-sm text-neutral-400">
                      System-level intent: capability_focus (e.g. extraction, trajectory) is compiled into eval families and then into dataset_spec.
                    </p>
                    <div className="mt-3 space-y-3">
                      <div>
                        <label className="mb-1 block text-sm text-neutral-300">Planner mode</label>
                        <select
                          value={plannerMode}
                          onChange={(e) => setPlannerMode(e.target.value)}
                          className="w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm"
                        >
                          <option value="deterministic">Deterministic (catalog only)</option>
                          <option value="llm">LLM (Gemini)</option>
                          <option value="hybrid">Hybrid (Gemini + normalize)</option>
                        </select>
                      </div>
                      {(plannerMode === "llm" || plannerMode === "hybrid") && (
                        <>
                          <div>
                            <label className="mb-1 block text-sm text-neutral-300">Model (optional)</label>
                            <input
                              type="text"
                              value={plannerModel}
                              onChange={(e) => setPlannerModel(e.target.value)}
                              placeholder="e.g. gemini-2.0-flash"
                              className="w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm font-mono"
                            />
                          </div>
                          <div>
                            <label className="mb-1 block text-sm text-neutral-300">Temperature (optional)</label>
                            <input
                              type="number"
                              min={0}
                              max={2}
                              step={0.1}
                              value={plannerTemperature === "" ? "" : plannerTemperature}
                              onChange={(e) =>
                                setPlannerTemperature(e.target.value === "" ? "" : Number(e.target.value))
                              }
                              placeholder="0.2"
                              className="w-32 rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm"
                            />
                          </div>
                          {geminiUnavailable && (
                            <p className="text-sm text-amber-400">
                              Gemini planner is not configured on the backend (missing GEMINI_API_KEY). Use deterministic mode or set GEMINI_API_KEY on the server.
                            </p>
                          )}
                        </>
                      )}
                      <label className="flex items-center gap-2 text-sm text-neutral-400">
                        <input
                          type="checkbox"
                          checked={showRawPlannerOutputs}
                          onChange={(e) => setShowRawPlannerOutputs(e.target.checked)}
                          className="rounded border-neutral-700"
                        />
                        Show raw planner outputs (when available)
                      </label>
                    </div>
                    <textarea
                      value={intentJson}
                      onChange={(e) => setIntentJson(e.target.value)}
                      className="mt-2 h-48 w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-sm"
                      placeholder={DEFAULT_INTENT_JSON}
                    />
                    <div className="mt-2 flex gap-2">
                      <button
                        type="button"
                        onClick={handleCompilePreview}
                        disabled={geminiUnavailable}
                        className="rounded-xl border border-neutral-700 px-3 py-2 text-sm text-neutral-200 disabled:opacity-50"
                      >
                        Preview compile
                      </button>
                      {compileError && (
                        <span className="self-center text-sm text-red-400">{compileError}</span>
                      )}
                    </div>
                    {compilePreview && (
                      <div className="mt-3 rounded-xl border border-neutral-700 bg-neutral-900/50 p-3">
                        <div className="mb-2 text-sm font-medium text-neutral-300">
                          Compiled plan (preview)
                        </div>
                        <pre className="max-h-64 overflow-auto text-xs text-neutral-400">
                          {JSON.stringify(
                            (() => {
                              const meta = (compilePreview.compile_metadata || {}) as Record<string, unknown>;
                              const base = {
                                compile_metadata: showRawPlannerOutputs
                                  ? meta
                                  : {
                                      ...meta,
                                      raw_llm_eval_families: undefined,
                                      raw_llm_prompt_blueprints: undefined,
                                      raw_llm_judge_specs: undefined,
                                      planner_critic_report: undefined,
                                    },
                                eval_families_count: (compilePreview.eval_families as unknown[])?.length,
                                compiled_dataset_spec: compilePreview.compiled_dataset_spec,
                              };
                              return base;
                            })(),
                            null,
                            2
                          )}
                        </pre>
                      </div>
                    )}
                  </>
                )}

                    <div className="flex flex-wrap items-center gap-4">
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
                  <div className="flex items-end pb-1">
                    <button
                      onClick={handleRunBatch}
                      disabled={loading || (advancedMode === "intent" && geminiUnavailable)}
                      className="rounded-xl bg-white px-4 py-2 text-black disabled:opacity-50"
                    >
                      {loading ? "Running..." : "Run Batch"}
                    </button>
                  </div>
                </div>

                <div>
                  <button
                    type="button"
                    onClick={() => setRuntimeOptionsOpen((o) => !o)}
                    className="text-sm text-neutral-400 underline hover:text-neutral-300"
                  >
                    {runtimeOptionsOpen ? "▼" : "▶"} Runtime options
                  </button>
                  {runtimeOptionsOpen && (
                    <div className="mt-3 rounded-xl border border-neutral-800 bg-neutral-950/50 p-3 text-sm text-neutral-500">
                      Optional runtime settings can be added here (e.g. timeout, env overrides).
                    </div>
                  )}
                </div>
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
