import Link from "next/link";
import { apiGet } from "@/lib/api";
import { JsonBlock, SectionCard } from "@/components/run-primitives";

type TraceResponse = {
  content: {
    run_id: string;
    item_id: string;
    item: unknown;
    oracle: unknown;
    qa_report: unknown;
    result: unknown;
    action_plans: unknown[];
    data_requests: unknown[];
    events: unknown[];
    raw_output: string | null;
    tool_trace: unknown;
    version_bundle: Record<string, unknown>;
  };
};

const PANELS = ["item", "oracle", "qa", "result", "requests", "raw", "events", "version"] as const;
type Panel = (typeof PANELS)[number];

function panelHref(runId: string, itemId: string, panel: Panel, view: "pretty" | "raw") {
  return `/run/${runId}/item/${itemId}?panel=${panel}&view=${view}`;
}

export default async function ItemTracePage({
  params,
  searchParams,
}: {
  params: Promise<{ runId: string; itemId: string }>;
  searchParams?: Promise<{ panel?: string; view?: string }>;
}) {
  const { runId, itemId } = await params;
  const sp = (await searchParams) ?? {};
  const panel = (PANELS.includes((sp.panel as Panel) ?? "item") ? sp.panel : "item") as Panel;
  const view = sp.view === "raw" ? "raw" : "pretty";

  const traceRes = (await apiGet(`/runs/${runId}/items/${itemId}/trace`)) as TraceResponse;
  const trace = traceRes.content;

  const panelData: Record<Panel, unknown> = {
    item: trace.item,
    oracle: trace.oracle,
    qa: trace.qa_report,
    result: trace.result,
    requests: {
      action_plans: trace.action_plans,
      data_requests: trace.data_requests,
    },
    raw: {
      raw_output: trace.raw_output,
      tool_trace: trace.tool_trace,
    },
    events: trace.events,
    version: trace.version_bundle,
  };

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100">
      <div className="mx-auto max-w-7xl px-6 py-8">
        <div className="mb-6">
          <Link href={`/run/${runId}?tab=items`} className="text-sm text-neutral-400 hover:text-neutral-200">
            ← Back to items
          </Link>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white">Item trace</h1>
          <div className="mt-2 font-mono text-sm text-neutral-400">{itemId}</div>
        </div>

        <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)_260px]">
          <SectionCard title="Trace">
            <div className="space-y-2">
              {PANELS.map((name) => (
                <Link
                  key={name}
                  href={panelHref(runId, itemId, name, view)}
                  className={`block rounded-xl px-3 py-2 text-sm capitalize ${
                    panel === name ? "bg-white text-black" : "bg-neutral-950 text-neutral-300 hover:bg-neutral-900"
                  }`}
                >
                  {name === "qa" ? "QA gate" : name}
                </Link>
              ))}
            </div>

            <div className="mt-6 border-t border-neutral-800 pt-4">
              <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">View mode</div>
              <div className="mt-2 flex gap-2">
                <Link
                  href={panelHref(runId, itemId, panel, "pretty")}
                  className={`rounded-xl px-3 py-2 text-sm ${
                    view === "pretty" ? "bg-white text-black" : "bg-neutral-950 text-neutral-300"
                  }`}
                >
                  Pretty
                </Link>
                <Link
                  href={panelHref(runId, itemId, panel, "raw")}
                  className={`rounded-xl px-3 py-2 text-sm ${
                    view === "raw" ? "bg-white text-black" : "bg-neutral-950 text-neutral-300"
                  }`}
                >
                  Raw JSON
                </Link>
              </div>
            </div>
          </SectionCard>

          <SectionCard title={`Artifact · ${panel === "qa" ? "QA gate" : panel}`}>
            {view === "raw" ? (
              <JsonBlock data={panelData[panel]} />
            ) : (
              <div className="space-y-4">
                {panel === "raw" ? (
                  <>
                    <div className="rounded-2xl border border-neutral-800 bg-neutral-950/70 p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">
                        Raw output
                      </div>
                      <pre className="mt-3 overflow-auto whitespace-pre-wrap text-sm text-neutral-200">
                        {trace.raw_output ?? "—"}
                      </pre>
                    </div>

                    <div className="rounded-2xl border border-neutral-800 bg-neutral-950/70 p-4">
                      <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">
                        Tool trace
                      </div>
                      <JsonBlock data={trace.tool_trace} maxHeight="max-h-[18rem]" />
                    </div>
                  </>
                ) : (
                  <JsonBlock data={panelData[panel]} />
                )}
              </div>
            )}
          </SectionCard>

          <SectionCard title="Metadata">
            <div className="space-y-3">
              <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">Run</div>
                <div className="mt-2 font-mono text-xs text-neutral-300">{runId}</div>
              </div>

              <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">Item</div>
                <div className="mt-2 font-mono text-xs text-neutral-300">{itemId}</div>
              </div>

              <div className="rounded-xl border border-neutral-800 bg-neutral-950/70 p-4">
                <div className="text-xs uppercase tracking-[0.16em] text-neutral-500">Version bundle</div>
                <div className="mt-2 text-sm text-neutral-200">
                  <JsonBlock data={trace.version_bundle} maxHeight="max-h-[16rem]" />
                </div>
              </div>
            </div>
          </SectionCard>
        </div>
      </div>
    </main>
  );
}
