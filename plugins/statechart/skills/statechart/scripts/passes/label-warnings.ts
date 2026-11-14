import { append, byText, type Chart, type ChartStep, type Region, tupleKey } from "../ir.ts";

const ENGLISH_PRONOUN = /^(?:you|your|i|we|it|they|he|she)(?![\p{L}\p{N}/])/iu;
const CHINESE_PRONOUN = /^(?:你|我们|我|它|他们|他|她)/u;
const CJK = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u;
const LETTER = /[\p{L}\p{N}]/u;
const BRACKETS = /^[\p{White_Space}[\](){}"'`]+/u;

export type LabelWarning = { kind: "pronoun" | "short" | "same" | "joined"; text: string };

const quoted = (s: string) => `"${s}"`;

const startsWithPronoun = (label: string) => {
  const s = label.replace(BRACKETS, "");
  return ENGLISH_PRONOUN.test(s) || CHINESE_PRONOUN.test(s);
};

const isShort = (label: string, words: number) => {
  const letters = [...label].filter((c) => LETTER.test(c));
  const cjk = letters.filter((c) => CJK.test(c)).length;
  if (cjk * 2 > letters.length) return [...label].filter((c) => !/\p{White_Space}/u.test(c)).length < 4;
  return label.split(/\p{White_Space}+/u).filter((w) => LETTER.test(w)).length < words;
};

export const stateName = (region: Region, path: string[]) =>
  (region.name ? `${region.name}: ` : "") + path.join(" / ");

export const arrowLabel = (s: ChartStep) => s.label + (s.when ? ` [${s.when}]` : "");

export function labelWarnings(chart: Chart): LabelWarning[] {
  const found = new Map<string, LabelWarning>();
  const add = (kind: LabelWarning["kind"], text: string) => {
    if (!found.has(text)) found.set(text, { kind, text });
  };
  for (const r of chart.regions) {
    const names = new Set<string>();
    for (const s of r.states) for (const name of s.path) names.add(name);
    for (const name of [...names].sort(byText)) {
      const where = r.name ? ` in ${r.name}` : "";
      if (startsWithPronoun(name))
        add("pronoun", `The state label ${quoted(name)}${where} starts with a pronoun.`);
      if (isShort(name, 2))
        add("short", `The state label ${quoted(name)}${where} is too short to name its subject.`);
    }
    const leaving = new Map<string, ChartStep[]>();
    for (const s of r.steps) {
      const label = arrowLabel(s);
      const suffix = s.when ? ` [${s.when}]` : "";
      const at = `from ${quoted(stateName(r, s.from))} to ${quoted(stateName(r, s.to))}`;
      for (const part of s.parts) {
        const text = part + suffix;
        if (startsWithPronoun(text))
          add("pronoun", `The arrow label ${quoted(text)} ${at} starts with a pronoun.`);
        if (isShort(text, 3))
          add("short", `The arrow label ${quoted(text)} ${at} is too short to name its actor.`);
      }
      if (s.parts.length > 1)
        add(
          "joined",
          `The tool joined ${s.parts.length} labels into ${quoted(label)} ${at}. Give each arrow its own destination or its own label.`,
        );
      append(leaving, tupleKey([s.from, label]), s);
    }
    for (const same of leaving.values()) {
      const targets = new Map<string, string>();
      for (const s of same) targets.set(tupleKey(s.to), stateName(r, s.to));
      if (targets.size < 2) continue;
      add(
        "same",
        `${targets.size} arrows leave ${quoted(stateName(r, same[0].from))} with the label ${quoted(arrowLabel(same[0]))} and go to different states: ${[...targets.values()].sort(byText).map(quoted).join(", ")}. Tell them apart with a condition in brackets.`,
      );
    }
  }
  return [...found.values()];
}

export type ArrowRow = { label: string; from: string; to: string; actions: string; steps: number };

export function arrowRows(chart: Chart): ArrowRow[] {
  const rows: ArrowRow[] = [];
  for (const r of chart.regions)
    for (const s of r.steps)
      rows.push({
        label: arrowLabel(s),
        from: stateName(r, s.from),
        to: stateName(r, s.to),
        actions: s.actions.join(", "),
        steps: s.steps,
      });
  return rows;
}
