import { beforeEach, describe, expect, it } from "vitest";
import {
  ANCHOR_SOURCE_ATTRIBUTE,
  TURN_ATTRIBUTE,
  clampToContainer,
  offsetsForRange,
  readSpanSelection,
} from "./selection";

/**
 * The DOM half of the measurement.
 *
 * These build ranges by hand rather than by selecting text, because a
 * selection is a user gesture and the arithmetic under it is what can be
 * wrong. What is being checked is that a range over the rendered reply
 * measures to the same offsets the stored string would give -- including when
 * the reply is split into several nodes by the marks over earlier branches,
 * and when the selection runs off the end of the message it started in.
 */

function mount(html: string): HTMLElement {
  document.body.innerHTML = html;
  return document.body.firstElementChild as HTMLElement;
}

function rangeOver(node: Node, start: number, end: number): Range {
  const range = document.createRange();
  range.setStart(node, start);
  range.setEnd(node, end);
  return range;
}

beforeEach(() => {
  document.body.innerHTML = "";
});

/**
 * jsdom does no layout, so a range cannot be asked where it is on screen.
 * Only the affordance's position depends on that, and a position is not what
 * these tests are about -- so it is stubbed here rather than guarded for in
 * the code, where a check would exist purely to satisfy a test environment.
 */
const NOWHERE = { top: 0, bottom: 0, left: 0, width: 0, height: 0 } as DOMRect;
if (typeof Range.prototype.getClientRects !== "function") {
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => NOWHERE;
}

describe("offsetsForRange", () => {
  it("measures a range inside one text node", () => {
    const container = mount("<div>one two three</div>");
    const text = container.firstChild!;
    expect(offsetsForRange(container, rangeOver(text, 4, 7))).toEqual({ start: 4, end: 7 });
  });

  // Once a reply carries marks over the spans earlier branches grew from, its
  // text is several nodes. The offsets must not change because of them.
  it("measures across the marks a previous branch left behind", () => {
    const container = mount("<div><span>one </span><mark>two</mark><span> three</span></div>");
    const tail = container.lastChild!.firstChild!;
    const range = document.createRange();
    range.setStart(container.firstChild!.firstChild!, 0);
    range.setEnd(tail, 6);
    expect(offsetsForRange(container, range)).toEqual({ start: 0, end: 13 });
  });

  it("keeps the newlines pre-wrap preserves", () => {
    const container = mount("<div>first\n\nsecond</div>");
    const text = container.firstChild!;
    expect(offsetsForRange(container, rangeOver(text, 0, 13))).toEqual({ start: 0, end: 13 });
    expect(container.textContent).toBe("first\n\nsecond");
  });

  it("clamps a selection that runs off the end of the message", () => {
    document.body.innerHTML = "<div id='reply'>one two</div><div id='next'>elsewhere</div>";
    const reply = document.getElementById("reply")!;
    const range = document.createRange();
    range.setStart(reply.firstChild!, 4);
    range.setEnd(document.getElementById("next")!.firstChild!, 5);
    expect(offsetsForRange(reply, range)).toEqual({ start: 4, end: 7 });
  });

  it("clamps a selection that starts before the message", () => {
    document.body.innerHTML = "<div id='before'>earlier</div><div id='reply'>one two</div>";
    const reply = document.getElementById("reply")!;
    const range = document.createRange();
    range.setStart(document.getElementById("before")!.firstChild!, 2);
    range.setEnd(reply.firstChild!, 3);
    expect(offsetsForRange(reply, range)).toEqual({ start: 0, end: 3 });
  });

  it("returns nothing for a range that never touches the message", () => {
    document.body.innerHTML = "<div id='reply'>one two</div><div id='next'>elsewhere</div>";
    const next = document.getElementById("next")!;
    const range = rangeOver(next.firstChild!, 0, 4);
    expect(offsetsForRange(document.getElementById("reply")!, range)).toBeNull();
  });

  it("returns nothing for a collapsed range", () => {
    const container = mount("<div>one two</div>");
    expect(offsetsForRange(container, rangeOver(container.firstChild!, 3, 3))).toBeNull();
  });

  it("counts a surrogate pair the way the string does", () => {
    const container = mount("<div>a🚀 walk</div>");
    const text = container.firstChild!;
    // Offsets out of the DOM are UTF-16, matching `String`; turning them into
    // the code points the API counts happens on the way out, not here.
    expect(offsetsForRange(container, rangeOver(text, 4, 8))).toEqual({ start: 4, end: 8 });
    expect(container.textContent!.slice(4, 8)).toBe("walk");
  });
});

/**
 * A branch anchors into exactly one message. A highlight that reaches a
 * second one is refused rather than quietly cut down to the first, because
 * clamping would hand back a branch off less text than was highlighted with
 * nothing on screen saying so.
 */
describe("readSpanSelection", () => {
  function thread() {
    document.body.innerHTML = `
      <div id="thread">
        <article ${TURN_ATTRIBUTE}="m1"><div ${ANCHOR_SOURCE_ATTRIBUTE}="m1">first reply</div></article>
        <article ${TURN_ATTRIBUTE}="m2"><p>a question</p></article>
        <article ${TURN_ATTRIBUTE}="m3"><div ${ANCHOR_SOURCE_ATTRIBUTE}="m3">second reply</div></article>
      </div>`;
    const text = (id: string) =>
      document.querySelector(`[${TURN_ATTRIBUTE}="${id}"]`)!.firstElementChild!.firstChild!;
    return { text };
  }

  function select(startNode: Node, startAt: number, endNode: Node, endAt: number) {
    const range = document.createRange();
    range.setStart(startNode, startAt);
    range.setEnd(endNode, endAt);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
  }

  it("offers a highlight inside one reply", () => {
    const { text } = thread();
    select(text("m1"), 0, text("m1"), 5);
    expect(readSpanSelection()).toMatchObject({ messageId: "m1", start: 0, end: 5 });
  });

  it("refuses a highlight running into the next reply", () => {
    const { text } = thread();
    select(text("m1"), 6, text("m3"), 6);
    expect(readSpanSelection()).toBeNull();
  });

  it("refuses a highlight running into the question below", () => {
    const { text } = thread();
    select(text("m1"), 6, text("m2"), 5);
    expect(readSpanSelection()).toBeNull();
  });

  it("allows an overshoot into the thread's own padding", () => {
    const { text } = thread();
    // Ending outside every turn is a sloppy drag, not a second message: the
    // part beyond the reply's text is trimmed and the offer stands.
    select(text("m1"), 6, document.getElementById("thread")!, 3);
    expect(readSpanSelection()).toMatchObject({ messageId: "m1", start: 6, end: 11 });
  });

  it("offers nothing for a highlight starting outside a reply", () => {
    const { text } = thread();
    select(text("m2"), 0, text("m2"), 3);
    expect(readSpanSelection()).toBeNull();
  });

  it("offers nothing for a collapsed selection", () => {
    const { text } = thread();
    select(text("m1"), 3, text("m1"), 3);
    expect(readSpanSelection()).toBeNull();
  });
});

describe("clampToContainer", () => {
  it("hands back a range already inside the container unchanged", () => {
    const container = mount("<div>one two</div>");
    const clamped = clampToContainer(container, rangeOver(container.firstChild!, 0, 3));
    expect(clamped!.toString()).toBe("one");
  });
});
