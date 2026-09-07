import type { ConversationGraph, Edge, Message } from "./api";

/**
 * Turning the graph into one linear thread.
 *
 * The API hands back every node and every link as two flat lists, because the
 * conversation is a tree and there is no single order to serialise it in. A
 * linear view has to choose a path down that tree, and the rule is:
 *
 *   follow continuation edges only, taking the newest child at each step.
 *
 * Both halves matter. Continuation-only keeps branches off the main path -- a
 * branch grown off a highlighted span is a different thread of thought, and
 * once it can be created it must not silently take over this view. Newest-wins
 * is what makes retrying a failed reply work: a retry writes a *second*
 * assistant child of the same question, so the newer attempt becomes the path
 * and the abandoned one drops off it, counted but not shown.
 */

/** A hard stop, so a malformed graph cannot spin here. Topology is acyclic. */
const MAX_STEPS = 2000;

export interface ThreadStep {
  message: Message;
  /** The link that attached it. Null only for the root message. */
  edge: Edge | null;
  /** Continuation children not on this path -- earlier attempts at a reply. */
  otherReplies: number;
  /** Children reached by an anchored edge. Branches; not rendered here. */
  branches: number;
}

export interface Thread {
  steps: ThreadStep[];
  /** The end of the path, which is what the composer attaches to. */
  tail: ThreadStep | null;
}

/** An anchored edge is a branch; all three anchor fields null is a continuation. */
export function isBranch(edge: Edge): boolean {
  return edge.anchor_start !== null;
}

/** Newest first, with the id breaking a same-timestamp tie deterministically. */
function newestFirst(a: Edge, b: Edge): number {
  if (a.created_at !== b.created_at) return a.created_at < b.created_at ? 1 : -1;
  return a.id < b.id ? 1 : -1;
}

export function buildThread(graph: ConversationGraph): Thread {
  const byId = new Map(graph.messages.map((message) => [message.id, message]));

  const childEdges = new Map<string, Edge[]>();
  const attached = new Map<string, Edge>();

  for (const edge of graph.edges) {
    // An edge whose endpoints are not both in this list would mean the two
    // lists disagree, which the API does not do -- skip rather than crash.
    if (!byId.has(edge.parent_message_id) || !byId.has(edge.child_message_id)) {
      continue;
    }
    const siblings = childEdges.get(edge.parent_message_id);
    if (siblings === undefined) childEdges.set(edge.parent_message_id, [edge]);
    else siblings.push(edge);
    attached.set(edge.child_message_id, edge);
  }

  // The root is the one message nothing points at. The conversation row also
  // records it, but deriving it here keeps this function pure over the graph.
  const root = graph.messages.find((message) => !attached.has(message.id));
  if (root === undefined) return { steps: [], tail: null };

  const steps: ThreadStep[] = [];
  const seen = new Set<string>();
  let current: Message | undefined = root;

  while (current !== undefined && steps.length < MAX_STEPS) {
    if (seen.has(current.id)) break;
    seen.add(current.id);

    const children: Edge[] = childEdges.get(current.id) ?? [];
    const continuations: Edge[] = children.filter((edge) => !isBranch(edge));
    const next: Edge | undefined = [...continuations].sort(newestFirst)[0];

    steps.push({
      message: current,
      edge: attached.get(current.id) ?? null,
      otherReplies: Math.max(continuations.length - 1, 0),
      branches: children.length - continuations.length,
    });

    current = next === undefined ? undefined : byId.get(next.child_message_id);
  }

  return { steps, tail: steps.length === 0 ? null : steps[steps.length - 1] };
}

/**
 * Why a thread is waiting, and which user message a reply should be generated
 * for. Both states are legal and both survive a reload, so the thread offers
 * the same button either way rather than pretending nothing happened.
 */
export type Gap =
  | { kind: "unanswered"; userMessageId: string }
  | { kind: "unfinished"; userMessageId: string };

export function findGap(thread: Thread): Gap | null {
  const tail = thread.tail;
  if (tail === null) return null;

  // A question with no reply under it. Generation can fail on its own, and a
  // message can be written without asking for a reply at all, so this is a
  // state the thread has to be able to render and recover from.
  if (tail.message.role === "user") {
    return { kind: "unanswered", userMessageId: tail.message.id };
  }

  // A blank assistant row means a reply was started and never landed -- the
  // tab was closed mid-stream, or the process died between opening the row and
  // writing the text. Its parent is the question to ask again.
  if (tail.message.pending && tail.edge !== null) {
    return { kind: "unfinished", userMessageId: tail.edge.parent_message_id };
  }

  return null;
}
