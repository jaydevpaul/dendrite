import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/lib/api";
import {
  DEFAULT_TITLE,
  titleFromMessage,
  updateConversation,
  type Conversation,
} from "@/features/conversations/api";
import { conversationKeys } from "@/features/conversations/queries";
import { createMessage, generatePath, type AnyStrategy, type StrategySource } from "./api";
import { appendCreatedMessage, messageKeys } from "./queries";
import { readGeneration, type StartData } from "./stream";

/**
 * Sending a message and streaming the reply.
 *
 * Two requests, in this order and never merged: one writes the user message
 * and its edge, the second asks for a reply to that message id. They stay
 * separate because a question with no reply is a legal state -- generation can
 * fail, and the same question can be answered more than once -- so the reply
 * route has to name an existing message either way.
 */

/** A reply arriving right now. Lives in memory only. */
export interface LiveRun {
  userMessageId: string;
  /** Known only once `start` arrives; nothing renders before that. */
  assistantMessageId: string | null;
  strategy: AnyStrategy | null;
  source: StrategySource | null;
  model: string | null;
  text: string;
  phase: "opening" | "streaming";
}

/**
 * What a finished run reported about itself, kept for as long as the tab is
 * open. Token counts are the provider's own, never counted here, and there is
 * no route yet that reads them back -- so this is per-session by construction.
 */
export interface RunRecord {
  strategy: AnyStrategy;
  source: StrategySource;
  model: string;
  generationId: string;
  inputTokens: number | null;
  outputTokens: number | null;
  degradations: string[];
}

export function useChat(conversationId: string) {
  const queryClient = useQueryClient();
  const [run, setRun] = useState<LiveRun | null>(null);
  const [records, setRecords] = useState<Record<string, RunRecord>>({});
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Navigating away has to close the stream. The generation itself carries on
  // server-side with nobody reading it, which is why the row it was writing
  // into can be left unfinished -- the thread offers that reply again rather
  // than pretending it completed.
  useEffect(() => () => abortRef.current?.abort(), []);

  const refetchGraph = useCallback(
    () =>
      queryClient.refetchQueries({ queryKey: messageKeys.graph(conversationId) }),
    [queryClient, conversationId],
  );

  /**
   * Name the conversation after its first message, if it still has the server
   * default name. Best-effort: a failed rename is cosmetic, and it must never
   * take the message that was just written down with it.
   */
  const nameFromFirstMessage = useCallback(
    async (text: string) => {
      const conversation = queryClient.getQueryData<Conversation>(
        conversationKeys.detail(conversationId),
      );
      // No cached conversation means this hook cannot know whether the name is
      // the default one, and guessing would overwrite a real title.
      if (conversation === undefined || conversation.title !== DEFAULT_TITLE) return;

      try {
        const renamed = await updateConversation(conversationId, {
          title: titleFromMessage(text),
        });
        queryClient.setQueryData(conversationKeys.detail(conversationId), renamed);
      } catch {
        // Leave it called Untitled. The user can rename it from the header.
      }
    },
    [conversationId, queryClient],
  );

  const generate = useCallback(
    async (userMessageId: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setError(null);
      setRun({
        userMessageId,
        assistantMessageId: null,
        strategy: null,
        source: null,
        model: null,
        text: "",
        phase: "opening",
      });

      // `start`'s fields are held locally as well as in state, because `done`
      // needs them in the same tick they are used and a state update is not
      // readable that soon.
      let started: StartData | null = null;

      try {
        for await (const event of readGeneration(
          generatePath(conversationId, userMessageId),
          controller.signal,
        )) {
          if (event.type === "start") {
            started = event.data;
            setRun((current) =>
              current === null
                ? current
                : {
                    ...current,
                    assistantMessageId: event.data.assistant_message_id,
                    // The arm that actually ran, which is not always the
                    // conversation default -- a fallback records itself.
                    strategy: event.data.strategy,
                    source: event.data.source,
                    model: event.data.model,
                    phase: "streaming",
                  },
            );
          } else if (event.type === "chunk") {
            setRun((current) =>
              current === null ? current : { ...current, text: current.text + event.data.text },
            );
          } else if (event.type === "done") {
            // `start` always precedes `done`, so this is never null in
            // practice -- but keying a record on an id we were not given
            // would attach it to the wrong message, so it is checked.
            if (started !== null) {
              const record: RunRecord = {
                strategy: started.strategy,
                source: started.source,
                model: started.model,
                generationId: event.data.generation_id,
                inputTokens: event.data.input_tokens,
                outputTokens: event.data.output_tokens,
                degradations: event.data.degradations,
              };
              const id = started.assistant_message_id;
              setRecords((existing) => ({ ...existing, [id]: record }));
            }
            // Refetch BEFORE dropping the live text. The assistant row was
            // blank in the cache (or absent from it), so clearing first would
            // flash an unfinished reply between the last chunk and the refetch.
            await refetchGraph();
            setRun(null);
          } else {
            setError(event.data.detail);
            // The blank row and the failure record are both on disk now, so
            // the thread can show the gap and offer the question again.
            await refetchGraph();
            setRun(null);
          }
        }
      } catch (caught) {
        // An abort is us, not a failure: the user navigated or started another
        // reply, and there is nothing to report.
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(
          caught instanceof ApiError || caught instanceof Error
            ? caught.message
            : "The reply could not be streamed.",
        );
        await refetchGraph();
        setRun(null);
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [conversationId, refetchGraph],
  );

  const send = useCallback(
    async (text: string, parentMessageId: string | null) => {
      setError(null);
      setSending(true);
      try {
        const created = await createMessage(conversationId, {
          role: "user",
          content: text,
          parent_message_id: parentMessageId,
        });

        appendCreatedMessage(queryClient, conversationId, created);

        // The root message is the one that names the conversation. Awaited
        // before the list is invalidated so the sidebar refetches once, with
        // the new name already on the row.
        if (parentMessageId === null) await nameFromFirstMessage(text);

        // Writing a message moves the conversation's updated_at, which is the
        // sidebar list's sort key -- so the list is genuinely stale, not just
        // showing an old label.
        void queryClient.invalidateQueries({ queryKey: conversationKeys.all });

        await generate(created.message.id);
      } catch (caught) {
        setError(
          caught instanceof ApiError || caught instanceof Error
            ? caught.message
            : "The message could not be sent.",
        );
      } finally {
        setSending(false);
      }
    },
    [conversationId, queryClient, generate, nameFromFirstMessage],
  );

  return {
    run,
    records,
    error,
    sending,
    isBusy: sending || run !== null,
    send,
    generate,
    dismissError: useCallback(() => setError(null), []),
  };
}
