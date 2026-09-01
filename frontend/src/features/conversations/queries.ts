import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ApiError } from "@/lib/api";
import {
  createConversation,
  getConversation,
  listConversations,
  updateConversation,
  type Conversation,
  type ConversationCreate,
  type ConversationUpdate,
} from "./api";

/**
 * One key factory rather than string literals at call sites, so a rename
 * cannot leave a stale invalidation silently pointing at nothing.
 *
 * `all` is the shared prefix: invalidating it covers the list and every
 * detail entry, which is what a mutation that changes `updated_at` needs
 * (the list is ordered by it).
 */
export const conversationKeys = {
  all: ["conversations"] as const,
  list: ["conversations", "list"] as const,
  detail: (id: string) => ["conversations", "detail", id] as const,
};

export function useConversations() {
  return useQuery<Conversation[], ApiError>({
    queryKey: conversationKeys.list,
    queryFn: listConversations,
  });
}

export function useConversation(id: string) {
  return useQuery<Conversation, ApiError>({
    queryKey: conversationKeys.detail(id),
    queryFn: () => getConversation(id),
    // A 404 is a real answer here (missing, or someone else's), not a blip.
    // Retrying it just delays the empty state by a round-trip.
    retry: (failureCount, error) => error.status !== 404 && failureCount < 1,
  });
}

export function useCreateConversation(options?: {
  onSuccess?: (conversation: Conversation) => void;
}) {
  const queryClient = useQueryClient();

  return useMutation<Conversation, ApiError, ConversationCreate>({
    mutationFn: createConversation,
    onSuccess: (conversation) => {
      // Seed the detail cache from the 201 body so navigating straight into
      // the new conversation renders without a second round-trip.
      queryClient.setQueryData(conversationKeys.detail(conversation.id), conversation);
      void queryClient.invalidateQueries({ queryKey: conversationKeys.list });
      options?.onSuccess?.(conversation);
    },
  });
}

export function useUpdateConversation(id: string) {
  const queryClient = useQueryClient();

  return useMutation<Conversation, ApiError, ConversationUpdate>({
    mutationFn: (body) => updateConversation(id, body),
    onSuccess: (conversation) => {
      queryClient.setQueryData(conversationKeys.detail(id), conversation);
      // PATCH moves `updated_at`, which is the list's sort key, so the list
      // is genuinely stale -- not just showing an old title.
      void queryClient.invalidateQueries({ queryKey: conversationKeys.list });
    },
  });
}
