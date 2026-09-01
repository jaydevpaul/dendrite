import { request } from "@/lib/api";

/**
 * The four strategies a *conversation* can default to.
 *
 * Mirrors `NonSpanStrategy` in `app/models/_shared.py`, in the same order.
 * `SpanOnly` is deliberately absent: it is branch-only and never a
 * conversation default (decision record section 5).
 */
export const NON_SPAN_STRATEGIES = [
  "FullInheritance",
  "ParentOnly",
  "HierarchicalDecay",
  "HierarchicalDecayWithRetrieval",
] as const;

export type NonSpanStrategy = (typeof NON_SPAN_STRATEGIES)[number];

/** Mirrors the backend's `ConversationOut` -- everything a response carries. */
export interface Conversation {
  id: string;
  title: string;
  default_strategy: NonSpanStrategy;
  /** Null until the first message exists, i.e. the conversation is empty. */
  root_message_id: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Title is `Annotated[str, StringConstraints(min_length=1, max_length=200)]`
 * on the backend, so an empty string is a 422 rather than "use the default".
 * Omit the field entirely to get the server's `'Untitled'`.
 */
export const TITLE_MAX_LENGTH = 200;

/**
 * `default_strategy` is accepted by POST /conversations but not surfaced yet:
 * the strategy picker is slice 6, and until then a new conversation takes the
 * server default (`DEFAULT_STRATEGY`, currently HierarchicalDecayWithRetrieval).
 */
export interface ConversationCreate {
  title?: string;
}

export interface ConversationUpdate {
  title?: string;
  default_strategy?: NonSpanStrategy;
}

export function createConversation(body: ConversationCreate) {
  return request<Conversation>("/conversations", { method: "POST", body });
}

/** Already ordered `updated_at desc, id desc` by the backend -- do not re-sort. */
export function listConversations() {
  return request<Conversation[]>("/conversations");
}

/**
 * A conversation belonging to someone else answers **404, not 403** -- a 403
 * would confirm the id exists. So "not found" and "not yours" are one state
 * here, and the UI must not claim to know which.
 */
export function getConversation(id: string) {
  return request<Conversation>(`/conversations/${id}`);
}

export function updateConversation(id: string, body: ConversationUpdate) {
  return request<Conversation>(`/conversations/${id}`, { method: "PATCH", body });
}
