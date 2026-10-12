import type { ConversationGraph, Edge, Message } from "@/features/messages/api";
import { isBranch } from "@/features/messages/thread";

/**
 * The conversation as a tree of turns, and where to draw it.
 *
 * The thread walk answers "which single path am I reading". This answers the
 * other question: what else is in this conversation. Same graph, no second
 * request - the message route already hands back every node and every link.
 *
 * **A turn fuses a user message with its reply into one node.** That is a
 * rendering choice and nothing more; a message is still the unit the graph
 * stores and the unit an anchor points into. Fusing is what makes the common
 * case readable - a straight conversation draws as a column of turns rather
 * than a ladder of alternating half-cards.
 *
 * **The fusion splits the moment a question has more than one reply**, which
 * is exactly regeneration and the eval's five-arm fan-out. Those are the cases
 * message-as-node exists to represent, so they are the cases that must not be
 * flattened away: the question becomes its own node with one child per reply.
 *
 * **Layout is deterministic, and that is the reason there is no graph
 * library.** Every node has exactly one parent, so this is a tree: depth sets
 * the row and a tidy left-to-right sweep sets the lane. Nothing settles, and
 * two screenshots of the same conversation are identical - which matters for a
 * project whose deliverable is a published evaluation.
 */

export interface TurnNode {
  /** The first message in the node, and the node's identity. */
  id: string;
  /** One message, or a question and its single reply. */
  messages: Message[];
  /** The link that attached this node. Null only at the conversation's root. */
  edge: Edge | null;
  /** True when the link that attached it is anchored: this node is a branch. */
  branch: boolean;
  /** The span it grew from, for a branch. Null otherwise. */
  anchoredText: string | null;
  /** Distance from the root in turns, which is the row it draws on. */
  depth: number;
  /**
   * What `?from=` has to hold for the linear view to show this node: the
   * nearest branch at or above it, or null for the main thread. Carried down
   * during the build rather than recomputed by climbing, because the build
   * already knows which view it is inside.
   */
  viewFrom: string | null;
  children: TurnNode[];
}

/** A hard stop, so a malformed graph cannot spin here. Topology is acyclic. */
const MAX_NODES = 2000;

/** Newest first, matching the linear walk, so the two never disagree. */
function newestFirst(a: Edge, b: Edge): number {
  if (a.created_at !== b.created_at) return a.created_at < b.created_at ? 1 : -1;
  return a.id < b.id ? 1 : -1;
}

/** Oldest first: reading order for siblings drawn side by side. */
function oldestFirst(a: Edge, b: Edge): number {
  return -newestFirst(a, b);
}

function index(graph: ConversationGraph) {
  const byId = new Map(graph.messages.map((message) => [message.id, message]));
  const childEdges = new Map<string, Edge[]>();
  const attached = new Map<string, Edge>();

  for (const edge of graph.edges) {
    if (!byId.has(edge.parent_message_id) || !byId.has(edge.child_message_id)) continue;
    const siblings = childEdges.get(edge.parent_message_id);
    if (siblings === undefined) childEdges.set(edge.parent_message_id, [edge]);
    else siblings.push(edge);
    attached.set(edge.child_message_id, edge);
  }

  return { byId, childEdges, attached };
}

export function buildTurnTree(graph: ConversationGraph): TurnNode[] {
  const { byId, childEdges, attached } = index(graph);
  const roots = graph.messages.filter((message) => !attached.has(message.id));
  let budget = MAX_NODES;

  function build(message: Message, depth: number, viewFrom: string | null): TurnNode {
    const edge = attached.get(message.id) ?? null;
    const branch = edge !== null && isBranch(edge);
    const view = branch ? message.id : viewFrom;

    const own = childEdges.get(message.id) ?? [];
    const replies = own.filter((child) => {
      if (isBranch(child)) return false;
      return byId.get(child.child_message_id)?.role === "assistant";
    });

    // Fused only when the question has exactly one reply. Two replies is a
    // regeneration or an eval fan-out, and flattening those would hide the
    // one thing the graph is here to show.
    const fuse =
      message.role === "user" && replies.length === 1
        ? byId.get(replies[0].child_message_id)
        : undefined;

    const messages = fuse === undefined ? [message] : [message, fuse];
    // A branch can hang off either half of a fused turn - a span in the reply
    // is the usual case, but nothing forbids one in the question.
    const outgoing = [
      ...own.filter((child) => fuse === undefined || child.child_message_id !== fuse.id),
      ...(fuse === undefined ? [] : (childEdges.get(fuse.id) ?? [])),
    ];

    const children: TurnNode[] = [];
    for (const child of [...outgoing].sort(oldestFirst)) {
      const target = byId.get(child.child_message_id);
      if (target === undefined || budget <= 0) continue;
      budget -= 1;
      children.push(build(target, depth + 1, view));
    }

    return {
      id: message.id,
      messages,
      edge,
      branch,
      anchoredText: branch ? (edge?.anchored_text ?? null) : null,
      depth,
      viewFrom: view,
      children,
    };
  }

  return roots.map((root) => build(root, 0, null));
}

/** Every node in the tree, in reading order: a node before its children. */
export function flattenTurns(roots: TurnNode[]): TurnNode[] {
  const out: TurnNode[] = [];
  const walk = (node: TurnNode) => {
    out.push(node);
    node.children.forEach(walk);
  };
  roots.forEach(walk);
  return out;
}

/** The node a message is drawn in, whichever half of a fused turn it is. */
export function nodeForMessage(roots: TurnNode[], messageId: string): TurnNode | null {
  return (
    flattenTurns(roots).find((node) =>
      node.messages.some((message) => message.id === messageId),
    ) ?? null
  );
}

export interface PlacedTurn {
  node: TurnNode;
  /** Depth. */
  row: number;
  /** Horizontal position in lane units; a leaf takes a whole lane. */
  lane: number;
}

export interface TurnLink {
  from: PlacedTurn;
  to: PlacedTurn;
  branch: boolean;
}

export interface TurnLayout {
  placed: PlacedTurn[];
  links: TurnLink[];
  /** Total lanes used, for sizing the canvas. */
  lanes: number;
  /** Deepest row present, for the same reason. */
  rows: number;
}

/**
 * Depth sets the row; a tidy sweep sets the lane.
 *
 * Leaves take the next free lane left to right, and a parent sits at the
 * midpoint of its first and last child. One pass, no iteration to
 * convergence, identical output for identical input - which matters because
 * the deliverable includes published screenshots.
 *
 * *Tried and reverted (2026-09-08):* one lane per thread, where a
 * continuation kept its parent's column and every branch opened a new one to
 * the right. It reads well with one branch and badly with three: they all
 * leave the same point and fan out as long diagonals across the whole width,
 * which looks misaligned rather than structured. Centring the parent keeps
 * every connector short and every child directly under the turn it came from.
 */
export function layoutTurns(roots: TurnNode[]): TurnLayout {
  const placed: PlacedTurn[] = [];
  const links: TurnLink[] = [];
  let nextLane = 0;
  let rows = 0;

  function place(node: TurnNode): PlacedTurn {
    rows = Math.max(rows, node.depth);

    if (node.children.length === 0) {
      const leaf: PlacedTurn = { node, row: node.depth, lane: nextLane };
      nextLane += 1;
      placed.push(leaf);
      return leaf;
    }

    const children = node.children.map(place);
    const first = children[0].lane;
    const last = children[children.length - 1].lane;
    const self: PlacedTurn = { node, row: node.depth, lane: (first + last) / 2 };
    placed.push(self);

    for (const child of children) {
      links.push({ from: self, to: child, branch: child.node.branch });
    }

    return self;
  }

  roots.forEach(place);

  return { placed, links, lanes: Math.max(nextLane, 1), rows };
}

/** The node one step above this one, or null for a root. */
export function parentOf(roots: TurnNode[], id: string): TurnNode | null {
  return (
    flattenTurns(roots).find((node) =>
      node.children.some((child) => child.id === id),
    ) ?? null
  );
}

/** Every message at or below a node: what deleting it would take. */
export function subtreeSize(node: TurnNode): number {
  return (
    node.messages.length +
    node.children.reduce((total, child) => total + subtreeSize(child), 0)
  );
}

/** True when `id` names the node itself or anything under it. */
export function containsNode(node: TurnNode, id: string | null): boolean {
  if (id === null) return false;
  if (node.id === id) return true;
  return node.children.some((child) => containsNode(child, id));
}

/** Nodes at or below this one, itself included: what a collapsed row hides. */
export function turnCount(node: TurnNode): number {
  return 1 + node.children.reduce((total, child) => total + turnCount(child), 0);
}

/** The links out of a node, split by the only distinction that changes layout. */
export function continuationsOf(node: TurnNode): TurnNode[] {
  return node.children.filter((child) => !child.branch);
}

export function branchesOf(node: TurnNode): TurnNode[] {
  return node.children.filter((child) => child.branch);
}

/**
 * One turn drawn as its own row, or a stretch of ordinary ones drawn as a
 * single collapsible anchor.
 */
export type SpineSegment =
  | { kind: "turn"; id: string; node: TurnNode }
  | { kind: "run"; id: string; nodes: TurnNode[] };

/** So a run's open state cannot collide with the id of a node in the tree. */
export const RUN_PREFIX = "run:";

/**
 * The thread below one turn, with the uneventful stretches folded up.
 *
 * A long conversation with one branch in it used to draw as twenty rows, and
 * the branch - the one thing this panel exists to point at - was lost among
 * nineteen that only said "and then it carried on". So a stretch of turns
 * that nothing hangs off collapses to one anchor row, and the reader opens it
 * when they want the detail.
 *
 * **A turn stays visible when something hangs off it**: a branch, or several
 * alternative replies. That is not a display preference, it is what keeps the
 * panel navigable - every branch is drawn under the turn whose words it came
 * out of, so the path down to any branch is visible without opening anything.
 * Fold those away and a branch would either float free of its origin or hide
 * behind a count.
 *
 * The walk follows continuations only and stops where the thread stops being
 * a single line, because a fork's arms are drawn as their own blocks and each
 * one segments its own spine.
 */
export function spineSegments(head: TurnNode): SpineSegment[] {
  const segments: SpineSegment[] = [];
  let run: TurnNode[] = [];

  const flush = () => {
    if (run.length === 0) return;
    segments.push({ kind: "run", id: `${RUN_PREFIX}${run[0].id}`, nodes: run });
    run = [];
  };

  const next = (node: TurnNode): TurnNode | null => {
    const continuations = continuationsOf(node);
    return continuations.length === 1 ? continuations[0] : null;
  };

  for (let node = next(head); node !== null; node = next(node)) {
    if (branchesOf(node).length > 0 || continuationsOf(node).length > 1) {
      flush();
      segments.push({ kind: "turn", id: node.id, node });
    } else {
      run.push(node);
    }
  }

  flush();
  return segments;
}

/** Ids from the root down to `id`, inclusive. Empty if it is not in the tree. */
export function ancestorChainIds(roots: TurnNode[], id: string): string[] {
  const found: string[] = [];

  function walk(node: TurnNode, trail: string[]): boolean {
    const here = [...trail, node.id];
    if (node.id === id) {
      found.push(...here);
      return true;
    }
    return node.children.some((child) => walk(child, here));
  }

  roots.some((root) => walk(root, []));
  return found;
}

/**
 * Which groups the tree opens with, before the reader touches anything.
 *
 * Two things are open by default and for different reasons. **The chain down
 * to the view being read**, because a navigator that hides where you are is
 * answering the wrong question. And **alternative replies** - the several
 * answers to one question that regeneration and the eval leave behind - which
 * are not a separate thread of thought at all, just the same one attempted
 * twice, so hiding them would misrepresent what happened.
 *
 * A branch is closed by default. That is the whole point of collapsing: a
 * branch is a different question, and its contents are not what the reader is
 * looking at until they say so.
 *
 * A folded stretch of ordinary turns is never seeded open either, and never
 * needs to be: a turn something hangs off is drawn as its own row, so the way
 * down to any branch is already visible.
 */
export function autoExpanded(roots: TurnNode[], currentFrom: string | null): Set<string> {
  const open = new Set<string>(
    currentFrom === null ? [] : ancestorChainIds(roots, currentFrom),
  );

  for (const node of flattenTurns(roots)) {
    const continuations = node.children.filter((child) => !child.branch);
    if (continuations.length > 1) {
      for (const child of continuations) open.add(child.id);
    }
  }

  return open;
}
