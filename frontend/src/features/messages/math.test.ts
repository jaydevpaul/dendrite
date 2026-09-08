import { describe, expect, it } from "vitest";
import { normalizeMathDelimiters } from "./math";

/**
 * One property carries this whole module: the string that comes out is the
 * same length as the string that went in. Anchors are offsets into the stored
 * message, and the parser's positions are taken from the normalised copy, so a
 * single character of drift here silently moves every anchor after it.
 */
describe("normalizeMathDelimiters", () => {
  it("leaves text with no LaTeX delimiters exactly as it was", () => {
    const content = "No maths here, just prose about $5 and $6.";
    expect(normalizeMathDelimiters(content)).toBe(content);
  });

  it("turns display delimiters into dollars without moving anything", () => {
    const content = "Scores:\n\n\\[ QK^T \\]\n";
    const result = normalizeMathDelimiters(content);

    expect(result).toBe("Scores:\n\n$$ QK^T $$\n");
    expect(result).toHaveLength(content.length);
  });

  it("turns inline delimiters into dollars too", () => {
    const content = "the vector \\(d_k\\) scales it";
    const result = normalizeMathDelimiters(content);

    expect(result).toBe("the vector $$d_k$$ scales it");
    expect(result).toHaveLength(content.length);
  });

  it("leaves LaTeX inside a fence alone, because there it is the example", () => {
    const content = ["Write it like this:", "", "```latex", "\\[ x^2 \\]", "```", ""].join("\n");
    expect(normalizeMathDelimiters(content)).toBe(content);
  });

  it("resumes swapping after the fence closes", () => {
    const content = ["```", "\\[ shown \\]", "```", "", "\\[ rendered \\]"].join("\n");
    const result = normalizeMathDelimiters(content);

    expect(result).toContain("\\[ shown \\]");
    expect(result).toContain("$$ rendered $$");
    expect(result).toHaveLength(content.length);
  });

  it("keeps the length whatever the mix of delimiters", () => {
    const content = [
      "One \\(a\\) and \\[b\\]",
      "",
      "```py",
      "print('\\\\[not maths\\\\]')",
      "```",
      "",
      "\\[",
      "c = a + b",
      "\\]",
    ].join("\n");

    expect(normalizeMathDelimiters(content)).toHaveLength(content.length);
  });
});
