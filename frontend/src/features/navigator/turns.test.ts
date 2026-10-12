import { describe, expect, it } from "vitest";
import type { ConversationGraph, Edge, Message } from "@/features/messages/api";
import {
  ancestorChainIds,
  autoExpanded,
  buildTurnTree,
  flattenTurns,
  layoutTurns,
  nodeForMessage,
  RUN_PREFIX,
  spineSegments,
  turnCount,
  type TurnNode,
} from "./turns";

/**
 * The tree behind both navigator views.
 *
 * Two properties are worth holding down. **Fusion has to split when a
 * question has more than one reply** - that is regeneration and the eval's
 * five-arm fan-out, the two cases message-as-node exists for, so a graph that
 * fused them would draw the conversation as a straight line and hide the only
 * structure that matters. And **layout has to be deterministic**: the
 * deliverable includes published screenshots, and a layout that settled
 * differently per load would make two pictures of one conversation disagree.
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
    pending: false,
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

/** A question, its reply, and a second question under it. */
function straight(): ConversationGraph {
  return graphOf(
    [
      message("q1", "user"),
      message("a1", "assistant"),
      message("q2", "user"),
      message("a2", "assistant"),
    ],
    [edge("e1", "q1", "a1"), edge("e2", "a1", "q2"), edge("e3", "q2", "a2")],
  );
}

describe("buildTurnTree", () => {
  it("fuses a question with its single reply", () => {
    const roots = buildTurnTree(straight());

    expect(roots).toHaveLength(1);
    expect(roots[0].messages.map((m) => m.id)).toEqual(["q1", "a1"]);
    expect(roots[0].children).toHaveLength(1);
    expect(roots[0].children[0].messages.map((m) => m.id)).toEqual(["q2", "a2"]);
  });

  it("splits the fusion when one question has two replies", () => {
    // Exactly what a retry writes, and what the eval's five arms write.
    const graph = graphOf(
      [message("q1", "user"), message("a1", "assistant"), message("a2", "assistant")],
      [edge("e1", "q1", "a1"), edge("e2", "q1", "a2")],
    );

    const roots = buildTurnTree(graph);
    expect(roots[0].messages.map((m) => m.id)).toEqual(["q1"]);
    expect(roots[0].children.map((child) => child.messages.map((m) => m.id))).toEqual([
      ["a1"],
      ["a2"],
    ]);
  });

  it("hangs a branch off the turn whose reply it was anchored in", () => {
    const graph = straight();
    graph.messages.push(message("b1", "user"), message("b2", "assistant"));
    graph.edges.push(edge("e4", "a1", "b1", "a phrase"), edge("e5", "b1", "b2"));

    const root = buildTurnTree(graph)[0];
    const branch = root.children.find((child) => child.branch);

    expect(branch).toBeDefined();
    expect(branch!.anchoredText).toBe("a phrase");
    expect(branch!.messages.map((m) => m.id)).toEqual(["b1", "b2"]);
    // The continuation is still there beside it, unaffected.
    expect(root.children.filter((child) => !child.branch)).toHaveLength(1);
  });

  it("tells each node which view shows it", () => {
    const graph = straight();
    graph.messages.push(message("b1", "user"), message("b2", "assistant"));
    graph.messages.push(message("b3", "user"), message("b4", "assistant"));
    graph.edges.push(edge("e4", "a1", "b1", "a phrase"), edge("e5", "b1", "b2"));
    graph.edges.push(edge("e6", "b2", "b3"), edge("e7", "b3", "b4"));

    const nodes = flattenTurns(buildTurnTree(graph));
    const view = (id: string) => nodes.find((node) => node.id === id)?.viewFrom;

    // On the main thread nothing is re-rooted; inside a branch every node
    // below it is read from the branch's first message.
    expect(view("q1")).toBeNull();
    expect(view("q2")).toBeNull();
    expect(view("b1")).toBe("b1");
    expect(view("b3")).toBe("b1");
  });

  it("finds the node either half of a fused turn is drawn in", () => {
    const roots = buildTurnTree(straight());

    expect(nodeForMessage(roots, "a1")?.id).toBe("q1");
    expect(nodeForMessage(roots, "q1")?.id).toBe("q1");
    expect(nodeForMessage(roots, "nope")).toBeNull();
  });

  it("draws siblings oldest first, matching reading order", () => {
    const graph = graphOf(
      [message("q1", "user"), message("a1", "assistant")],
      [edge("e1", "q1", "a1")],
    );
    graph.messages.push(message("x1", "user"), message("y1", "user"));
    graph.edges.push(edge("e2", "a1", "x1", "first span"));
    graph.edges.push(edge("e3", "a1", "y1", "second span"));

    const root = buildTurnTree(graph)[0];
    expect(root.children.map((child) => child.id)).toEqual(["x1", "y1"]);
  });
});

describe("layoutTurns", () => {
  it("puts depth on the row and one leaf per lane", () => {
    const layout = layoutTurns(buildTurnTree(straight()));
    const rows = layout.placed.map((entry) => entry.row).sort();

    expect(rows).toEqual([0, 1]);
    expect(layout.lanes).toBe(1);
    expect(layout.placed.every((entry) => entry.lane === 0)).toBe(true);
  });

  it("centres a parent over its children", () => {
    // Reverted to this from one-lane-per-thread: with three branches off one
    // turn, that version fanned every connector out as a long diagonal.
    const graph = graphOf(
      [message("q1", "user"), message("a1", "assistant"), message("a2", "assistant")],
      [edge("e1", "q1", "a1"), edge("e2", "q1", "a2")],
    );

    const layout = layoutTurns(buildTurnTree(graph));
    const lane = (id: string) =>
      layout.placed.find((entry) => entry.node.id === id)?.lane;

    expect(lane("a1")).toBe(0);
    expect(lane("a2")).toBe(1);
    expect(lane("q1")).toBe(0.5);
    expect(layout.lanes).toBe(2);
  });

  it("marks the links a branch made, which is what draws them apart", () => {
    const graph = straight();
    graph.messages.push(message("b1", "user"));
    graph.edges.push(edge("e4", "a1", "b1", "a phrase"));

    const layout = layoutTurns(buildTurnTree(graph));
    expect(layout.links.filter((link) => link.branch)).toHaveLength(1);
    expect(layout.links.filter((link) => !link.branch)).toHaveLength(1);
  });

  it("lays the same graph out identically every time", () => {
    const first = layoutTurns(buildTurnTree(straight()));
    const second = layoutTurns(buildTurnTree(straight()));

    const shape = (layout: typeof first) =>
      layout.placed.map((entry) => [entry.node.id, entry.row, entry.lane]);

    expect(shape(first)).toEqual(shape(second));
  });
});

describe("collapsing", () => {
  /** The straight thread, a branch off its reply, and a turn inside that. */
  function withBranch(): ConversationGraph {
    const graph = straight();
    graph.messages.push(message("b1", "user"), message("b2", "assistant"));
    graph.messages.push(message("b3", "user"), message("b4", "assistant"));
    graph.edges.push(edge("e4", "a1", "b1", "a phrase"), edge("e5", "b1", "b2"));
    graph.edges.push(edge("e6", "b2", "b3"), edge("e7", "b3", "b4"));
    return graph;
  }

  it("counts what a collapsed branch is hiding", () => {
    const roots = buildTurnTree(withBranch());
    const branch = roots[0].children.find((child) => child.branch)!;

    // The branch itself plus the turn inside it.
    expect(turnCount(branch)).toBe(2);
  });

  it("names the chain down to a node, so it can be opened", () => {
    const roots = buildTurnTree(withBranch());
    expect(ancestorChainIds(roots, "b3")).toEqual(["q1", "b1", "b3"]);
    expect(ancestorChainIds(roots, "nope")).toEqual([]);
  });

  it("opens nothing by default on the main thread", () => {
    // A branch is a different question; its contents wait to be asked for.
    expect(autoExpanded(buildTurnTree(withBranch()), null).size).toBe(0);
  });

  it("opens the chain down to the view being read", () => {
    const open = autoExpanded(buildTurnTree(withBranch()), "b1");
    expect([...open].sort()).toEqual(["b1", "q1"]);
  });

  it("opens alternative replies, which are not a departure from the thread", () => {
    const graph = graphOf(
      [message("q1", "user"), message("a1", "assistant"), message("a2", "assistant")],
      [edge("e1", "q1", "a1"), edge("e2", "q1", "a2")],
    );

    expect([...autoExpanded(buildTurnTree(graph), null)].sort()).toEqual(["a1", "a2"]);
  });
});

describe("spineSegments", () => {
  /** A straight thread of `count` turns, so a fold has something to fold. */
  function chain(count: number): ConversationGraph {
    const messages: Message[] = [];
    const edges: Edge[] = [];
    for (let i = 1; i <= count; i += 1) {
      messages.push(message(`q${i}`, "user"), message(`a${i}`, "assistant"));
      edges.push(edge(`eq${i}`, `q${i}`, `a${i}`));
      if (i > 1) edges.push(edge(`ec${i}`, `a${i - 1}`, `q${i}`));
    }
    return graphOf(messages, edges);
  }

  /** What the tree draws, as a readable line: a node id, or a fold's size. */
  function shape(node: TurnNode): string[] {
    return spineSegments(node).map((segment) =>
      segment.kind === "turn" ? segment.node.id : `fold:${segment.nodes.length}`,
    );
  }

  it("folds a straight thread into one anchor", () => {
    // Five turns below the root, and the panel spends one row on them.
    expect(shape(buildTurnTree(chain(6))[0])).toEqual(["fold:5"]);
  });

  it("keeps the turn a branch came out of, so the branch has somewhere to sit", () => {
    const graph = chain(4);
    graph.messages.push(message("b1", "user"));
    graph.edges.push(edge("eb", "a3", "b1", "a phrase"));

    // q3 owns the branch and stays; the turns either side of it fold.
    expect(shape(buildTurnTree(graph)[0])).toEqual(["fold:1", "q3", "fold:1"]);
  });

  it("keeps a fork, and stops there", () => {
    const graph = chain(3);
    graph.messages.push(message("a3b", "assistant"));
    graph.edges.push(edge("eregen", "q3", "a3b"));

    // The walk ends at the fork: each arm draws as its own block and folds
    // its own spine, so carrying on here would draw them twice.
    expect(shape(buildTurnTree(graph)[0])).toEqual(["fold:1", "q3"]);
  });

  it("gives a fold an id no node in the tree can carry", () => {
    const segments = spineSegments(buildTurnTree(chain(3))[0]);
    expect(segments[0].id).toBe(`${RUN_PREFIX}q2`);
    expect(flattenTurns(buildTurnTree(chain(3))).map((n) => n.id)).not.toContain(
      segments[0].id,
    );
  });

  it("folds nothing below a leaf", () => {
    expect(shape(buildTurnTree(chain(1))[0])).toEqual([]);
  });

  it("does not follow a branch, which is a different thread of thought", () => {
    const graph = chain(2);
    graph.messages.push(message("b1", "user"), message("b2", "assistant"));
    graph.messages.push(message("b3", "user"), message("b4", "assistant"));
    graph.edges.push(edge("eb", "a1", "b1", "a phrase"), edge("eb2", "b1", "b2"));
    graph.edges.push(edge("eb3", "b2", "b3"), edge("eb4", "b3", "b4"));

    const root = buildTurnTree(graph)[0];
    // The root owns a branch, so the branch is drawn from the root's own row
    // rather than turning up in the spine below it.
    expect(shape(root)).toEqual(["fold:1"]);
    const branch = root.children.find((child) => child.branch)!;
    expect(shape(branch)).toEqual(["fold:1"]);
  });
});
