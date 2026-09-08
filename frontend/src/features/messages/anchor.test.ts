import { describe, expect, it } from "vitest";
import {
  anchorFromUtf16,
  resolveAnchor,
  toCodePointOffset,
  toUtf16Index,
} from "./anchor";
import type { Edge } from "./api";

/** An anchored edge, with only the fields the anchor code reads filled in. */
function branchEdge(fields: Partial<Edge> & { id: string }): Edge {
  return {
    parent_message_id: "parent",
    child_message_id: `child-${fields.id}`,
    anchor_start: null,
    anchor_end: null,
    anchored_text: null,
    strategy_override: null,
    created_at: "2026-09-08T10:00:00+00:00",
    ...fields,
  };
}

describe("code point conversion", () => {
  it("agrees with UTF-16 while the text is all one-unit characters", () => {
    const text = "plain ascii text";
    expect(toCodePointOffset(text, 6)).toBe(6);
    expect(toUtf16Index(text, 6)).toBe(6);
  });

  // The whole reason this conversion exists. JavaScript counts the rocket as
  // two, Python counts it as one, and every offset after it disagrees.
  it("counts a character outside the basic plane once", () => {
    const text = "a 🚀 b";
    expect(text.length).toBe(6);
    expect(toCodePointOffset(text, text.length)).toBe(5);
    expect(toCodePointOffset(text, 4)).toBe(3);
    expect(toUtf16Index(text, 3)).toBe(4);
  });

  it("round-trips every boundary of a string full of pairs", () => {
    const text = "🌱 grows 🌿 then 🌳";
    let index = 0;
    while (index <= text.length) {
      const offset = toCodePointOffset(text, index);
      expect(toUtf16Index(text, offset)).toBe(index);
      index += index < text.length && text.codePointAt(index)! > 0xffff ? 2 : 1;
    }
  });

  it("snaps an index landing inside a pair back to the whole character", () => {
    const text = "a🚀b";
    // Index 2 is the low half of the rocket. Counting it as its own character
    // would put half a character in the offset.
    expect(toCodePointOffset(text, 2)).toBe(1);
  });

  it("clamps an offset past the end rather than running off it", () => {
    expect(toCodePointOffset("abc", 99)).toBe(3);
    expect(toUtf16Index("abc", 99)).toBe(3);
  });
});

describe("anchorFromUtf16", () => {
  const content = "The walk climbs to the root, and 200 is a runaway guard.";

  it("sends the exact substring its offsets name", () => {
    const start = content.indexOf("runaway guard");
    const anchor = anchorFromUtf16(content, start, start + "runaway guard".length);
    expect(anchor).not.toBeNull();
    expect(anchor!.anchored_text).toBe("runaway guard");
    // The server slices its own content with these two numbers and compares.
    expect(content.slice(anchor!.anchor_start, anchor!.anchor_end)).toBe("runaway guard");
  });

  it("drops whitespace at both ends and moves the offsets with it", () => {
    const start = content.indexOf(" and ");
    const anchor = anchorFromUtf16(content, start, start + 5);
    expect(anchor!.anchored_text).toBe("and");
    expect(content.slice(anchor!.anchor_start, anchor!.anchor_end)).toBe("and");
  });

  it("refuses a highlight that is nothing but whitespace", () => {
    expect(anchorFromUtf16("a \n\t b", 1, 5)).toBeNull();
  });

  it("refuses a collapsed or inverted range", () => {
    expect(anchorFromUtf16(content, 4, 4)).toBeNull();
    expect(anchorFromUtf16(content, 9, 4)).toBeNull();
  });

  it("reports code-point offsets when the reply contains an emoji", () => {
    const text = "🚀 launches the walk";
    const start = text.indexOf("walk");
    const anchor = anchorFromUtf16(text, start, start + 4)!;
    // UTF-16 says 16; the server, counting code points, says 15.
    expect(start).toBe(16);
    expect(anchor.anchor_start).toBe(15);
    expect([...text].slice(anchor.anchor_start, anchor.anchor_end).join("")).toBe("walk");
  });
});

describe("resolveAnchor", () => {
  const content = "one two three";

  it("finds the range a stored anchor names", () => {
    const range = resolveAnchor(
      content,
      branchEdge({ id: "e1", anchor_start: 4, anchor_end: 7, anchored_text: "two" }),
    );
    expect(range).toEqual({ edgeId: "e1", start: 4, end: 7 });
  });

  it("declines to draw a span whose text no longer matches its offsets", () => {
    const range = resolveAnchor(
      content,
      branchEdge({ id: "e1", anchor_start: 0, anchor_end: 3, anchored_text: "two" }),
    );
    expect(range).toBeNull();
  });

  it("declines an anchor running past the end of an edited message", () => {
    const range = resolveAnchor(
      "short",
      branchEdge({ id: "e1", anchor_start: 4, anchor_end: 40, anchored_text: "two" }),
    );
    expect(range).toBeNull();
  });

  it("returns nothing for a continuation edge", () => {
    expect(resolveAnchor(content, branchEdge({ id: "e1" }))).toBeNull();
  });

  it("reads a stored anchor back through an emoji", () => {
    const text = "🚀 launches the walk";
    const range = resolveAnchor(
      text,
      branchEdge({ id: "e1", anchor_start: 15, anchor_end: 19, anchored_text: "walk" }),
    )!;
    expect(text.slice(range.start, range.end)).toBe("walk");
  });
});
