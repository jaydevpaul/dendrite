import { describe, expect, it } from "vitest";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkRehype from "remark-rehype";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import rehypeStringify from "rehype-stringify";
import { normalizeMathDelimiters } from "./math";
import {
  EDGES_ATTRIBUTE,
  SOURCE_ATOMIC_ATTRIBUTE,
  SOURCE_END_ATTRIBUTE,
  SOURCE_START_ATTRIBUTE,
  rehypeSourceSpans,
  rehypeStampMath,
} from "./source-spans";
import { offsetsForRange } from "./selection";
import type { AnchorRange } from "./anchor";

/**
 * The renderer's contract with the anchor layer.
 *
 * One property matters more than every specific case here: **a stamped run
 * that is not atomic must contain exactly the source text it claims**. If that
 * holds, a selection measured inside a run and added to its stamp is right by
 * construction; if it fails anywhere, anchors written from that part of a
 * reply are wrong and the API's own check turns them into 422s - or worse,
 * accepts them pointing at the wrong copy of a repeated phrase.
 *
 * `sweep` asserts that property over whole documents, so a markdown construct
 * nobody thought about is still covered as long as it appears in one of them.
 *
 * The pipeline is rebuilt here rather than imported from the component,
 * because the component's copy lives inside react-markdown. The plugins and
 * their order are the part that has to match, and they are listed in one place
 * in each file.
 */
function render(content: string, anchors: AnchorRange[] = []): HTMLElement {
  const html = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkMath, { singleDollarTextMath: false })
    .use(remarkRehype)
    .use(rehypeStampMath)
    .use(rehypeKatex)
    .use(rehypeHighlight, { detect: true, ignoreMissing: true })
    .use(rehypeSourceSpans, { content, anchors })
    .use(rehypeStringify)
    .processSync(normalizeMathDelimiters(content))
    .toString();

  document.body.innerHTML = `<div id="reply">${html}</div>`;
  return document.getElementById("reply") as HTMLElement;
}

function stamped(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(`[${SOURCE_START_ATTRIBUTE}]`)];
}

function stampOf(element: HTMLElement) {
  return {
    start: Number(element.getAttribute(SOURCE_START_ATTRIBUTE)),
    end: Number(element.getAttribute(SOURCE_END_ATTRIBUTE)),
    atomic: element.hasAttribute(SOURCE_ATOMIC_ATTRIBUTE),
  };
}

/** Every measurable run says where it came from, and is right about it. */
function sweep(content: string): number {
  const container = render(content);
  const runs = stamped(container);
  expect(runs.length).toBeGreaterThan(0);

  let measurable = 0;
  for (const run of runs) {
    const { start, end, atomic } = stampOf(run);
    expect(Number.isFinite(start)).toBe(true);
    expect(end).toBeGreaterThan(start);
    if (atomic) continue;
    measurable += 1;
    expect(run.textContent).toBe(content.slice(start, end));
  }
  return measurable;
}

/** A range over the text of the first run whose text is exactly `text`. */
function selectRun(container: HTMLElement, text: string): Range {
  const run = stamped(container).find((element) => element.textContent === text);
  if (run === undefined) throw new Error(`no run rendering exactly ${JSON.stringify(text)}`);
  const range = document.createRange();
  range.selectNodeContents(run);
  return range;
}

describe("source stamps", () => {
  it("stamps a plain paragraph with its own offsets", () => {
    const content = "A plain sentence.";
    const container = render(content);

    const runs = stamped(container);
    expect(runs).toHaveLength(1);
    expect(stampOf(runs[0])).toEqual({ start: 0, end: content.length, atomic: false });
  });

  it("skips the syntax characters emphasis is written with", () => {
    const content = "Hello **world** again";
    const container = render(content);

    // "world" starts at 8 in the source even though it starts at 6 on screen.
    expect(offsetsForRange(container, selectRun(container, "world"))).toEqual({
      start: 8,
      end: 13,
    });
    expect(content.slice(8, 13)).toBe("world");
  });

  it("measures inside a run, so a partial selection is still exact", () => {
    const content = "the **quick brown** fox";
    const container = render(content);

    const run = stamped(container).find((element) => element.textContent === "quick brown")!;
    const text = run.firstChild as Text;
    const range = document.createRange();
    range.setStart(text, 6); // "brown"
    range.setEnd(text, 11);

    const offsets = offsetsForRange(container, range)!;
    expect(content.slice(offsets.start, offsets.end)).toBe("brown");
  });

  it("finds the source text of a list item without its bullet", () => {
    const content = "- first item\n- second item";
    const container = render(content);

    const offsets = offsetsForRange(container, selectRun(container, "second item"))!;
    expect(content.slice(offsets.start, offsets.end)).toBe("second item");
  });

  it("maps a table cell back to the row it was written on", () => {
    const content = "| Token | Weight |\n|---|---|\n| cat | 0.35 |\n| mat | 0.25 |";
    const container = render(content);

    const offsets = offsetsForRange(container, selectRun(container, "0.35"))!;
    expect(content.slice(offsets.start, offsets.end)).toBe("0.35");
  });

  it("measures inside a fenced block, whose text is its source verbatim", () => {
    const content = 'Try this:\n\n```python\nprint("hi")\n```\n';
    const container = render(content);

    const code = container.querySelector<HTMLElement>(`code[${SOURCE_START_ATTRIBUTE}]`)!;
    const { start, atomic } = stampOf(code);
    expect(atomic).toBe(false);
    expect(content.slice(start, start + 'print("hi")'.length)).toBe('print("hi")');

    // Highlighting has cut the code into coloured spans; the text is unchanged,
    // so a range across them still measures correctly.
    const range = document.createRange();
    range.selectNodeContents(code);
    const offsets = offsetsForRange(container, range)!;
    expect(content.slice(offsets.start, offsets.end)).toBe('print("hi")\n');
  });

  it("treats a formula as one range rather than measuring inside KaTeX", () => {
    const content = "The score:\n\n\\[ QK^T \\]\n";
    const container = render(content);

    const math = stamped(container).find(
      (element) => element.querySelector(".katex") !== null,
    );
    expect(math).toBeDefined();
    expect(stampOf(math!).atomic).toBe(true);

    // A selection landing inside the formula takes the whole formula.
    const range = document.createRange();
    range.selectNodeContents(math!);
    const offsets = offsetsForRange(container, range)!;
    expect(content.slice(offsets.start, offsets.end)).toContain("QK^T");
  });

  it("treats an escaped character as atomic rather than measuring past it", () => {
    const content = "a \\*literal\\* asterisk";
    const container = render(content);

    const runs = stamped(container);
    const atomic = runs.filter((element) => stampOf(element).atomic);
    expect(atomic.length).toBeGreaterThan(0);
    // And the sweep still holds for everything measurable around it.
    sweep(content);
  });

  it("holds the source property over a whole reply", () => {
    const content = [
      "# Attention",
      "",
      "The **attention layer** decides which parts matter.",
      "",
      "- **Query (Q):** what a token is looking for",
      "- **Key (K):** what it contains",
      "",
      "> A quoted line with `inline code` in it.",
      "",
      "| Token | Weight |",
      "|---|---:|",
      "| cat | 0.35 |",
      "",
      "```ts",
      "const scores = q.map((value) => value * 2);",
      "```",
      "",
      "And a formula: \\[ \\text{softmax}(QK^T) \\]",
      "",
      "1. first",
      "2. second",
      "",
      "---",
      "",
      "Done. See [the docs](https://example.com).",
    ].join("\n");

    expect(sweep(content)).toBeGreaterThan(10);
  });
});

describe("anchor marks", () => {
  const content = "pgvector uses HNSW indexes, which trade recall for speed.";
  const anchors: AnchorRange[] = [{ edgeId: "e1", start: 33, end: 55 }];

  it("cuts the text at the anchor's boundaries and names the edge", () => {
    const container = render(content, anchors);

    const mark = container.querySelector<HTMLElement>(`mark[${EDGES_ATTRIBUTE}]`)!;
    expect(mark.getAttribute(EDGES_ATTRIBUTE)).toBe("e1");
    expect(mark.textContent).toBe(content.slice(33, 55));
  });

  it("reports both edges on a run two anchors share", () => {
    const container = render(content, [
      { edgeId: "e1", start: 0, end: 26 },
      { edgeId: "e2", start: 14, end: 55 },
    ]);

    const marks = [...container.querySelectorAll<HTMLElement>(`mark[${EDGES_ATTRIBUTE}]`)];
    const shared = marks.find(
      (mark) => (mark.getAttribute(EDGES_ATTRIBUTE) ?? "").split(",").length === 2,
    );
    expect(shared?.textContent).toBe(content.slice(14, 26));
  });

  it("leaves the text intact whatever the anchors do to it", () => {
    const container = render(content, [
      { edgeId: "e1", start: 0, end: 8 },
      { edgeId: "e2", start: 4, end: 20 },
      { edgeId: "e3", start: 33, end: 55 },
    ]);

    expect(container.textContent).toBe(content);
  });
});

describe("anchors on things that are not runs of text", () => {
  it("marks a formula, so a branch off one is visible in the reply", () => {
    // The range a selection inside a formula produces: the whole node.
    const content = ["Scores:", "", "\\[ QK^T \\]", ""].join("\n");
    const start = content.indexOf("\\[");
    const end = content.indexOf("\\]") + 2;

    const container = render(content, [{ edgeId: "e1", start, end }]);
    const mark = container.querySelector<HTMLElement>(`mark[${EDGES_ATTRIBUTE}]`);

    expect(mark).not.toBeNull();
    expect(mark!.getAttribute(EDGES_ATTRIBUTE)).toBe("e1");
    expect(mark!.querySelector(".katex")).not.toBeNull();
  });

  it("marks a whole fenced block the same way", () => {
    const content = ["```ts", "const a = 1;", "```", ""].join("\n");
    const container = render(content, [
      { edgeId: "e2", start: content.indexOf("const"), end: content.indexOf(";") + 1 },
    ]);

    const mark = container.querySelector<HTMLElement>(`mark[${EDGES_ATTRIBUTE}]`);
    expect(mark).not.toBeNull();
    expect(mark!.querySelector("pre")).not.toBeNull();
  });

  it("leaves a formula unmarked when the anchor only overlaps it", () => {
    const content = "before \\[ x \\] after";
    const container = render(content, [{ edgeId: "e3", start: 0, end: 10 }]);

    const marks = [...container.querySelectorAll<HTMLElement>(`mark[${EDGES_ATTRIBUTE}]`)];
    // The text before it is marked; the formula is not swallowed by a range
    // that does not cover it.
    expect(marks.some((mark) => mark.querySelector(".katex") !== null)).toBe(false);
    expect(marks.length).toBeGreaterThan(0);
  });
});
