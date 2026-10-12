import { describe, expect, it } from "vitest";
import { plainPreview } from "./preview";

/**
 * The cases these tests exist for came off the screen, in this order: a
 * navigator row reading `**attention layer**`, a branch quoting
 * `\[ \text{score}(Q,K) = QK^T \]`, and a table row quoted as a run of pipes.
 * Anything a model actually writes and this app then quotes in one line
 * belongs here.
 */
describe("plainPreview", () => {
  it("takes the markers off emphasis and keeps the words", () => {
    expect(plainPreview("The **attention layer** is the *mechanism* that lets")).toBe(
      "The attention layer is the mechanism that lets",
    );
  });

  it("reads a formula as the expression, not as LaTeX", () => {
    expect(plainPreview("\\[ \\text{score}(Q,K) = QK^T \\]")).toBe(
      "score(Q,K) = QK^T",
    );
  });

  it("keeps a command's name rather than dropping it", () => {
    // Losing it entirely would turn "\alpha decays" into "decays", which
    // reads as prose and is wrong.
    expect(plainPreview("$$\\alpha \\to \\beta$$")).toBe("alpha to beta");
  });

  it("drops a heading's hashes and a quote's bracket", () => {
    expect(plainPreview("## Core idea\n\n> a quoted line")).toBe(
      "Core idea a quoted line",
    );
  });

  it("turns a list into its items", () => {
    expect(plainPreview("- **Query (Q):** what it wants\n- **Key (K):** what it has")).toBe(
      "Query (Q): what it wants Key (K): what it has",
    );
  });

  it("keeps a table's cells and drops its rules", () => {
    const table = "| Token | Weight |\n|---|---:|\n| cat | 0.35 |";
    expect(plainPreview(table)).toBe("Token · Weight · cat · 0.35");
  });

  it("keeps fenced code and drops the fence", () => {
    expect(plainPreview("Try:\n\n```python\nprint(1)\n```\n")).toBe("Try: print(1)");
  });

  it("reads a link as its text", () => {
    expect(plainPreview("see [the docs](https://example.com) for more")).toBe(
      "see the docs for more",
    );
  });

  it("reads an image as its alt text", () => {
    expect(plainPreview("![a diagram](x.png) above")).toBe("a diagram above");
  });

  it("restores an escaped character rather than eating it", () => {
    expect(plainPreview("a \\*literal\\* asterisk")).toBe("a *literal* asterisk");
  });

  it("collapses every run of whitespace into one line", () => {
    expect(plainPreview("first\n\n\nsecond   third\n")).toBe("first second third");
  });

  it("leaves ordinary prose completely alone", () => {
    const prose = "Why does that matter for retrieval?";
    expect(plainPreview(prose)).toBe(prose);
  });

  it("answers an empty string for text that was only syntax", () => {
    // The callers show their own fallback, so this has to be empty rather
    // than a stray bullet or a lone separator.
    expect(plainPreview("---")).toBe("");
    expect(plainPreview("")).toBe("");
  });
});
