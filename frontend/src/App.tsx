import { useState } from "react";
import { review } from "./api";
import type { Finding, Meta } from "./types";
import Banner from "./components/Banner";
import CodeInput from "./components/CodeInput";
import FindingsList from "./components/FindingsList";

type Status = "idle" | "loading" | "results" | "error";

export default function App() {
  const [input, setInput] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [findings, setFindings] = useState<Finding[]>([]);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState("");

  async function handleReview() {
    setStatus("loading");
    setError("");
    try {
      const result = await review(input);
      setFindings(result.findings);
      setMeta(result.meta);
      setStatus("results");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
      setStatus("error");
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="mx-auto max-w-3xl space-y-6 px-4 py-8">
        <header>
          <h1 className="text-2xl font-semibold">PR Mentor AI</h1>
          <p className="mt-1 text-sm text-slate-600">
            A code reviewer that teaches. Rule findings are certain; AI findings are
            verified before you see them.
          </p>
        </header>

        <CodeInput
          value={input}
          onChange={setInput}
          onReview={handleReview}
          loading={status === "loading"}
        />

        {status === "loading" && (
          <p className="text-sm text-slate-500">
            Running ruff and bandit, then asking the AI reviewer...
          </p>
        )}

        {status === "error" && (
          <p className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
            {error}
          </p>
        )}

        {status === "results" && meta && (
          <div className="space-y-4">
            <Banner meta={meta} />

            {findings.length === 0 ? (
              <div className="rounded border border-emerald-300 bg-emerald-50 p-4">
                <p className="font-medium text-emerald-900">No issues found</p>
                {/* Must not claim the AI came back clean when it never ran. */}
                <p className="mt-1 text-sm text-emerald-800">
                  {meta.ai_available
                    ? "The rule engine and the AI reviewer both came back clean on the changed lines."
                    : "The rule engine found nothing on the changed lines. The AI reviewer did not run, so this is a rule-only result."}
                </p>
              </div>
            ) : (
              <FindingsList findings={findings} />
            )}

            <p className="text-xs text-slate-400">
              {meta.rule_count} rule · {meta.ai_count} AI · reviewed in {meta.duration_ms} ms
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
