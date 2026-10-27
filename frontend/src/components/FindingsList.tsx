import { useState } from "react";
import type { Finding, Source } from "../types";
import { SEVERITY_ORDER } from "../types";
import FindingCard from "./FindingCard";

type Filter = "all" | Source;

export default function FindingsList({ findings }: { findings: Finding[] }) {
  const [filter, setFilter] = useState<Filter>("all");

  const ruleTotal = findings.filter((f) => f.source === "rule").length;
  const aiTotal = findings.length - ruleTotal;

  const visible = filter === "all" ? findings : findings.filter((f) => f.source === filter);

  const filters: { key: Filter; label: string }[] = [
    { key: "all", label: `All ${findings.length}` },
    { key: "rule", label: `Rule ${ruleTotal}` },
    { key: "ai", label: `AI ${aiTotal}` },
  ];

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-3 text-sm text-slate-600">
          {SEVERITY_ORDER.map((severity) => {
            const count = findings.filter((f) => f.severity === severity).length;
            return (
              <span key={severity}>
                <span className="font-semibold text-slate-900">{count}</span> {severity}
              </span>
            );
          })}
        </div>

        <div className="flex gap-1">
          {filters.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              className={`rounded border px-2 py-1 text-xs ${
                filter === key
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-300 text-slate-600 hover:bg-slate-100"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {visible.length === 0 ? (
        <p className="rounded border border-slate-200 bg-white p-4 text-sm text-slate-500">
          No {filter === "ai" ? "AI " : filter === "rule" ? "rule " : ""}findings to show.
        </p>
      ) : (
        SEVERITY_ORDER.map((severity) => {
          const group = visible.filter((f) => f.severity === severity);
          if (group.length === 0) {
            return null;
          }
          return (
            <div key={severity} className="space-y-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                {severity} ({group.length})
              </h2>
              {group.map((finding) => (
                <FindingCard key={finding.id} finding={finding} />
              ))}
            </div>
          );
        })
      )}
    </section>
  );
}
