/**
 * A message reduced to one line of plain prose.
 *
 * Everywhere a reply is *quoted* rather than read - a navigator row, a graph
 * card, a branch crumb, the span above the branch composer - it has to be
 * plain text. The stored message is markdown, so quoting it verbatim shows the
 * reader `**attention layer**` and `\[ \text{score}(Q,K) = QK^T \]` where a
 * phrase belongs, which is the same failure as not rendering a reply at all,
 * only in miniature.
 *
 * This is deliberately **not** a markdown parser. A preview has no structure -
 * it is one line - so what is wanted is the words with the syntax taken off,
 * and running the real pipeline to get them would mean rendering to a DOM and
 * reading its text back for every row in a list.
 *
 * It is also **only** for previews. Nothing anchored is computed from this
 * output: an anchor's offsets are always counted against the stored string, so
 * this can shorten and rewrite as freely as it likes with no risk of moving a
 * branch.
 */

/** LaTeX commands whose argument is ordinary text worth keeping. */
const TEXT_COMMANDS = /\\(?:text|mathrm|mathbf|mathit|operatorname)\{([^{}]*)\}/g;

/** How the app separates facts elsewhere, so a table's cells read the same. */
const CELL = "·";

export function plainPreview(markdown: string): string {
  // Maths first, and this order is the one thing here that is not arbitrary.
  // `\[` is a LaTeX delimiter to this app - the renderer rewrites it to `$$`
  // for exactly that reason - but read as markdown it is an escaped bracket,
  // so anything that handled escapes earlier would leave the brackets in and
  // the formula wrapped in them.
  let text = markdown.replace(/\\\[|\\\]|\\\(|\\\)|\$\$|\$/g, " ");

  // Fenced code: keep the code, drop the fence and the language tag. A
  // preview that said "```python" would be quoting punctuation.
  text = text.replace(/```[^\n]*\n?/g, " ").replace(/~~~[^\n]*\n?/g, " ");

  // Images before links, or the alt text keeps its leading "!".
  text = text.replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1");
  text = text.replace(/\[([^\]]*)\]\([^)]*\)/g, "$1");

  // A \text{...} keeps its words; every other command loses the backslash and
  // keeps its name, so `\alpha` reads as "alpha" rather than vanishing.
  text = text.replace(TEXT_COMMANDS, "$1");
  text = text.replace(/\\([a-zA-Z]+)/g, "$1");
  text = text.replace(/(?<!\\)[{}]/g, "");

  // Block furniture, at the start of a line only: a heading's hashes, a
  // quote's angle bracket, a list's bullet or number, a horizontal rule.
  text = text.replace(/^[ \t]{0,3}#{1,6}[ \t]+/gm, "");
  text = text.replace(/^[ \t]{0,3}>[ \t]?/gm, "");
  text = text.replace(/^[ \t]{0,3}(?:[-*+]|\d+[.)])[ \t]+/gm, "");
  text = text.replace(/^[ \t]{0,3}(?:[-*_][ \t]*){3,}$/gm, " ");

  // A table row becomes its cells. The alignment row is punctuation and goes
  // entirely; the pipes at either end of every row would otherwise leave a
  // separator dangling, which is why runs of them are collapsed below rather
  // than trimmed only at the ends of the line.
  text = text.replace(
    /^[ \t]{0,3}\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*$/gm,
    " ",
  );
  text = text.replace(/[ \t]*\|[ \t]*/g, ` ${CELL} `);

  // Emphasis, strikethrough and inline code: the markers only, never the
  // words inside them. The lookbehind is what keeps an escaped asterisk -
  // written `\*` - out of it, so the line below can restore it as a literal
  // rather than as a marker that was already thrown away.
  text = text.replace(/(?<!\\)(\*\*|__|~~|\*|_|`)/g, "");
  text = text.replace(/\\([\\`*_{}[\]()#+\-.!|>~])/g, "$1");

  return text
    .replace(/\s+/g, " ")
    .replace(new RegExp(`(?:${CELL}\\s*)+`, "g"), `${CELL} `)
    .replace(new RegExp(`^(?:\\s|${CELL})+|(?:\\s|${CELL})+$`, "g"), "");
}
