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

// —— Planner: staged compile status (frontend-only UX) ————————————————————
const PLANNER_COMPILE_STAGES = [
  "正在理解评测目标…",
  "正在选择支持的评测类型…",
  "正在编译判定规则与 Batch 规格…",
];

const DEFAULT_BRIEF_PLACEHOLDER =
  "评测邮件查询任务中的 tool-use 可靠性，重点关注 trajectory 正确性、schema adherence，以及困难边界场景。请优先覆盖更容易暴露失败的问题样本，总量约 100 条。";

const DEFAULT_INTENT_SPEC = {
  evaluation_goal: "Evaluate email extraction and multi-step tool use reliability.",
  capability_focus: ["extraction", "trajectory"],
  difficulty_mix: { medium: 0.3, hard: 0.7 },
  risk_focus: ["schema_adherence", "tool_use_correctness", "instruction_following"],
  batch_size: 12,
};
const DEFAULT_INTENT_JSON = JSON.stringify(DEFAULT_INTENT_SPEC, null, 2);

type CompileBriefResponse = {
  brief_text: string;
  intent_spec: Record<string, unknown>;
  compiled_plan: Record<string, unknown>;
  compiled_dataset_spec: Record<string, unknown>;
  compile_metadata: Record<string, unknown>;
};

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
  const [advancedMode, setAdvancedMode] = useState<"custom_json" | "intent">("intent");
  const [intentJson, setIntentJson] = useState(DEFAULT_INTENT_JSON);
  const [compilePreview, setCompilePreview] = useState<Record<string, unknown> | null>(null);
  const [compileError, setCompileError] = useState("");
  const [runtimeOptionsOpen, setRuntimeOptionsOpen] = useState(false);
  const [runSectionMode, setRunSectionMode] = useState<"planner" | "expert" | "demo">("planner");
  const [sutUrl, setSutUrl] = useState(`${API_BASE}/sut/run`);
  const [quota, setQuota] = useState(12);
  const [demoCase, setDemoCase] = useState<string>("wrong_email");
  const [loading, setLoading] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [error, setError] = useState("");
  const [latestRunId, setLatestRunId] = useState("");
  const [latestFailedCluster, setLatestFailedCluster] = useState<string | null>(null);
  const [demoCases, setDemoCases] = useState<Array<{ value: string; label: string }>>(QUICK_DEMO_CASES_FALLBACK);
  const [plannerMode, setPlannerMode] = useState<string>("hybrid");
  const [plannerModel, setPlannerModel] = useState("gemini-3-flash-preview");
  const [plannerTemperature, setPlannerTemperature] = useState<number | "">("");
  const [showRawPlannerOutputs, setShowRawPlannerOutputs] = useState(false);
  const [plannerStatus, setPlannerStatus] = useState<PlannerStatusResponse | null>(null);

  // Planner (brief-first)
  const [briefText, setBriefText] = useState(DEFAULT_BRIEF_PLACEHOLDER);
  const [briefCompileResult, setBriefCompileResult] = useState<CompileBriefResponse | null>(null);
  const [briefCompileLoading, setBriefCompileLoading] = useState(false);
  const [briefCompileError, setBriefCompileError] = useState("");
  const [briefTargetDomain, setBriefTargetDomain] = useState("");
  const [briefDisclosureIntent, setBriefDisclosureIntent] = useState(false);
  const [briefDisclosurePlan, setBriefDisclosurePlan] = useState(false);
  const [briefDisclosureSpec, setBriefDisclosureSpec] = useState(false);
  // Staged loading UX during compile (frontend-only; advances on timer)
  const [plannerCompileStage, setPlannerCompileStage] = useState(0);

  // Expert JSON: dataset spec (direct) vs intent spec (compile then run)
  const [expertRunInputMode, setExpertRunInputMode] = useState<"dataset_spec" | "intent_spec">("dataset_spec");

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
      setError(err instanceof Error ? err.message : "加载运行列表失败");
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

  // Staged compile status (frontend-only): advance stage on timer while compile is in progress
  useEffect(() => {
    if (!briefCompileLoading) {
      setPlannerCompileStage(0);
      return;
    }
    setPlannerCompileStage(0);
    const t1 = setTimeout(() => setPlannerCompileStage(1), 800);
    const t2 = setTimeout(() => setPlannerCompileStage(2), 1800);
    return () => {
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, [briefCompileLoading]);

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
      const useIntent = runSectionMode === "expert" && expertRunInputMode === "intent_spec";
      if (useIntent) {
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
      setError(err instanceof Error ? err.message : "运行 Batch 失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleCompilePreview() {
    setCompileError("");
    setCompilePreview(null);
    setPreviewLoading(true);
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
      setCompileError(err instanceof Error ? err.message : "编译失败");
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleCompileBrief() {
    setBriefCompileError("");
    setBriefCompileResult(null);
    setBriefCompileLoading(true);
    try {
      const targetDomain = briefTargetDomain.trim()
        ? briefTargetDomain.split(/[\s,]+/).filter(Boolean)
        : undefined;
      const res = await apiPost<CompileBriefResponse>("/compile-brief", {
        brief_text: briefText.trim() || DEFAULT_BRIEF_PLACEHOLDER,
        quota: quota,
        planner_mode: plannerMode,
        planner_model: plannerModel || undefined,
        planner_temperature: plannerTemperature === "" ? undefined : Number(plannerTemperature),
        allow_experimental: false,
        target_domain: targetDomain,
      });
      setBriefCompileResult(res);
    } catch (err) {
      setBriefCompileError(err instanceof Error ? err.message : "编译失败");
    } finally {
      setBriefCompileLoading(false);
    }
  }

  async function handleRunCompiledBatch() {
    if (!briefCompileResult?.compiled_dataset_spec) {
      setError("请先完成方案编译，再运行编译结果。");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await apiPost<RunCreateResponse>("/runs", {
        spec_json: JSON.stringify(briefCompileResult.compiled_dataset_spec),
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
      setError(err instanceof Error ? err.message : "运行 Batch 失败");
    } finally {
      setLoading(false);
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
        const msg =
          typeof body.detail === "string"
            ? body.detail
            : body.message || res.statusText || "演示运行失败";
        setError(msg);
        return;
      }
      const runId = body.run_id;
      if (!runId) {
        setError("服务端未返回 run_id");
        return;
      }
      setLatestRunId(runId);
      await loadRuns();
      router.push(`/run/${runId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "演示运行失败");
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
      setError(err instanceof Error ? err.message : "运行 regression 失败");
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
          <div className="text-sm uppercase tracking-[0.2em] text-white">
            规划驱动的评测与故障诊断
          </div>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-white">
            评测引擎
          </h1>
          <p className="mt-3 max-w-3xl text-lg text-neutral-400">
            从高层目标发起评测，追踪全链路阶段，并查看带诊断的结构化失败，而不只是通过 /
            失败。
          </p>
        </div>

        <div className="mb-8 grid gap-4 md:grid-cols-4">
          <StatCard label="最近运行" value={String(runs.length)} />
          <StatCard
            label="最新运行通过率"
            value={runs.length ? formatPassRate(runs[0].pass_rate) : "—"}
          />
          <StatCard
            label="最近失败项"
            value={latestFailedCluster ?? (failedRunsCount > 0 ? "…" : "—")}
            hint="最近几次运行中最新出现的失败类型"
          />
          <StatCard
            label="失败运行数"
            value={String(failedRunsCount)}
            hint={failedRunsCount > 0 ? "可前往 Mission Control 查看" : "近期无失败"}
          />
        </div>

        <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
          <SectionCard title="发起运行">
            <div className="mb-5 flex gap-2 rounded-2xl border border-neutral-800 bg-neutral-950 p-1">
              <button
                onClick={() => setRunSectionMode("planner")}
                className={`flex-1 rounded-xl px-3 py-2 text-sm ${
                  runSectionMode === "planner"
                    ? "bg-white text-black"
                    : "text-neutral-300 hover:bg-neutral-900"
                }`}
              >
                规划输入（推荐）
              </button>
              <button
                onClick={() => setRunSectionMode("expert")}
                className={`flex-1 rounded-xl px-3 py-2 text-sm ${
                  runSectionMode === "expert"
                    ? "bg-white text-black"
                    : "text-neutral-300 hover:bg-neutral-900"
                }`}
              >
                专家模式 JSON
              </button>
              <button
                onClick={() => setRunSectionMode("demo")}
                className={`flex-1 rounded-xl px-3 py-2 text-sm ${
                  runSectionMode === "demo"
                    ? "bg-white text-black"
                    : "text-neutral-300 hover:bg-neutral-900"
                }`}
              >
                演示案例
              </button>
            </div>

            {runSectionMode === "demo" ? (
              <div className="space-y-4">
                <p className="text-sm text-neutral-400">
                  用于演示评测流水线与失败处理：一键运行失败案例，然后进入运行详情查看阶段流转、结构化失败与诊断结果。
                </p>
                <div>
                  <label className="mb-2 block text-sm text-neutral-300">失败演示案例</label>
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

                <div className="flex flex-col gap-3">
                  <button
                    onClick={handleFailureDemo}
                    disabled={loading}
                    className="w-full rounded-xl bg-white px-4 py-2.5 text-black font-medium disabled:opacity-50 sm:w-auto"
                  >
                    {loading ? "运行中..." : "运行失败演示"}
                  </button>
                  <div className="flex items-center gap-2 text-xs text-neutral-500">
                    <span>可选：</span>
                    <button
                      type="button"
                      onClick={handleRegression}
                      disabled={loading}
                      className="underline hover:text-neutral-400 disabled:opacity-50"
                    >
                      运行 golden regression
                    </button>
                    <span>以辅助发布前验证。</span>
                  </div>
                </div>
              </div>
            ) : runSectionMode === "planner" ? (
              <div className="space-y-4">
                <p className="text-sm font-medium text-neutral-200">
                  请用自然语言描述你想评测的能力与目标。
                </p>
                <p className="text-sm text-neutral-400">
                  系统会将你的描述编译为支持的评测类型、样本蓝图与判定规则。
                </p>
                <div>
                  <label className="mb-2 block text-sm text-neutral-300">评测需求说明</label>
                  <textarea
                    value={briefText}
                    onChange={(e) => setBriefText(e.target.value)}
                    className="min-h-[120px] w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm placeholder:text-neutral-600"
                    rows={5}
                  />
                </div>
                <div className="flex flex-wrap items-end gap-4 rounded-xl border border-neutral-800/80 bg-neutral-900/40 p-3">
                  <div>
                    <label className="mb-1 block text-xs text-neutral-500">运行样本数量</label>
                    <input
                      type="number"
                      min={1}
                      max={500}
                      value={quota}
                      onChange={(e) => setQuota(Number(e.target.value) || 1)}
                      className="w-24 rounded-lg border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-neutral-500">规划模式</label>
                    <select
                      value={plannerMode}
                      onChange={(e) => setPlannerMode(e.target.value)}
                      className="rounded-lg border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm"
                    >
                      <option value="hybrid">混合模式（LLM + 确定性）</option>
                    </select>
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-neutral-500">规划模型</label>
                    <input
                      type="text"
                      value={plannerModel}
                      onChange={(e) => setPlannerModel(e.target.value)}
                      placeholder="可选"
                      className="w-40 rounded-lg border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm font-mono"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-neutral-500">Temperature（温度）</label>
                    <input
                      type="number"
                      min={0}
                      max={2}
                      step={0.1}
                      value={plannerTemperature === "" ? "" : plannerTemperature}
                      onChange={(e) =>
                        setPlannerTemperature(e.target.value === "" ? "" : Number(e.target.value))
                      }
                      placeholder="—"
                      className="w-16 rounded-lg border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm"
                    />
                  </div>
                  <div className="min-w-[140px]">
                    <label className="mb-1 block text-xs text-neutral-500">目标领域标签</label>
                    <input
                      type="text"
                      value={briefTargetDomain}
                      onChange={(e) => setBriefTargetDomain(e.target.value)}
                      placeholder="例如：extraction, trajectory"
                      className="w-full rounded-lg border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm"
                    />
                  </div>
                  <div className="min-w-[200px]">
                    <label className="mb-1 block text-xs text-neutral-500">SUT URL（运行时）</label>
                    <input
                      value={sutUrl}
                      onChange={(e) => setSutUrl(e.target.value)}
                      className="w-full rounded-lg border border-neutral-800 bg-neutral-950 px-2 py-1.5 font-mono text-sm"
                      placeholder="http://127.0.0.1:8000/sut/run"
                    />
                  </div>
                </div>
                {plannerStatus &&
                  !plannerStatus.gemini_configured &&
                  (plannerMode === "llm" || plannerMode === "hybrid") && (
                    <p className="text-sm text-amber-400">
                      Gemini planner 尚未配置（缺少 GEMINI_API_KEY）。请使用 deterministic
                      模式，或在服务端配置 GEMINI_API_KEY。
                    </p>
                  )}
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={handleCompileBrief}
                    disabled={
                      briefCompileLoading ||
                      (["llm", "hybrid"].includes(plannerMode) && !plannerStatus?.gemini_configured)
                    }
                    className="rounded-xl bg-white px-4 py-2 text-black font-medium disabled:opacity-50 inline-flex items-center gap-2"
                  >
                    {briefCompileLoading && (
                      <span
                        className="size-4 shrink-0 rounded-full border-2 border-neutral-400 border-t-transparent animate-spin"
                        aria-hidden
                      />
                    )}
                    {briefCompileLoading ? "编译中…" : "生成评测方案"}
                  </button>
                  {briefCompileError && (
                    <span className="text-sm text-red-400">{briefCompileError}</span>
                  )}
                </div>
                {briefCompileLoading && (
                  <div className="rounded-xl border border-neutral-700 bg-neutral-900/50 p-4">
                    <div className="flex items-center gap-3">
                      <span
                        className="size-5 shrink-0 rounded-full border-2 border-neutral-500 border-t-transparent animate-spin"
                        aria-hidden
                      />
                      <div>
                        <div className="text-sm font-medium text-neutral-200">
                          {
                            PLANNER_COMPILE_STAGES[
                              Math.min(plannerCompileStage, PLANNER_COMPILE_STAGES.length - 1)
                            ]
                          }
                        </div>
                        <p className="mt-0.5 text-xs text-neutral-500">
                          规划器正在基于评测目录生成你的评测方案。
                        </p>
                      </div>
                    </div>
                  </div>
                )}
                {briefCompileResult && !briefCompileLoading && (
                  <div className="space-y-4">
                    <div className="text-sm font-medium text-neutral-300">编译结果预览</div>
                    <div className="rounded-xl border border-neutral-700 bg-neutral-900/50 p-4 space-y-4">
                      <div>
                        <div className="text-xs uppercase tracking-wide text-neutral-500">评测目标</div>
                        <p className="mt-1 text-sm text-neutral-300">
                          {(briefCompileResult.intent_spec?.evaluation_goal as string) ?? "—"}
                        </p>
                      </div>
                      <div>
                        <div className="text-xs uppercase tracking-wide text-neutral-500">
                          推断能力重点
                        </div>
                        <p className="mt-1 text-sm text-neutral-300">
                          {(briefCompileResult.intent_spec?.capability_focus as string[])?.join(
                            ", "
                          ) ?? "—"}
                        </p>
                      </div>
                      <div>
                        <div className="text-xs uppercase tracking-wide text-neutral-500">
                          已选评测类型（Eval Families）
                        </div>
                        <ul className="mt-1 list-inside list-disc text-sm text-neutral-300">
                          {(
                            (briefCompileResult.compiled_plan?.eval_families as Array<{
                              family_id?: string;
                            }>) ?? []
                          ).map((f, i) => (
                            <li key={i}>{f.family_id ?? "—"}</li>
                          ))}
                        </ul>
                      </div>
                      <div>
                        <div className="text-xs uppercase tracking-wide text-neutral-500">
                          判定方式（Judge Methods）
                        </div>
                        <ul className="mt-1 list-inside list-disc text-sm text-neutral-300">
                          {(
                            (briefCompileResult.compiled_plan?.judge_specs as Array<{
                              judge_spec_id?: string;
                            }>) ?? []
                          )
                            .slice(0, 8)
                            .map((j, i) => (
                              <li key={i}>{j.judge_spec_id ?? "—"}</li>
                            ))}
                        </ul>
                      </div>
                      <div>
                        <div className="text-xs uppercase tracking-wide text-neutral-500">
                          目标构成
                        </div>
                        <p className="mt-1 text-sm text-neutral-300">
                          {(briefCompileResult.compiled_dataset_spec?.capability_targets as unknown[])
                            ?.length ?? 0}{" "}
                          个 capability targets · 数据集：{" "}
                          {(briefCompileResult.compiled_dataset_spec?.dataset_name as string) ?? "—"}
                        </p>
                      </div>
                      {((briefCompileResult.compile_metadata?.warnings as string[]) ?? []).length >
                        0 && (
                        <div>
                          <div className="text-xs uppercase tracking-wide text-amber-500">警告</div>
                          <ul className="mt-1 list-inside list-disc text-sm text-amber-400">
                            {(briefCompileResult.compile_metadata?.warnings as string[]).map(
                              (w, i) => (
                                <li key={i}>{w}</li>
                              )
                            )}
                          </ul>
                        </div>
                      )}
                      <div className="text-xs text-neutral-500">
                        规划模式：{" "}
                        {(briefCompileResult.compile_metadata?.planner_mode as string) ?? "—"}
                        {(briefCompileResult.compile_metadata?.fallback_used as boolean) &&
                          "（已启用 fallback）"}
                      </div>
                    </div>
                    <div className="space-y-2">
                      <button
                        type="button"
                        onClick={() => setBriefDisclosureIntent((o) => !o)}
                        className="text-sm text-neutral-400 underline hover:text-neutral-300"
                      >
                        {briefDisclosureIntent ? "▼" : "▶"} 解析后的 intent JSON
                      </button>
                      {briefDisclosureIntent && (
                        <pre className="max-h-48 overflow-auto rounded-xl border border-neutral-700 bg-neutral-900/50 p-3 text-xs text-neutral-400">
                          {JSON.stringify(briefCompileResult.intent_spec, null, 2)}
                        </pre>
                      )}
                      <button
                        type="button"
                        onClick={() => setBriefDisclosurePlan((o) => !o)}
                        className="block text-sm text-neutral-400 underline hover:text-neutral-300"
                      >
                        {briefDisclosurePlan ? "▼" : "▶"} 编译后的 plan JSON
                      </button>
                      {briefDisclosurePlan && (
                        <pre className="max-h-48 overflow-auto rounded-xl border border-neutral-700 bg-neutral-900/50 p-3 text-xs text-neutral-400">
                          {JSON.stringify(briefCompileResult.compiled_plan, null, 2)}
                        </pre>
                      )}
                      <button
                        type="button"
                        onClick={() => setBriefDisclosureSpec((o) => !o)}
                        className="block text-sm text-neutral-400 underline hover:text-neutral-300"
                      >
                        {briefDisclosureSpec ? "▼" : "▶"} 编译后的 dataset spec JSON
                      </button>
                      {briefDisclosureSpec && (
                        <pre className="max-h-48 overflow-auto rounded-xl border border-neutral-700 bg-neutral-900/50 p-3 text-xs text-neutral-400">
                          {JSON.stringify(briefCompileResult.compiled_dataset_spec, null, 2)}
                        </pre>
                      )}
                    </div>
                    <button
                      onClick={handleRunCompiledBatch}
                      disabled={loading}
                      className="rounded-xl bg-white px-4 py-2 text-black font-medium disabled:opacity-50 inline-flex items-center gap-2"
                    >
                      {loading && (
                        <span
                          className="size-4 shrink-0 rounded-full border-2 border-neutral-400 border-t-transparent animate-spin"
                          aria-hidden
                        />
                      )}
                      {loading ? "运行中…" : "运行编译结果"}
                    </button>
                    <p className="text-xs text-neutral-500">
                      将直接运行上方预览的已编译 dataset spec（运行时不会重新编译）。
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-4">
                <p className="text-sm text-neutral-400">
                  直接编辑 planner spec / dataset spec，不经过需求编译，由你完全控制输入 JSON。
                </p>
                <div className="flex gap-2 rounded-2xl border border-neutral-800 bg-neutral-950 p-1">
                  <button
                    type="button"
                    onClick={() => setExpertRunInputMode("dataset_spec")}
                    className={`flex-1 rounded-xl px-3 py-2 text-sm ${
                      expertRunInputMode === "dataset_spec"
                        ? "bg-white text-black"
                        : "text-neutral-400 hover:bg-neutral-900"
                    }`}
                  >
                    Dataset spec（直接运行）
                  </button>
                  <button
                    type="button"
                    onClick={() => setExpertRunInputMode("intent_spec")}
                    className={`flex-1 rounded-xl px-3 py-2 text-sm ${
                      expertRunInputMode === "intent_spec"
                        ? "bg-white text-black"
                        : "text-neutral-400 hover:bg-neutral-900"
                    }`}
                  >
                    Intent spec（先编译再运行）
                  </button>
                </div>
                <div>
                  <label className="mb-2 block text-sm text-neutral-300">SUT URL</label>
                  <input
                    value={sutUrl}
                    onChange={(e) => setSutUrl(e.target.value)}
                    className="w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-sm"
                    placeholder="http://127.0.0.1:8000/sut/run"
                  />
                </div>
                {expertRunInputMode === "dataset_spec" ? (
                  <>
                    <div>
                      <label className="mb-2 block text-sm text-neutral-300">数据集模板</label>
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
                        {advancedJsonOpen ? "▼" : "▶"} 自定义 JSON
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
                    <div className="flex items-end gap-3">
                      <div>
                        <label className="mb-1 block text-xs text-neutral-500">运行样本数量</label>
                        <input
                          type="number"
                          min={1}
                          max={500}
                          value={quota}
                          onChange={(e) => setQuota(Number(e.target.value) || 1)}
                          className="w-24 rounded-lg border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm"
                        />
                      </div>
                      <button
                        onClick={() => {
                          const body: Record<string, unknown> = {
                            quota,
                            sut: "http",
                            sut_url: sutUrl,
                            sut_timeout: 30,
                            model_version: "http-sut-local",
                            spec_json: specJson,
                          };
                          setLoading(true);
                          setError("");
                          apiPost<RunCreateResponse>("/runs", body)
                            .then((res) => {
                              setLatestRunId(res.run_id);
                              loadRuns();
                              router.push(`/run/${res.run_id}`);
                            })
                            .catch((err) =>
                              setError(err instanceof Error ? err.message : "运行 Batch 失败")
                            )
                            .finally(() => setLoading(false));
                        }}
                        disabled={loading}
                        className="rounded-xl bg-white px-4 py-2 text-black font-medium disabled:opacity-50"
                      >
                        {loading ? "运行中…" : "运行 Batch"}
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div>
                      <label className="mb-2 block text-sm text-neutral-300">Intent JSON</label>
                      <p className="mb-1.5 text-xs text-neutral-500">
                        粘贴 intent_spec 后，后端会先完成编译，再运行生成的 Batch。
                      </p>
                      <textarea
                        value={intentJson}
                        onChange={(e) => setIntentJson(e.target.value)}
                        className="h-48 w-full rounded-xl border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-sm"
                        placeholder={DEFAULT_INTENT_JSON}
                      />
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <button
                        type="button"
                        onClick={handleCompilePreview}
                        disabled={previewLoading || geminiUnavailable}
                        className="rounded-xl border border-neutral-700 px-3 py-2 text-sm text-neutral-300 hover:bg-neutral-800/50 disabled:opacity-50 inline-flex items-center gap-2"
                      >
                        {previewLoading && (
                          <span
                            className="size-4 shrink-0 rounded-full border-2 border-neutral-500 border-t-transparent animate-spin"
                            aria-hidden
                          />
                        )}
                        {previewLoading ? "正在生成方案..." : "预览方案"}
                      </button>
                      {compileError && <span className="text-sm text-red-400">{compileError}</span>}
                    </div>
                    {compilePreview &&
                      !previewLoading &&
                      (() => {
                        const spec = compilePreview.compiled_dataset_spec as
                          | Record<string, unknown>
                          | undefined;
                        const targets = Array.isArray(spec?.capability_targets)
                          ? spec.capability_targets
                          : [];
                        return (
                          <div className="rounded-xl border border-neutral-700 bg-neutral-900/50 p-3">
                            <div className="text-xs uppercase tracking-wide text-neutral-500">
                              预览
                            </div>
                            <p className="mt-1 text-sm text-neutral-300">
                              {String(spec?.dataset_name ?? "—")} · {targets.length} 个 targets
                            </p>
                          </div>
                        );
                      })()}
                    <div className="flex items-end gap-3">
                      <div>
                        <label className="mb-1 block text-xs text-neutral-500">运行样本数量</label>
                        <input
                          type="number"
                          min={1}
                          max={500}
                          value={quota}
                          onChange={(e) => setQuota(Number(e.target.value) || 1)}
                          className="w-24 rounded-lg border border-neutral-800 bg-neutral-950 px-2 py-1.5 text-sm"
                        />
                      </div>
                      <button
                        onClick={handleRunBatch}
                        disabled={loading || geminiUnavailable}
                        className="rounded-xl bg-white px-4 py-2 text-black font-medium disabled:opacity-50"
                      >
                        {loading ? "运行中…" : "运行 Batch"}
                      </button>
                    </div>
                  </>
                )}
                <div>
                  <button
                    type="button"
                    onClick={() => setRuntimeOptionsOpen((o) => !o)}
                    className="text-sm text-neutral-400 underline hover:text-neutral-300"
                  >
                    {runtimeOptionsOpen ? "▼" : "▶"} 运行选项
                  </button>
                  {runtimeOptionsOpen && (
                    <div className="mt-3 rounded-xl border border-neutral-800 bg-neutral-950/50 p-3 text-sm text-neutral-500">
                      可在此补充运行时配置（例如 timeout、env overrides）。
                    </div>
                  )}
                </div>
              </div>
            )}

            {latestRunId && (
              <p className="mt-4 text-sm text-emerald-400">
                最新运行：{" "}
                <Link className="underline" href={`/run/${latestRunId}`}>
                  {latestRunId}
                </Link>
              </p>
            )}

            {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
          </SectionCard>

          <div className="space-y-6">
            <SectionCard title="重点运行">
              {featuredRun ? (
                <Link
                  href={`/run/${featuredRun.run_id}`}
                  className="block rounded-2xl border border-neutral-800 bg-neutral-950/80 p-5 transition hover:border-neutral-700 hover:bg-neutral-950"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm text-neutral-400">{featuredRun.dataset_name}</div>
                      <div
                        className="mt-1 font-mono text-sm text-neutral-200"
                        title={featuredRun.run_id}
                      >
                        {shortRunId(featuredRun.run_id)}
                      </div>
                    </div>
                    <StatusBadge status={getRunStatus(featuredRun)} />
                  </div>

                  <div className="mt-4 grid grid-cols-3 gap-3">
                    <StatCard label="通过率" value={formatPassRate(featuredRun.pass_rate)} />
                    <StatCard label="失败数" value={String(featuredRun.failures_total)} />
                    <StatCard
                      label="更新时间"
                      value={formatRunTime(featuredRun.ended_at, featuredRun.started_at)}
                    />
                  </div>

                  <div className="mt-4 text-sm text-neutral-400">
                    进入 Mission Control 查看 pipeline 阶段、样本轨迹与诊断结果。
                  </div>
                </Link>
              ) : (
                <div className="rounded-2xl border border-dashed border-neutral-800 p-6 text-neutral-400">
                  暂无运行记录。
                </div>
              )}
            </SectionCard>

            <SectionCard title="最近运行">
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
                        <span>{run.failures_total} 个失败</span>
                        <span>{run.items_total} 个样本</span>
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