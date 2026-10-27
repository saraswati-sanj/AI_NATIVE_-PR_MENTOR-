import type { Meta } from "../types";

/**
 * The three notices from DESIGN.md section 5.1: partial code, AI unavailable,
 * and AI findings discarded by the guardrails.
 *
 * The last one is the point of the whole design, so it is shown as information
 * rather than as a problem: it means the verification actually ran.
 */
export default function Banner({ meta }: { meta: Meta }) {
  const notices: { tone: string; text: string }[] = [];

  if (meta.is_partial) {
    notices.push({
      tone: "border-amber-300 bg-amber-50 text-amber-900",
      text:
        "This does not parse as complete Python, so it was treated as a fragment. " +
        "Rule checks ran where they could, and some findings may be missing.",
    });
  }

  if (!meta.ai_available) {
    notices.push({
      tone: "border-slate-300 bg-slate-50 text-slate-700",
      text:
        "AI review was unavailable, so these are rule-based findings only. " +
        "Everything shown is from static analysis and is reliable.",
    });
  }

  if (meta.ai_dropped > 0) {
    notices.push({
      tone: "border-sky-300 bg-sky-50 text-sky-900",
      text:
        `${meta.ai_dropped} AI ${meta.ai_dropped === 1 ? "finding was" : "findings were"} ` +
        "discarded by the guardrails for pointing at unchanged lines, repeating a " +
        "rule finding, or citing a line that does not exist.",
    });
  }

  if (notices.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      {notices.map((notice) => (
        <p key={notice.text} className={`rounded border px-3 py-2 text-sm ${notice.tone}`}>
          {notice.text}
        </p>
      ))}
    </div>
  );
}
