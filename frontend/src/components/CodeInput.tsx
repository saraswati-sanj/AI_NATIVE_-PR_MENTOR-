import { EXAMPLES } from "../examples";

/** Matches the backend's own limits so the user sees them before submitting. */
const MAX_LINES = 300;
const MAX_KB = 20;

interface Props {
  value: string;
  onChange: (value: string) => void;
  onReview: () => void;
  loading: boolean;
}

export default function CodeInput({ value, onChange, onReview, loading }: Props) {
  const lines = value ? value.split("\n").length : 0;
  const kb = new TextEncoder().encode(value).length / 1024;
  const overLimit = lines > MAX_LINES || kb > MAX_KB;
  const disabled = loading || value.trim().length === 0 || overLimit;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-slate-500">Try an example:</span>
        {EXAMPLES.map((example) => (
          <button
            key={example.label}
            type="button"
            onClick={() => onChange(example.code)}
            disabled={loading}
            title={`Expected: ${example.expected}`}
            className="rounded border border-slate-300 px-2 py-1 text-sm text-slate-700 hover:bg-slate-100 disabled:opacity-50"
          >
            {example.label}
          </button>
        ))}
      </div>

      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
        rows={16}
        placeholder="Paste a Python snippet or a unified diff..."
        className="w-full rounded border border-slate-300 p-3 font-mono text-sm leading-relaxed focus:border-slate-500 focus:outline-none"
      />

      <div className="flex items-center justify-between gap-3">
        <span className={`text-sm ${overLimit ? "text-red-600" : "text-slate-500"}`}>
          {lines} / {MAX_LINES} lines · {kb.toFixed(1)} / {MAX_KB} KB
          {overLimit && " - too large to review"}
        </span>
        <button
          type="button"
          onClick={onReview}
          disabled={disabled}
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? "Reviewing..." : "Review"}
        </button>
      </div>
    </section>
  );
}
