import { useState } from "react";
import type { Finding, Severity } from "../types";

const SEVERITY_PILL: Record<Severity, string> = {
  critical: "bg-red-600 text-white",
  major: "bg-amber-500 text-white",
  minor: "bg-slate-400 text-white",
};

const SEVERITY_BORDER: Record<Severity, string> = {
  critical: "border-l-red-500",
  major: "border-l-amber-400",
  minor: "border-l-slate-300",
};

export default function FindingCard({ finding }: { finding: Finding }) {
  const [copied, setCopied] = useState(false);

  async function copyFix() {
    if (!finding.suggested_fix) {
      return;
    }
    try {
      await navigator.clipboard.writeText(finding.suggested_fix);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can be denied; the fix is on screen to copy by hand.
    }
  }

  return (
    <article
      className={`rounded border border-l-4 border-slate-200 bg-white p-4 ${SEVERITY_BORDER[finding.severity]}`}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <span className={`rounded px-2 py-0.5 font-semibold uppercase ${SEVERITY_PILL[finding.severity]}`}>
          {finding.severity}
        </span>
        <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-600">{finding.category}</span>

        {/* Rule vs AI must be visually distinct: this is the design's core claim. */}
        {finding.source === "rule" ? (
          <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-white">
            RULE{finding.rule_id ? ` ${finding.rule_id}` : ""}
          </span>
        ) : (
          <span className="rounded border border-violet-400 bg-violet-50 px-2 py-0.5 font-mono text-violet-700">
            AI
            {finding.confidence !== null
              ? ` ${Math.round(finding.confidence * 100)}% sure`
              : ""}
          </span>
        )}

        <span className="ml-auto text-slate-500">line {finding.line}</span>
      </div>

      <h3 className="font-medium text-slate-900">{finding.title}</h3>
      <p className="mt-1 text-sm leading-relaxed text-slate-600">{finding.why_it_matters}</p>

      {finding.suggested_fix && (
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-medium uppercase text-slate-500">Suggested fix</span>
            <button
              type="button"
              onClick={copyFix}
              className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100"
            >
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <pre className="overflow-x-auto rounded bg-slate-900 p-3 font-mono text-xs text-slate-100">
            {finding.suggested_fix}
          </pre>
          {/* Only meaningful when a fix exists: no fix is not an unverified fix. */}
          {!finding.fix_verified && (
            <p className="mt-1 text-xs text-amber-700">
              This fix did not parse as valid Python, so check it before using it.
            </p>
          )}
        </div>
      )}

      {finding.concept && (
        <p className="mt-3 border-t border-slate-100 pt-2 text-xs text-slate-500">
          Learn next: <span className="font-medium text-slate-700">{finding.concept}</span>
        </p>
      )}
    </article>
  );
}
