import type { ReactNode } from "react";

export function SectionCard({
  title,
  actions,
  children,
}: {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-neutral-800 bg-neutral-900/80 p-5 shadow-[0_0_0_1px_rgba(255,255,255,0.02)]">
      {(title || actions) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title ? <h2 className="text-lg font-semibold text-white">{title}</h2> : <div />}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-2xl border border-neutral-800 bg-neutral-950/70 p-4">
      <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
      {hint ? <div className="mt-1 text-sm text-neutral-400">{hint}</div> : null}
    </div>
  );
}

export function GateBanner({
  gate,
  message,
}: {
  gate: "PASS" | "WATCH" | "BLOCKED";
  message: string;
}) {
  const cls =
    gate === "PASS"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
      : gate === "WATCH"
        ? "border-amber-500/30 bg-amber-500/10 text-amber-200"
        : "border-red-500/30 bg-red-500/10 text-red-200";

  return (
    <div className={`rounded-2xl border p-4 ${cls}`}>
      <div className="text-xs uppercase tracking-[0.18em] opacity-70">Release gate</div>
      <div className="mt-2 text-xl font-semibold">{gate}</div>
      <div className="mt-2 text-sm">{message}</div>
    </div>
  );
}

export function StatusBadge({ status }: { status: "PASS" | "FAIL" | "PARTIAL" | "WATCH" | "BLOCKED" }) {
  const cls =
    status === "PASS"
      ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
      : status === "FAIL" || status === "BLOCKED"
        ? "border-red-500/40 bg-red-500/15 text-red-300"
        : "border-amber-500/40 bg-amber-500/15 text-amber-300";

  return <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${cls}`}>{status}</span>;
}

export function JsonBlock({ data, maxHeight = "max-h-[34rem]" }: { data: unknown; maxHeight?: string }) {
  return (
    <pre
      className={`overflow-auto rounded-2xl border border-neutral-800 bg-neutral-950/90 p-4 text-xs leading-6 text-neutral-200 ${maxHeight}`}
    >
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}
