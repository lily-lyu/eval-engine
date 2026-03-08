import { formatMs } from "@/lib/run-view";
import type { StageRow } from "@/lib/run-view";

export function PipelineStrip({ stages }: { stages: StageRow[] }) {
  return (
    <div className="flex flex-wrap gap-3">
      {stages.map((stage) => {
        const stageHasFailure = stage.failCount > 0 || Boolean(stage.topFailureCode);
        const completedTextClass = stageHasFailure ? "text-neutral-200" : "text-emerald-300";
        const failureTextClass = "text-red-400";

        const failureLabel =
          stage.failCount > 0
            ? `failed: ${stage.topFailureCode ?? stage.failCount}`
            : stage.topFailureCode
              ? `fail verdict: ${stage.topFailureCode}`
              : null;

        const borderCls = stageHasFailure
          ? "border-amber-500/40 bg-amber-500/5"
          : "border-neutral-800 bg-neutral-950/70";

        return (
          <div
            key={stage.stage}
            className={`rounded-2xl border p-4 min-w-[10rem] ${borderCls}`}
            title={stage.topFailureCode ?? undefined}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium uppercase tracking-wider text-neutral-500">
                {stage.agent}
              </span>
              {stage.failCount > 0 && (
                <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-xs text-amber-300">
                  {stage.failCount} fail
                </span>
              )}
            </div>
            <div className="mt-2 text-sm font-medium text-white">{stage.label}</div>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-400">
              <span>{stage.inputCount} in</span>
              <span className={completedTextClass}>{stage.okCount} completed</span>
              {stage.avgLatencyMs != null && (
                <span>{formatMs(stage.avgLatencyMs)}</span>
              )}
            </div>
            {failureLabel ? (
              <div className={`mt-3 text-sm ${failureTextClass}`} title={stage.topFailureCode ?? undefined}>
                {failureLabel}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
