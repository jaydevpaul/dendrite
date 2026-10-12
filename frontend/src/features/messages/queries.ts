import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import type { ApiError } from "@/lib/api";
import {
  deleteBranch,
  fetchStrategyAt,
  listMessages,
  type ConversationGraph,
  type MessageCreated,
  type StrategyResolution,
} from "./api";
import { conversationKeys } from "@/features/conversations/queries";

/**
 * One key factory, so a rename cannot leave a stale invalidation pointing at
 * nothing. `all` is the shared prefix; the graph is keyed per conversation.
 */
export const messageKeys = {
  all: ["messages"] as const,
  graph: (conversationId: string) => ["messages", "graph", conversationId] as const,
  strategy: (conversationId: string, messageId: string) =>
    ["messages", "strategy", conversationId, messageId] as const,
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

/**
 * What composes at one point in the thread, so a control can say so.
 *
 * Keyed on the message, which is what makes this cheap: the answer for a
 * given message changes only if an edge above it is rewritten, and topology
 * is immutable. Sending moves the key to the new tail rather than
 * invalidating anything.
 *
 * A fallback answer - anything whose `source` is not `edge` - is the
 * conversation default, and the caller reads that live off the conversation
 * itself. So changing the default updates the display with no refetch here,
 * which is the reason `source` is on the wire at all.
 */
export function useStrategyAt(conversationId: string, messageId: string | null) {
  return useQuery<StrategyResolution, ApiError>({
    queryKey: messageKeys.strategy(conversationId, messageId ?? "none"),
    queryFn: () => fetchStrategyAt(conversationId, messageId as string),
    enabled: messageId !== null,
    retry: (failureCount, error) => error.status !== 404 && failureCount < 1,
  });
}

export function useDeleteBranch(
  conversationId: string,
  options?: { onSuccess?: (messageId: string) => void },
) {
  const queryClient = useQueryClient();

  return useMutation<void, ApiError, string>({
    mutationFn: (messageId) => deleteBranch(conversationId, messageId),
    onSuccess: (_result, messageId) => {
      // Refetched rather than patched: the delete takes a whole subtree, and
      // working out locally which rows went is re-implementing the server's
      // walk in the client where it can drift.
      void queryClient.invalidateQueries({ queryKey: messageKeys.graph(conversationId) });
      // The conversation list is ordered by updated_at and shows a message
      // count, both of which just moved.
      void queryClient.invalidateQueries({ queryKey: conversationKeys.all });
      options?.onSuccess?.(messageId);
    },
  });
}
