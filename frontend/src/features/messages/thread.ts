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
 * it must not silently take over this view. Newest-wins is what makes
 * retrying a failed reply work: a retry writes a *second* assistant child of
 * the same question, so the newer attempt becomes the path and the abandoned
 * one drops off it, counted but not shown.
 *
 * A branch is read by re-rooting the same walk. `buildThread` will start from
 * any message rather than from the conversation's root, and the walk from
 * there is the same one -- continuations only, newest child. That is what
 * makes a branch a view of this graph rather than a second kind of thread:
 * the only thing the reader changes is where the path starts.
 */

/** A hard stop, so a malformed graph cannot spin here. Topology is acyclic. */
const MAX_STEPS = 2000;

export interface ThreadStep {
  message: Message;
  /**
   * The link that attached it. Null for the conversation's root message, and
   * null for the first step of a re-rooted view only if that message is the
   * root -- a branch's first step carries the anchored edge it grew from.
   */
  edge: Edge | null;
  /** Continuation children not on this path -- earlier attempts at a reply. */
  otherReplies: number;
  /**
   * Children reached by an anchored edge: branches off this message. Not on
   * this path by construction, and each one is a view the reader can open.
   */
  branchEdges: Edge[];
}

export interface Thread {
  steps: ThreadStep[];
  /** The end of the path, which is what the composer attaches to. */
  tail: ThreadStep | null;
  /** Every message in the conversation, for labelling links off the path. */
  messagesById: Map<string, Message>;
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

/** The two lookups every walk over the graph needs, built once. */
function indexGraph(graph: ConversationGraph) {
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

  return { byId, childEdges, attached };
}

/**
 * One path down the graph. `fromMessageId` re-roots it at a branch; omit it
 * for the main thread, which starts at the conversation's root.
 *
 * An unknown or absent `fromMessageId` falls back to the root rather than
 * rendering nothing, because it arrives from the address bar and a stale
 * bookmark should land somewhere real.
 */
export function buildThread(graph: ConversationGraph, fromMessageId?: string | null): Thread {
  const { byId, childEdges, attached } = indexGraph(graph);

  // The root is the one message nothing points at. The conversation row also
  // records it, but deriving it here keeps this function pure over the graph.
  const root = graph.messages.find((message) => !attached.has(message.id));

  const start =
    fromMessageId === undefined || fromMessageId === null
      ? root
      : (byId.get(fromMessageId) ?? root);

  if (start === undefined) return { steps: [], tail: null, messagesById: byId };

  const steps: ThreadStep[] = [];
  const seen = new Set<string>();
  let current: Message | undefined = start;

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
      branchEdges: children.filter(isBranch).sort(newestFirst),
    });

    current = next === undefined ? undefined : byId.get(next.child_message_id);
  }

  return {
    steps,
    tail: steps.length === 0 ? null : steps[steps.length - 1],
    messagesById: byId,
  };
}

/**
 * Where the reader is, as a chain of views from the main thread down.
 *
 * A branch can be taken from inside a branch, so "back" is not always the
 * main thread. Each anchored edge crossed on the way up to the root is one
 * view, named by the span it grew from, and the last entry is the view being
 * read now.
 */
export interface TrailStep {
  /** What `?from=` holds for this view. Null is the main thread. */
  fromMessageId: string | null;
  /** The span this view branched off. Null for the main thread. */
  anchoredText: string | null;
}

export function branchTrail(
  graph: ConversationGraph,
  fromMessageId: string | null | undefined,
): TrailStep[] {
  const main: TrailStep = { fromMessageId: null, anchoredText: null };
  if (fromMessageId === undefined || fromMessageId === null) return [main];

  const { byId, attached } = indexGraph(graph);
  if (!byId.has(fromMessageId)) return [main];

  const inner: TrailStep[] = [];
  const seen = new Set<string>();
  let current: string | undefined = fromMessageId;

  while (current !== undefined && !seen.has(current)) {
    seen.add(current);
    const edge: Edge | undefined = attached.get(current);
    if (edge === undefined) break;

    if (isBranch(edge)) {
      inner.push({ fromMessageId: current, anchoredText: edge.anchored_text });
    } else if (current === fromMessageId) {
      // The view was opened at a message no branch attached -- a hand-edited
      // address, or a branch whose edge is gone. It is still a real path, so
      // it gets a crumb with no span rather than being silently redirected.
      inner.push({ fromMessageId: current, anchoredText: null });
    }

    current = edge.parent_message_id;
  }

  return [main, ...inner.reverse()];
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
