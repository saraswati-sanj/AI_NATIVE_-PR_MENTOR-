/**
 * Demo snippets with planted bugs, taken from DESIGN.md section 16.
 *
 * The first three are caught by the rule engine; the fourth needs the AI,
 * which makes it the one that shows what the two sources each contribute.
 */

export interface Example {
  label: string;
  expected: string;
  code: string;
}

export const EXAMPLES: Example[] = [
  {
    label: "SQL injection",
    expected: "rule - bandit B608",
    code: `def find_user(cursor, name):
    query = "SELECT * FROM users WHERE name = '" + name + "'"
    cursor.execute(query)
    return cursor.fetchone()
`,
  },
  {
    label: "Mutable default",
    expected: "rule - ruff B006",
    code: `def add_tag(tag, tags=[]):
    tags.append(tag)
    return tags
`,
  },
  {
    label: "Bare except",
    expected: "rule - ruff E722",
    code: `def read_count(path):
    try:
        return int(open(path).read())
    except:
        return 0
`,
  },
  {
    label: "Off-by-one",
    expected: "ai - logic bug",
    code: `def total_scores(scores):
    total = 0
    for i in range(len(scores) + 1):
        total += scores[i]
    return total / len(scores)
`,
  },
];
