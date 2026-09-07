import { useQuery, type QueryClient } from "@tanstack/react-query";
import type { ApiError } from "@/lib/api";
import { listMessages, type ConversationGraph, type MessageCreated } from "./api";

/**
 * One key factory, so a rename cannot leave a stale invalidation pointing at
 * nothing. `all` is the shared prefix; the graph is keyed per conversation.
 */
export const messageKeys = {
  all: ["messages"] as const,
  graph: (conversationId: string) => ["messages", "graph", conversationId] as const,
};

export function useConversationGraph(conversationId: string) {
  return useQuery<ConversationGraph, ApiError>({
    queryKey: messageKeys.graph(conversationId),
    queryFn: () => listMessages(conversationId),
    // A 404 here means the conversation is missing or not yours, which is a
    // real answer rather than a blip. Retrying only delays the empty state.
    retry: (failureCount, error) => error.status !== 404 && failureCount < 1,
  });
}

/**
 * Fold a 201 from POST /messages straight into the cached graph.
 *
 * These are the server's own rows, ids and timestamps included, so this is not
 * an optimistic guess that has to be reconciled later -- it is the same data a
 * refetch would bring back, without the round-trip. Both lists arrive ordered
 * `created_at, id` and the new rows are the newest, so appending preserves it.
 */
export function appendCreatedMessage(
  queryClient: QueryClient,
  conversationId: string,
  created: MessageCreated,
) {
  queryClient.setQueryData<ConversationGraph>(
    messageKeys.graph(conversationId),
    (graph) => {
      if (graph === undefined) return graph;
      return {
        messages: [...graph.messages, created.message],
        edges: created.edge === null ? graph.edges : [...graph.edges, created.edge],
      };
    },
  );
}
