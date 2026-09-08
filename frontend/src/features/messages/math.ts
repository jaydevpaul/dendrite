/**
 * The model writes LaTeX with backslash delimiters; the markdown parser reads
 * dollar signs. This translates between them **without changing the length of
 * the string**, which is the only reason it is allowed to run at all.
 *
 * Anchors are offsets into the stored message, so anything that rewrites the
 * text before parsing would shift every position after it and put the whole
 * mapping out. Each delimiter here is two characters going in and two coming
 * out, so every character keeps its index and the parser's positions are
 * still positions in the stored string. The swap is asserted rather than
 * trusted: a mismatch returns the original text and the math simply renders
 * as the literal backslashes the model sent, which is a cosmetic problem
 * instead of a silently wrong anchor.
 *
 * Both display and inline become `$$`. Single `$` math is deliberately left
 * off - prose about money would otherwise turn into formulae the moment two
 * dollar amounts appeared in one paragraph.
 */

/** Fences suspend the swap: LaTeX shown as an example is not LaTeX to render. */
const FENCE = /^\s{0,3}(`{3,}|~{3,})/;

function swapDelimiters(line: string): string {
  return line
    .replace(/\\\[/g, "$$$$")
    .replace(/\\\]/g, "$$$$")
    .replace(/\\\(/g, "$$$$")
    .replace(/\\\)/g, "$$$$");
}

export function normalizeMathDelimiters(content: string): string {
  if (!content.includes("\\[") && !content.includes("\\(")) return content;

  const lines = content.split("\n");
  let fence: string | null = null;

  const swapped = lines.map((line) => {
    const opener = FENCE.exec(line);

    if (fence !== null) {
      // Inside a fence. Only a matching closer of at least the same length
      // ends it, which is how nested examples stay intact.
      if (opener !== null && opener[1][0] === fence[0] && opener[1].length >= fence.length) {
        fence = null;
      }
      return line;
    }

    if (opener !== null) {
      fence = opener[1];
      return line;
    }

    return swapDelimiters(line);
  });

  const result = swapped.join("\n");

  // The whole design depends on this. If it ever fails, render the original.
  return result.length === content.length ? result : content;
}
