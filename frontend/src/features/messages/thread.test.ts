import { describe, expect, it } from "vitest";
import { branchTrail, buildThread, findGap } from "./thread";
import type { ConversationGraph, Edge, Message } from "./api";

/**
 * The path walk, and the trail out of a branch.
 *
 * Both halves of the walk are load-bearing and neither fails loudly: follow
 * an anchored edge and a branch quietly takes over the main thread, take the
 * oldest child and an abandoned reply holds the path with the good one hidden
 * behind a counter. So a fork and an abandoned reply are the two cases worth
 * pinning down.
 */

let clock = 0;

function message(id: string, role: "user" | "assistant", content = `${id} text`): Message {
  clock += 1;
  const at = new Date(Date.UTC(2026, 8, 8, 0, 0, clock)).toISOString();
  return {
    id,
    conversation_id: "c1",
    role,
    content,
    created_at: at,
    updated_at: at,
    pending: role === "assistant" && content === "",
  };
}

function edge(id: string, parent: string, child: string, anchoredText?: string): Edge {
  clock += 1;
  return {
    id,
    parent_message_id: parent,
    child_message_id: child,
    anchor_start: anchoredText === undefined ? null : 0,
    anchor_end: anchoredText === undefined ? null : anchoredText.length,
    anchored_text: anchoredText ?? null,
    strategy_override: null,
    created_at: new Date(Date.UTC(2026, 8, 8, 0, 0, clock)).toISOString(),
  };
}

function graphOf(messages: Message[], edges: Edge[]): ConversationGraph {
  return { messages, edges };
}

describe("buildThread", () => {
  it("walks a straight chain from the root", () => {
    const graph = graphOf(
      [message("m1", "user"), message("m2", "assistant"), message("m3", "user")],
      [edge("e1", "m1", "m2"), edge("e2", "m2", "m3")],
    );
    expect(buildThread(graph).steps.map((step) => step.message.id)).toEqual([
      "m1",
      "m2",
      "m3",
    ]);
  });

  it("takes the newest reply and counts the abandoned one", () => {
    const question = message("q", "user");
    const first = message("a1", "assistant");
    const second = message("a2", "assistant");
    const graph = graphOf(
      [question, first, second],
      [edge("e1", "q", "a1"), edge("e2", "q", "a2")],
    );

    const thread = buildThread(graph);
    expect(thread.steps.map((step) => step.message.id)).toEqual(["q", "a2"]);
    expect(thread.steps[0].otherReplies).toBe(1);
  });

  it("never follows an anchored edge onto the main path", () => {
    const graph = graphOf(
      [
        message("m1", "user"),
        message("m2", "assistant", "a reply about the walk"),
        message("b1", "user", "what about the walk?"),
      ],
      [edge("e1", "m1", "m2"), edge("e2", "m2", "b1", "the walk")],
    );

    const thread = buildThread(graph);
    expect(thread.steps.map((step) => step.message.id)).toEqual(["m1", "m2"]);
    expect(thread.steps[1].branchEdges.map((each) => each.id)).toEqual(["e2"]);
    expect(thread.steps[1].otherReplies).toBe(0);
  });

  it("re-roots at a branch and walks its continuations from there", () => {
    const graph = graphOf(
      [
        message("m1", "user"),
        message("m2", "assistant", "a reply about the walk"),
        message("b1", "user", "what about the walk?"),
        message("b2", "assistant", "it climbs to the root"),
      ],
      [edge("e1", "m1", "m2"), edge("e2", "m2", "b1", "the walk"), edge("e3", "b1", "b2")],
    );

    const branch = buildThread(graph, "b1");
    expect(branch.steps.map((step) => step.message.id)).toEqual(["b1", "b2"]);
    // The first step of a branch keeps the anchored link it grew from, which
    // is what the crumb above the thread is named by.
    expect(branch.steps[0].edge?.anchored_text).toBe("the walk");
    expect(branch.tail?.message.id).toBe("b2");
  });

  it("falls back to the root when the address names a message that is gone", () => {
    const graph = graphOf([message("m1", "user")], []);
    expect(buildThread(graph, "missing").steps.map((step) => step.message.id)).toEqual([
      "m1",
    ]);
  });

  it("returns nothing for an empty conversation", () => {
    const thread = buildThread(graphOf([], []));
    expect(thread.steps).toEqual([]);
    expect(thread.tail).toBeNull();
  });
});

describe("branchTrail", () => {
  const graph = graphOf(
    [
      message("m1", "user"),
      message("m2", "assistant", "the outer reply"),
      message("b1", "user", "about the outer"),
      message("b2", "assistant", "the inner reply"),
      message("c1", "user", "about the inner"),
    ],
    [
      edge("e1", "m1", "m2"),
      edge("e2", "m2", "b1", "outer"),
      edge("e3", "b1", "b2"),
      edge("e4", "b2", "c1", "inner"),
    ],
  );

  it("is just the main thread when nothing is re-rooted", () => {
    expect(branchTrail(graph, null)).toEqual([{ fromMessageId: null, anchoredText: null }]);
  });

  it("names every span crossed on the way down, outermost first", () => {
    expect(branchTrail(graph, "c1")).toEqual([
      { fromMessageId: null, anchoredText: null },
      { fromMessageId: "b1", anchoredText: "outer" },
      { fromMessageId: "c1", anchoredText: "inner" },
    ]);
  });

  it("still shows a view opened at a message no branch attached", () => {
    expect(branchTrail(graph, "b2")).toEqual([
      { fromMessageId: null, anchoredText: null },
      { fromMessageId: "b1", anchoredText: "outer" },
      { fromMessageId: "b2", anchoredText: null },
    ]);
  });
});

describe("findGap", () => {
  it("offers to answer a question with nothing under it", () => {
    const graph = graphOf([message("m1", "user")], []);
    expect(findGap(buildThread(graph))).toEqual({ kind: "unanswered", userMessageId: "m1" });
  });

  it("offers to try again where a reply was started and never landed", () => {
    const graph = graphOf(
      [message("m1", "user"), message("m2", "assistant", "")],
      [edge("e1", "m1", "m2")],
    );
    expect(findGap(buildThread(graph))).toEqual({ kind: "unfinished", userMessageId: "m1" });
  });

  it("finds nothing wrong with a finished thread", () => {
    const graph = graphOf(
      [message("m1", "user"), message("m2", "assistant")],
      [edge("e1", "m1", "m2")],
    );
    expect(findGap(buildThread(graph))).toBeNull();
  });

  it("looks at the branch on screen, not at the main thread", () => {
    const graph = graphOf(
      [
        message("m1", "user"),
        message("m2", "assistant", "a reply"),
        message("b1", "user", "about it"),
      ],
      [edge("e1", "m1", "m2"), edge("e2", "m2", "b1", "a reply")],
    );
    expect(findGap(buildThread(graph))).toBeNull();
    expect(findGap(buildThread(graph, "b1"))).toEqual({
      kind: "unanswered",
      userMessageId: "b1",
    });
  });
});
