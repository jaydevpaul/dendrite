import { describe, expect, it } from "vitest";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkRehype from "remark-rehype";
import rehypeStringify from "rehype-stringify";
import { rehypeSourceSpans } from "./source-spans";
import { ANCHOR_SOURCE_ATTRIBUTE, TURN_ATTRIBUTE, readSpanSelection } from "./selection";
import type { AnchorRange } from "./anchor";

/**
 * The selection layer over a *rendered* reply, in the shape the thread really
 * builds: a turn, a selection surface inside it, and stamped runs inside that.
 *
 * The case that matters most is the second one below. A reply that already has
 * a branch off it renders a mark, and the mark is a component - so if the
 * stamps the renderer put on that run do not survive into the DOM, then
 * highlighting anything inside or after it stops offering a branch. The reply
 * looks completely normal; branching just quietly stops working on it, which
 * is exactly the kind of failure a test has to hold down.
 */
function thread(content: string, anchors: AnchorRange[] = []): void {
  const html = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkRehype)
    .use(rehypeSourceSpans, { content, anchors })
    .use(rehypeStringify)
    .processSync(content)
    .toString();

  document.body.innerHTML = `
    <div id="thread">
      <article ${TURN_ATTRIBUTE}="m1">
        <div ${ANCHOR_SOURCE_ATTRIBUTE}="m1">${html}</div>
      </article>
    </div>`;
}

/** The rendered text node whose content is exactly `text`. */
function textNode(text: string): Text {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    if (walker.currentNode.textContent === text) return walker.currentNode as Text;
  }
  throw new Error(`no text node reading exactly ${JSON.stringify(text)}`);
}

function select(node: Node, from: number, to: number): void {
  const range = document.createRange();
  range.setStart(node, from);
  range.setEnd(node, to);
  const selection = window.getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
}

/** jsdom does no layout, and only the affordance's position depends on it. */
const NOWHERE = { top: 0, bottom: 0, left: 0, width: 0, height: 0 } as DOMRect;
if (typeof Range.prototype.getClientRects !== "function") {
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => NOWHERE;
}

const CONTENT = "pgvector uses **HNSW indexes**, which trade recall for speed.";

describe("selecting inside a rendered reply", () => {
  it("offers a branch off a phrase in the prose", () => {
    thread(CONTENT);
    const node = textNode("pgvector uses ");
    select(node, 0, 8);

    expect(readSpanSelection()).toMatchObject({ messageId: "m1", start: 0, end: 8 });
  });

  it("reports source offsets, not the offsets on screen", () => {
    thread(CONTENT);
    const node = textNode("HNSW indexes");
    select(node, 0, 4);

    const found = readSpanSelection()!;
    expect(CONTENT.slice(found.start, found.end)).toBe("HNSW");
  });

  it("still offers a branch on a reply that already has one", () => {
    // The span "trade recall for speed" already carries a branch, so that run
    // renders as a mark.
    const start = CONTENT.indexOf("trade");
    thread(CONTENT, [{ edgeId: "e1", start, end: start + "trade recall for speed".length }]);

    const node = textNode("pgvector uses ");
    select(node, 0, 8);
    expect(readSpanSelection()).toMatchObject({ start: 0, end: 8 });
  });

  it("offers a branch off text inside an existing mark", () => {
    const start = CONTENT.indexOf("trade");
    thread(CONTENT, [{ edgeId: "e1", start, end: start + "trade recall for speed".length }]);

    const node = textNode("trade recall for speed");
    select(node, 6, 12);

    const found = readSpanSelection()!;
    expect(CONTENT.slice(found.start, found.end)).toBe("recall");
  });
});
