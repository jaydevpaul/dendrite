import type { Element, ElementContent, Root, RootContent, Text } from "hast";
import type { AnchorRange } from "./anchor";

/**
 * The bridge between a rendered reply and the offsets an anchor is written in.
 *
 * Rendering markdown breaks the equality the selection layer used to rely on:
 * `**bold**` in the stored message is `bold` on screen, a list item loses its
 * `- `, and a fence's backticks are gone entirely. Measuring a highlight
 * against the rendered text would therefore write anchors that point a few
 * characters off, and the further down the reply you highlight the worse it
 * gets.
 *
 * So the renderer carries the source positions down into the DOM. Every run of
 * text that came from the source verbatim is wrapped in a span stamped with
 * where it started in the stored string, and a selection is measured *within*
 * one of those spans and added to its stamp. What the markdown parser already
 * knows is written into the markup rather than reconstructed later by
 * guesswork.
 *
 * **Every stamp is checked against the source before it is emitted.** A node
 * whose rendered text is not literally the source slice it claims - an escape
 * like a backslashed asterisk, an entity, a KaTeX formula that is a whole DOM
 * tree rather than a string - is stamped *atomic* instead: it still knows its
 * source range, but a selection touching it takes that range whole rather than
 * measuring inside it. An anchor a few characters out is a 422 from the API in
 * the good case and a mark over the wrong words in the bad one, so a coarser
 * anchor is the right trade and a wrong one is not on the table.
 */

/** Where this element's text begins in the stored message. */
export const SOURCE_START_ATTRIBUTE = "data-src-start";
/** Where it ends. Only meaningful together with the attribute above. */
export const SOURCE_END_ATTRIBUTE = "data-src-end";
/**
 * Present when the element's text does not equal its source slice, so offsets
 * inside it cannot be measured and the whole range is taken instead.
 */
export const SOURCE_ATOMIC_ATTRIBUTE = "data-src-atomic";
/** Comma-separated edge ids of the branches whose spans cover this run. */
export const EDGES_ATTRIBUTE = "data-edges";

export interface SourceSpansOptions {
  /** The stored message text, exactly as the offsets will be counted against. */
  content: string;
  /** Branch spans to mark. Empty while a reply is still streaming. */
  anchors?: AnchorRange[];
}

function classNames(element: Element): string[] {
  const className = element.properties?.className;
  return Array.isArray(className) ? className.map(String) : [String(className ?? "")];
}

/**
 * KaTeX renders a formula as a tree with the same characters in it twice -
 * once for sighted readers and once as MathML - so there is no honest mapping
 * from a point inside it back to one offset.
 */
function isRenderedMath(element: Element): boolean {
  return element.tagName === "math" || classNames(element).some((n) => n.startsWith("katex"));
}

/** Everything a node renders as text, in order. */
function textOf(node: RootContent | Root): string {
  if (node.type === "text") return node.value;
  if (node.type === "element" || node.type === "root") {
    return node.children.map(textOf).join("");
  }
  return "";
}

function span(
  start: number,
  end: number,
  children: ElementContent[],
  extra: Record<string, string> = {},
): Element {
  return {
    type: "element",
    tagName: "span",
    properties: {
      [SOURCE_START_ATTRIBUTE]: String(start),
      [SOURCE_END_ATTRIBUTE]: String(end),
      ...extra,
    },
    children,
  };
}

function atomic(start: number, end: number, children: ElementContent[]): Element {
  return span(start, end, children, { [SOURCE_ATOMIC_ATTRIBUTE]: "" });
}

/** The ids of the anchors that cover the whole run [from, to). */
function coveringEdges(anchors: AnchorRange[], from: number, to: number): string[] {
  return anchors
    .filter((anchor) => anchor.start <= from && anchor.end >= to)
    .map((anchor) => anchor.edgeId);
}

/**
 * One text node becomes one or more stamped spans, cut at every anchor
 * boundary that falls inside it.
 *
 * The cutting is the same boundary sweep the plain-text renderer used: two
 * branches may be anchored on spans that share a word, so a run covered by
 * both has to report both rather than one mark overwriting the other.
 */
function splitText(node: Text, options: SourceSpansOptions): ElementContent[] {
  const position = node.position;
  if (position?.start.offset === undefined || position.end.offset === undefined) {
    // No position to trust. Left as bare text: the selection layer then falls
    // back to the nearest stamped neighbour rather than measuring in here.
    return [node];
  }

  const start = position.start.offset;
  const end = position.end.offset;

  // The guard the whole design rests on. An escape, an entity or a character
  // reference makes the rendered value shorter than the source it came from,
  // and arithmetic inside such a run would drift.
  if (options.content.slice(start, end) !== node.value) {
    return [atomic(start, end, [node])];
  }

  const anchors = options.anchors ?? [];
  const cuts = new Set<number>([start, end]);
  for (const anchor of anchors) {
    if (anchor.start > start && anchor.start < end) cuts.add(anchor.start);
    if (anchor.end > start && anchor.end < end) cuts.add(anchor.end);
  }

  const boundaries = [...cuts].sort((a, b) => a - b);
  const pieces: ElementContent[] = [];

  for (let index = 0; index < boundaries.length - 1; index += 1) {
    const from = boundaries[index];
    const to = boundaries[index + 1];
    const text: Text = { type: "text", value: options.content.slice(from, to) };
    const edges = coveringEdges(anchors, from, to);

    if (edges.length === 0) {
      pieces.push(span(from, to, [text]));
      continue;
    }

    pieces.push({
      type: "element",
      tagName: "mark",
      properties: {
        [SOURCE_START_ATTRIBUTE]: String(from),
        [SOURCE_END_ATTRIBUTE]: String(to),
        [EDGES_ATTRIBUTE]: edges.join(","),
      },
      children: [text],
    });
  }

  return pieces;
}

/**
 * A fenced block's text *is* its source, character for character, so the
 * `<code>` element can be stamped once and measured inside - even though
 * highlighting has since cut it into dozens of coloured spans, which only
 * wrap the text and never change it.
 *
 * The content starts after the opening fence's line, and the search for that
 * line break is why this is not simply the node's own start offset. An
 * indented block has no fence at all and starts where it starts. Either way
 * the result is verified before it is used.
 */
function stampCodeBlock(pre: Element, options: SourceSpansOptions): void {
  const code = pre.children.find(
    (child): child is Element => child.type === "element" && child.tagName === "code",
  );
  const target = code ?? pre;
  const position = target.position ?? pre.position;
  if (position?.start.offset === undefined || position.end.offset === undefined) return;

  const text = textOf(target);
  const opener = options.content[position.start.offset];
  const fenced = opener === "`" || opener === "~";

  let start = position.start.offset;
  if (fenced) {
    const lineBreak = options.content.indexOf("\n", position.start.offset);
    if (lineBreak === -1) return;
    start = lineBreak + 1;
  }

  target.properties = target.properties ?? {};

  if (options.content.slice(start, start + text.length) === text) {
    target.properties[SOURCE_START_ATTRIBUTE] = String(start);
    target.properties[SOURCE_END_ATTRIBUTE] = String(start + text.length);
    return;
  }

  // Some transformation moved the text - a highlighter that normalised a tab,
  // say. The block still knows where it came from, so it becomes atomic
  // rather than unbranchable.
  target.properties[SOURCE_START_ATTRIBUTE] = String(position.start.offset);
  target.properties[SOURCE_END_ATTRIBUTE] = String(position.end.offset);
  target.properties[SOURCE_ATOMIC_ATTRIBUTE] = "";
}

function stampAtomicElement(element: Element): void {
  const position = element.position;
  if (position?.start.offset === undefined || position.end.offset === undefined) return;
  element.properties = element.properties ?? {};
  element.properties[SOURCE_START_ATTRIBUTE] = String(position.start.offset);
  element.properties[SOURCE_END_ATTRIBUTE] = String(position.end.offset);
  element.properties[SOURCE_ATOMIC_ATTRIBUTE] = "";
}

function stampRangeOf(element: Element): { start: number; end: number } | null {
  const start = Number(element.properties?.[SOURCE_START_ATTRIBUTE]);
  const end = Number(element.properties?.[SOURCE_END_ATTRIBUTE]);
  return Number.isFinite(start) && Number.isFinite(end) && end > start ? { start, end } : null;
}

/**
 * A branch can be anchored on something that is not a run of text at all - a
 * formula, a whole code block - and then there is no text node to cut, so the
 * mark has to go round the node itself.
 *
 * Leaving this out was a real failure and a quiet one: the anchor still
 * resolved, so the branch counted as marked and was left off the list of
 * branches shown under the message, while nothing was drawn in the reply
 * either. The branch existed and could not be reached from anywhere.
 *
 * Only a range that covers the node completely marks it. A selection inside
 * one of these takes its whole range anyway, so that is what an anchor off a
 * formula looks like; a range that merely overlaps it belongs to the text on
 * one side and gets its mark there.
 */
function markWhole(element: Element, options: SourceSpansOptions): ElementContent {
  const stamped = stampRangeOf(element);
  const code =
    element.tagName === "pre"
      ? element.children.find(
          (child): child is Element => child.type === "element" && child.tagName === "code",
        )
      : undefined;
  const range = stamped ?? (code !== undefined ? stampRangeOf(code) : null);
  if (range === null) return element;

  // Compared against the range with its surrounding whitespace trimmed off.
  // An anchor drops whitespace at both ends - a highlight is described by the
  // characters it names - so an anchor over a whole fenced block stops one
  // character short of the newline before the closing fence, and asking for
  // literal coverage would mean a code block could never be marked at all.
  const inner = options.content.slice(range.start, range.end);
  const from = range.start + (inner.length - inner.trimStart().length);
  const to = range.end - (inner.length - inner.trimEnd().length);

  const edges = coveringEdges(options.anchors ?? [], from, Math.max(to, from + 1));
  if (edges.length === 0) return element;

  return {
    type: "element",
    tagName: "mark",
    properties: {
      [SOURCE_START_ATTRIBUTE]: String(range.start),
      [SOURCE_END_ATTRIBUTE]: String(range.end),
      [EDGES_ATTRIBUTE]: edges.join(","),
    },
    children: [element],
  };
}

function walk(parent: Root | Element, options: SourceSpansOptions): void {
  const children: (RootContent | ElementContent)[] = [];

  for (const child of parent.children) {
    if (child.type === "text") {
      children.push(...splitText(child, options));
      continue;
    }

    if (child.type !== "element") {
      children.push(child);
      continue;
    }

    if (isRenderedMath(child)) {
      stampAtomicElement(child);
    } else if (child.tagName === "pre") {
      stampCodeBlock(child, options);
    } else if (child.properties?.[SOURCE_ATOMIC_ATTRIBUTE] === undefined) {
      walk(child, options);
    }

    // Wrapped last, so the node it wraps has already been stamped. Anything
    // walked into was marked from the inside and comes back unchanged.
    children.push(markWhole(child, options));
  }

  parent.children = children as typeof parent.children;
}

/**
 * The rehype plugin. Runs last, after highlighting and after KaTeX, because it
 * reads the tree those two leave behind.
 */
export function rehypeSourceSpans(options: SourceSpansOptions) {
  return (tree: Root) => {
    walk(tree, options);
  };
}

/**
 * The one pass that has to run *before* KaTeX.
 *
 * KaTeX does not decorate the formula it is given, it replaces it: the element
 * carrying the source position disappears and what takes its place was built
 * from a string, with no position at all. So the range is recorded first, in a
 * wrapper that survives the substitution. Without this a highlight touching a
 * formula has nothing stamped to resolve against and falls back to the nearest
 * text on either side - not wrong, but coarse enough that a branch off a line
 * of maths would quote the sentence above it.
 *
 * Takes no options: the positions it needs are already on the tree, so unlike
 * the pass below it never has to compare anything against the source.
 */
export function rehypeStampMath() {
  return (tree: Root) => {
    const wrap = (parent: Root | Element): void => {
      parent.children = parent.children.map((child) => {
        if (child.type !== "element") return child;

        const kind = mathKind(child);
        const position = child.position;

        if (kind === null || position?.start.offset === undefined || position.end.offset === undefined) {
          wrap(child);
          return child;
        }

        return {
          type: "element",
          // A display formula is a block, and a span wrapped round a block is
          // markup the browser will rearrange.
          tagName: kind === "display" ? "div" : "span",
          properties: {
            [SOURCE_START_ATTRIBUTE]: String(position.start.offset),
            [SOURCE_END_ATTRIBUTE]: String(position.end.offset),
            [SOURCE_ATOMIC_ATTRIBUTE]: "",
          },
          children: [child],
        } satisfies Element;
      }) as typeof parent.children;
    };

    wrap(tree);
  };
}

/**
 * Math arrives from the parser as a `code` element with a language class, and
 * a display formula arrives inside a `pre` that KaTeX replaces whole - so for
 * that one it is the `pre` that has to be wrapped, or the wrapper goes with it.
 */
function mathKind(element: Element): "inline" | "display" | null {
  const own = classNames(element);
  if (own.includes("math-inline")) return "inline";
  if (own.includes("math-display")) return "display";

  if (element.tagName !== "pre") return null;

  const code = element.children.find(
    (child): child is Element => child.type === "element" && child.tagName === "code",
  );
  return code !== undefined && classNames(code).includes("math-display") ? "display" : null;
}
