import type { Edge } from "./api";

/**
 * Anchors, and the one conversion that makes them line up.
 *
 * An anchor is three fields on the edge: two offsets into the parent
 * message's stored text, and the text those offsets point at. The API refuses
 * the write unless `content[start:end]` is exactly the text sent, so the
 * offsets have to be computed in the same units the server counts in, and
 * they are not the units the browser counts in.
 *
 * **The browser counts UTF-16 code units; Python counts code points.** A
 * string with one emoji in it has a `.length` of 2 in JavaScript for a
 * character Python considers one, so every offset after that emoji is one too
 * high. The write then fails as a 422 saying the text does not match at that
 * offset -- and in the worse case, where the highlighted words appear twice in
 * the reply, it succeeds while pointing at the wrong copy. So the two spaces
 * are kept strictly apart here: everything that touches the DOM works in
 * UTF-16 indices, everything that crosses the wire is converted to code
 * points, and the conversion is these two functions.
 */

/** The three fields the API wants together, in code points. */
export interface AnchorPayload {
  anchor_start: number;
  anchor_end: number;
  anchored_text: string;
}

/** A resolved anchor, in the UTF-16 indices the DOM and `String` use. */
export interface AnchorRange {
  /** The edge this range belongs to, so a click can find its branch. */
  edgeId: string;
  start: number;
  end: number;
}

/** True when `index` opens a surrogate pair, i.e. one character in two units. */
function isPairAt(text: string, index: number): boolean {
  const code = text.charCodeAt(index);
  if (code < 0xd800 || code > 0xdbff) return false;
  const next = text.charCodeAt(index + 1);
  return next >= 0xdc00 && next <= 0xdfff;
}

/**
 * A UTF-16 index landing between the two halves of one character is snapped
 * back to the start of that character. A browser will not normally hand one
 * out, but an index arrived at by arithmetic can be, and half a character in
 * an offset is a mismatch the server can only answer with a 422.
 */
function snapToCharacter(text: string, index: number): number {
  const code = text.charCodeAt(index);
  const isLowHalf = code >= 0xdc00 && code <= 0xdfff;
  return isLowHalf && index > 0 && isPairAt(text, index - 1) ? index - 1 : index;
}

/** UTF-16 index → the code-point offset the API counts in. */
export function toCodePointOffset(text: string, utf16Index: number): number {
  const limit = snapToCharacter(text, Math.min(Math.max(utf16Index, 0), text.length));
  let offset = 0;
  let index = 0;
  while (index < limit) {
    index += isPairAt(text, index) ? 2 : 1;
    offset += 1;
  }
  return offset;
}

/** The reverse, for rendering a stored anchor back into the browser's text. */
export function toUtf16Index(text: string, codePointOffset: number): number {
  let index = 0;
  let seen = 0;
  while (index < text.length && seen < codePointOffset) {
    index += isPairAt(text, index) ? 2 : 1;
    seen += 1;
  }
  return index;
}

/**
 * A highlighted range in the browser turned into the three fields to send.
 *
 * Whitespace at either end is dropped and the offsets move with it, so the
 * anchor still describes exactly the characters it names. A drag that
 * overshoots the last word by a space is the normal way to select text, and
 * an anchor with a trailing newline in it would be sent verbatim into the
 * composed prompt.
 *
 * Returns null when there is nothing left to anchor -- a collapsed range, or
 * a selection of nothing but whitespace, both of which the API refuses.
 */
export function anchorFromUtf16(
  content: string,
  startIndex: number,
  endIndex: number,
): AnchorPayload | null {
  const low = snapToCharacter(content, Math.min(Math.max(startIndex, 0), content.length));
  const high = snapToCharacter(content, Math.min(Math.max(endIndex, 0), content.length));
  if (high <= low) return null;

  const raw = content.slice(low, high);
  const leading = raw.length - raw.trimStart().length;
  const trailing = raw.length - raw.trimEnd().length;
  const start = low + leading;
  const end = high - trailing;
  if (end <= start) return null;

  return {
    anchor_start: toCodePointOffset(content, start),
    anchor_end: toCodePointOffset(content, end),
    anchored_text: content.slice(start, end),
  };
}

/**
 * Where a stored anchor sits in the text as the browser measures it.
 *
 * The stored text is checked against the offsets rather than trusted. They
 * agreed when the edge was written -- the service refuses the write
 * otherwise -- so a disagreement now means the parent message was edited
 * underneath the anchor. Relocating it is the backend's repair job and does
 * not exist yet, so the range is simply not drawn: an unmarked span is
 * honest, a span drawn at stale offsets highlights the wrong words.
 */
export function resolveAnchor(content: string, edge: Edge): AnchorRange | null {
  if (edge.anchor_start === null || edge.anchor_end === null || edge.anchored_text === null) {
    return null;
  }
  const start = toUtf16Index(content, edge.anchor_start);
  const end = toUtf16Index(content, edge.anchor_end);
  if (end <= start || end > content.length) return null;
  if (content.slice(start, end) !== edge.anchored_text) return null;
  return { edgeId: edge.id, start, end };
}
