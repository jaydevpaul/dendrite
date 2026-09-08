import { request } from "@/lib/api";
import type { NonSpanStrategy } from "@/features/conversations/api";

/**
 * Every strategy a *branch* can resolve to, which is the four a conversation
 * can default to plus SpanOnly. SpanOnly is branch-only -- it needs an anchor
 * to compose from -- so it can appear as what ran, but never as a default.
 */
export type AnyStrategy = NonSpanStrategy | "SpanOnly";

/**
 * What a branch can be asked to compose from, in the order it is offered.
 *
 * `SpanOnly` leads because it is what a branch does with no instruction at
 * all: an anchored link one step off a reply resolves to it on its own. So
 * choosing it sends **no** `strategy_override` -- the edge is left to answer
 * for itself rather than carrying a value that says the same thing.
 *
 * That is not only tidiness. An override is inherited by the rest of the
 * branch, so a stored `SpanOnly` would be the natural answer for every later
 * message in it too -- a follow-up composed from a span and nothing else. The
 * backend already refuses to inherit it that far, and not writing it keeps the
 * two from ever disagreeing.
 */
export const BRANCH_STRATEGIES = [
  "SpanOnly",
  "FullInheritance",
  "ParentOnly",
  "HierarchicalDecay",
  "HierarchicalDecayWithRetrieval",
] as const;

/**
 * Why a message got the strategy it got. Four of the five values answer with
 * the conversation default, so this is the thing that tells "nothing was
 * overridden" apart from "a branch boundary answered" or "the depth guard
 * fired". Mirrors `StrategySource` in `app/models/_shared.py`.
 */
export type StrategySource =
  | "edge"
  | "branch_default"
  | "branch_boundary"
  | "conversation_default"
  | "depth_cap";

/** Mirrors `MessageOut`. `pending` is derived server-side, not a column. */
export interface Message {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  updated_at: string;
  /**
   * True for a blank assistant row -- the only thing that creates one is the
   * generation route's insert before it starts streaming, so blankness means
   * "a reply was started here". After a reload it is what tells the thread to
   * show an unfinished reply rather than an empty message.
   */
  pending: boolean;
}

/**
 * Mirrors `EdgeOut`. All three anchor fields populated means this link is a
 * branch off a highlighted span; all three null means it continues the thread.
 * The API refuses any other combination.
 */
export interface Edge {
  id: string;
  parent_message_id: string;
  child_message_id: string;
  anchor_start: number | null;
  anchor_end: number | null;
  anchored_text: string | null;
  strategy_override: AnyStrategy | null;
  created_at: string;
}

/** Mirrors `ConversationGraph`: every node and every link, as two flat lists. */
export interface ConversationGraph {
  messages: Message[];
  edges: Edge[];
}

export interface MessageCreate {
  role: "user" | "assistant";
  content: string;
  /** Null writes the conversation's root message; a second null is a 409. */
  parent_message_id: string | null;
  anchor_start?: number;
  anchor_end?: number;
  anchored_text?: string;
  strategy_override?: AnyStrategy;
}

/** The 201 body: the new message and the edge that attached it. */
export interface MessageCreated {
  message: Message;
  /** Null for the root message, which has nothing to attach to. */
  edge: Edge | null;
}

/**
 * Content is `min_length=1` after stripping on the backend, so whitespace-only
 * text is a 422 rather than an empty message. The composer trims before
 * sending for that reason.
 */
export function createMessage(conversationId: string, body: MessageCreate) {
  return request<MessageCreated>(`/conversations/${conversationId}/messages`, {
    method: "POST",
    body,
  });
}

/**
 * The whole graph in one call, already ordered `created_at, id` on both lists.
 * The thread derives the path it renders from these two lists -- see
 * `thread.ts`. Do not re-sort.
 */
export function listMessages(conversationId: string) {
  return request<ConversationGraph>(`/conversations/${conversationId}/messages`);
}

export function generatePath(conversationId: string, messageId: string) {
  return `/conversations/${conversationId}/messages/${messageId}/generate`;
}
