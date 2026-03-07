import { formatMs } from "@/lib/run-view";
import type { StageRow } from "@/lib/run-view";

export function PipelineStrip({ stages }: { stages: StageRow[] }) {
  return (
    <div className="flex flex-wrap gap-3">
      {stages.map((row) => {
        const hasFailures = row.failCount > 0;
        const borderCls = hasFailures
          ? "border-amber-500/40 bg-amber-500/5"
          : "border-neutral-800 bg-neutral-950/70";
        return (
          <div
            key={row.stage}
            className={`rounded-2xl border p-4 min-w-[10rem] ${borderCls}`}
            title={row.topFailureCode ?? undefined}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium uppercase tracking-wider text-neutral-500">
                {row.agent}
              </span>
              {hasFailures && (
                <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-xs text-amber-300">
                  {row.failCount} fail
                </span>
              )}
            </div>
            <div className="mt-2 text-sm font-medium text-white">{row.label}</div>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-neutral-400">
              <span>{row.inputCount} in</span>
              <span className="text-emerald-400">{row.okCount} completed</span>
              {row.avgLatencyMs != null && (
                <span>{formatMs(row.avgLatencyMs)}</span>
              )}
            </div>
            {row.topFailureCode && (
              <div className="mt-2 truncate text-xs text-amber-400" title={row.topFailureCode}>
                {row.stage === "VERIFY" ? `fail verdict: ${row.topFailureCode}` : row.topFailureCode}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
