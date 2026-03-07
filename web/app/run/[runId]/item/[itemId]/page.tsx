import Link from "next/link";
import { apiGet } from "@/lib/api";

type ItemResultResponse = {
  content: {
    item_id: string;
    verdict: string;
    score: number;
    error_type: string;
    evidence: unknown[];
    raw_output_ref?: {
      uri?: string;
      mime?: string;
      bytes?: number;
      sha256?: string;
    };
    model_version: string;
    seed: number;
    created_at: string;
    task_type: string;
    eval_method: string;
  };
};

type ArtifactResponse = {
  content?: {
    filename: string;
    path: string;
    text: string;
    content_type: string;
    bytes: number;
    parsed_json?: unknown;
    parsed_jsonl?: unknown[];
  };
  error?: {
    kind: string;
    code: string;
    message: string;
    details?: unknown;
  };
};

export default async function ItemDetailPage({
  params,
}: {
  params: Promise<{ runId: string; itemId: string }>;
}) {
  const { runId, itemId } = await params;

  const [item, rawOutput, toolTrace] = await Promise.all([
    apiGet<ItemResultResponse>(`/runs/${runId}/items/${itemId}`),
    apiGet<ArtifactResponse>(`/runs/${runId}/artifacts/${itemId}_raw.txt`),
    apiGet<ArtifactResponse>(`/runs/${runId}/artifacts/${itemId}_tool_trace.json`),
  ]);

  return (
    <main className="min-h-screen bg-neutral-950 text-neutral-100 p-8">
      <div className="mx-auto max-w-6xl space-y-8">
        <div>
          <Link href={`/run/${runId}`} className="text-sm text-neutral-400 underline">
            ← Back to run
          </Link>
          <h1 className="mt-3 text-3xl font-semibold">{itemId}</h1>
          <p className="mt-2 text-neutral-400">
            {item.content.task_type} · {item.content.eval_method}
          </p>
        </div>

        <section className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
          <h2 className="mb-4 text-xl font-medium">Item Result</h2>
          <pre className="overflow-x-auto whitespace-pre-wrap text-sm">
{JSON.stringify(item.content, null, 2)}
          </pre>
        </section>

        <section className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
          <h2 className="mb-4 text-xl font-medium">Raw Output</h2>
          <pre className="overflow-x-auto whitespace-pre-wrap text-sm">
{rawOutput.content?.text ?? JSON.stringify(rawOutput, null, 2)}
          </pre>
        </section>

        <section className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5">
          <h2 className="mb-4 text-xl font-medium">Tool Trace</h2>
          <pre className="overflow-x-auto whitespace-pre-wrap text-sm">
{toolTrace.content?.text ?? JSON.stringify(toolTrace, null, 2)}
          </pre>
        </section>
      </div>
    </main>
  );
}
