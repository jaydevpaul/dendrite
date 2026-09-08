/**
 * Reading a browser text selection as offsets into a message's stored text.
 *
 * This is the seam the whole slice turns on, and there are two ways to measure
 * it depending on what the message was rendered with.
 *
 * A message rendered as plain text under `whitespace-pre-wrap` needs no help:
 * pre-wrap preserves every character exactly as stored, so the text in the DOM
 * and the text in the database are the same string and a range over one is a
 * range over the other. That is how the reader's own messages are drawn.
 *
 * A model reply is rendered markdown, where the two strings genuinely differ -
 * `**bold**` on disk is `bold` on screen. There the renderer stamps each run
 * of text with where it began in the stored message, and a selection is
 * measured *within* one stamped run and added to its stamp. So the reply is
 * not measured as one flat string at all; it is measured per run, against
 * positions the markdown parser worked out while it was parsing.
 *
 * Which mode applies is decided by the markup itself - stamped runs present or
 * absent - rather than by a flag passed down from the component, so a turn
 * cannot be rendered one way and measured the other.
 *
 * Offsets here are UTF-16 indices, the units `String` and `Range` work in.
 * Converting them to the code points the API counts is `anchor.ts`'s job and
 * happens at the last moment, on the way out.
 */

import {
  SOURCE_ATOMIC_ATTRIBUTE,
  SOURCE_END_ATTRIBUTE,
  SOURCE_START_ATTRIBUTE,
} from "./source-spans";

/**
 * Marks an element whose text content is exactly one message's stored
 * content, with the message id as its value. One listener over the thread
 * finds the right message by walking up to the nearest of these, so a drag
 * that runs off the end of a reply still anchors to the reply it started in.
 */
export const ANCHOR_SOURCE_ATTRIBUTE = "data-anchor-source";

/**
 * Marks one turn in the thread, branchable or not.
 *
 * Separate from the attribute above, and both are needed. That one says "this
 * element's text is exactly this message's content"; this one says "this is
 * where one message ends and the next begins". A selection running from a
 * reply into the question below it crosses a turn boundary without ever
 * reaching a second *source*, so the source attribute alone cannot see it.
 */
export const TURN_ATTRIBUTE = "data-turn";

export interface SpanSelection {
  messageId: string;
  /** UTF-16 indices into that message's content. */
  start: number;
  end: number;
  /** Where to put the affordance: the last line of the selection. */
  rect: DOMRect;
}

function enclosing(node: Node | null, attribute: string): HTMLElement | null {
  if (node === null) return null;
  const element =
    node.nodeType === Node.ELEMENT_NODE ? (node as HTMLElement) : node.parentElement;
  return element === null ? null : element.closest<HTMLElement>(`[${attribute}]`);
}

/**
 * The part of `range` that lies inside `container`, or null if none of it
 * does. A selection is allowed to start in a reply and run off the end of it;
 * the part outside belongs to another message, or to no message at all, and
 * cannot be described by offsets into this one.
 *
 * `compareBoundaryPoints` reads backwards: the constant names the boundary of
 * the *argument* first and of `this` second, so `END_TO_START` compares this
 * range's start against the container's end.
 */
export function clampToContainer(container: HTMLElement, range: Range): Range | null {
  const whole = container.ownerDocument.createRange();
  whole.selectNodeContents(container);

  // Disjoint in either direction: the selection is entirely past the end of
  // the container, or entirely before its start.
  if (range.compareBoundaryPoints(Range.END_TO_START, whole) >= 0) return null;
  if (range.compareBoundaryPoints(Range.START_TO_END, whole) <= 0) return null;

  const clamped = range.cloneRange();
  if (clamped.compareBoundaryPoints(Range.START_TO_START, whole) < 0) {
    clamped.setStart(whole.startContainer, whole.startOffset);
  }
  if (clamped.compareBoundaryPoints(Range.END_TO_END, whole) > 0) {
    clamped.setEnd(whole.endContainer, whole.endOffset);
  }
  return clamped.collapsed ? null : clamped;
}

interface Stamp {
  start: number;
  end: number;
  /** Text inside cannot be measured, so a touch takes the whole range. */
  atomic: boolean;
}

function readStamp(element: HTMLElement): Stamp | null {
  const start = Number(element.getAttribute(SOURCE_START_ATTRIBUTE));
  const end = Number(element.getAttribute(SOURCE_END_ATTRIBUTE));
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return { start, end, atomic: element.hasAttribute(SOURCE_ATOMIC_ATTRIBUTE) };
}

function stampedElements(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>(`[${SOURCE_START_ATTRIBUTE}]`)];
}

/** A collapsed range at one boundary, for comparing against elements. */
function pointAt(node: Node, offset: number): Range {
  const point = node.ownerDocument!.createRange();
  point.setStart(node, offset);
  point.collapse(true);
  return point;
}

function rangeOf(element: HTMLElement): Range {
  const range = element.ownerDocument.createRange();
  range.selectNode(element);
  return range;
}

/**
 * One boundary of a selection, as an offset into the stored message.
 *
 * Three cases, in order. Inside a stamped run: measure the text from the run's
 * own beginning to the boundary and add the run's stamp. Inside a stamped run
 * that is atomic - a formula, an escape, a code block the highlighter
 * reshaped: take the run's whole range, since a point inside it does not
 * correspond to a single position in the source. And landing in no stamped run
 * at all - the gap between two paragraphs, a list's bullet, the padding under
 * the reply: fall to the nearest stamped run on the side the boundary is
 * facing, which is the closest thing to it that has a real position.
 */
function sourceIndexAt(
  container: HTMLElement,
  node: Node,
  offset: number,
  side: "start" | "end",
): number | null {
  const host = enclosing(node, SOURCE_START_ATTRIBUTE);

  if (host !== null && container.contains(host)) {
    const stamp = readStamp(host);
    if (stamp === null) return null;
    if (stamp.atomic) return side === "start" ? stamp.start : stamp.end;

    const inner = container.ownerDocument.createRange();
    inner.selectNodeContents(host);
    inner.setEnd(node, offset);
    return Math.min(stamp.start + inner.toString().length, stamp.end);
  }

  const stamped = stampedElements(container);
  if (stamped.length === 0) return null;

  const point = pointAt(node, offset);

  if (side === "start") {
    // The first run that begins at or after this point: the selection starts
    // in the whitespace before it.
    const following = stamped.find(
      (element) => point.compareBoundaryPoints(Range.START_TO_START, rangeOf(element)) <= 0,
    );
    const fallback = readStamp(stamped[stamped.length - 1]);
    return following !== undefined
      ? (readStamp(following)?.start ?? null)
      : (fallback?.end ?? null);
  }

  // The last run that ends at or before this point, for the same reason
  // mirrored: the selection ran off the end of it into whitespace.
  const preceding = [...stamped]
    .reverse()
    .find((element) => point.compareBoundaryPoints(Range.END_TO_END, rangeOf(element)) >= 0);
  const fallback = readStamp(stamped[0]);
  return preceding !== undefined ? (readStamp(preceding)?.end ?? null) : (fallback?.start ?? null);
}

/**
 * The source range spanned by every stamped run the selection touches.
 *
 * Used only when resolving the two boundaries separately fails. It cannot
 * describe a partial selection - a run is in or out - so it is the coarse
 * answer, not the normal one.
 */
function touchedRange(
  container: HTMLElement,
  range: Range,
): { start: number; end: number } | null {
  let start = Number.POSITIVE_INFINITY;
  let end = Number.NEGATIVE_INFINITY;

  for (const element of stampedElements(container)) {
    if (!range.intersectsNode(element)) continue;
    const stamp = readStamp(element);
    if (stamp === null) continue;
    start = Math.min(start, stamp.start);
    end = Math.max(end, stamp.end);
  }

  return end > start ? { start, end } : null;
}

/**
 * UTF-16 offsets of `range` within the stored text `container` renders.
 *
 * The flat path measures with `Range.toString()`, which concatenates the data
 * of the text nodes it spans and nothing else. That is the stored string, not
 * the rendered one -- `Selection.toString()` and `innerText` both apply layout
 * rules that collapse whitespace, which is the one thing that must not happen
 * here.
 *
 * The stamped path never measures across the whole container, because the
 * characters between two runs -- a fence's backticks, the blank line between
 * paragraphs -- are in the stored string and not in the DOM at all. Each
 * boundary is resolved on its own and the two are checked against each other
 * afterwards.
 */
export function offsetsForRange(
  container: HTMLElement,
  range: Range,
): { start: number; end: number } | null {
  const clamped = clampToContainer(container, range);
  if (clamped === null) return null;

  if (stampedElements(container).length > 0) {
    const start = sourceIndexAt(
      container,
      clamped.startContainer,
      clamped.startOffset,
      "start",
    );
    const end = sourceIndexAt(container, clamped.endContainer, clamped.endOffset, "end");

    if (start !== null && end !== null && end > start) return { start, end };

    // The two boundaries crossed, which happens when neither sits in a stamped
    // run: one fallback looks forward and the other back, and they pass each
    // other. Widening to the runs the selection actually touches is coarser
    // than the reader asked for and still describes what they highlighted --
    // whereas answering null here withdraws the offer with nothing on screen
    // explaining why, and *that* was the bug: one mark in a reply and
    // branching quietly stopped working on it.
    return touchedRange(container, clamped);
  }

  const before = container.ownerDocument.createRange();
  before.selectNodeContents(container);
  before.setEnd(clamped.startContainer, clamped.startOffset);

  const start = before.toString().length;
  return { start, end: start + clamped.toString().length };
}

/**
 * The current selection, if it lies in exactly one message's text.
 *
 * **A highlight that reaches a second message is not offered as a branch.** An
 * anchor is one link into one parent, so a selection across two messages could
 * only ever be honoured as a fragment of the first -- and clamping it silently
 * would hand back a branch off less text than was highlighted, with nothing
 * saying so. Refusing is the honest answer: nothing appears, and a second drag
 * inside one reply works.
 *
 * Overshooting into the padding below a reply is still fine. That is not
 * another message, so the part outside the text is trimmed away and the offer
 * stands -- which is what makes the rule "don't cross into another message"
 * rather than "don't leave the element".
 */
export function readSpanSelection(): SpanSelection | null {
  const selection = window.getSelection();
  if (selection === null || selection.rangeCount === 0 || selection.isCollapsed) return null;

  const range = selection.getRangeAt(0);
  const container = enclosing(range.startContainer, ANCHOR_SOURCE_ATTRIBUTE);
  if (container === null) return null;

  const messageId = container.getAttribute(ANCHOR_SOURCE_ATTRIBUTE);
  if (messageId === null || messageId === "") return null;

  // The end may sit outside every turn -- the thread's own padding, the gap
  // under the last reply. What it may not do is sit inside a different turn,
  // whether that turn is branchable or not.
  const startTurn = enclosing(range.startContainer, TURN_ATTRIBUTE);
  const endTurn = enclosing(range.endContainer, TURN_ATTRIBUTE);
  if (endTurn !== null && endTurn !== startTurn) return null;

  const offsets = offsetsForRange(container, range);
  if (offsets === null) return null;

  const clamped = clampToContainer(container, range);
  if (clamped === null) return null;

  // The last line of the selection, so the affordance lands where the drag
  // ended rather than above the first line of a five-line highlight.
  const rects = clamped.getClientRects();
  const rect = rects.length > 0 ? rects[rects.length - 1] : clamped.getBoundingClientRect();

  return { messageId, start: offsets.start, end: offsets.end, rect };
}

/** Drop the highlight, so the affordance cannot outlive the selection it names. */
export function clearSelection() {
  window.getSelection()?.removeAllRanges();
}
