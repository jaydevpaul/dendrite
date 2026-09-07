import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useParams } from "react-router-dom";
import { Check, Pencil, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FormAlert } from "@/components/ui/form-alert";
import { Input } from "@/components/ui/input";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/format";
import { TITLE_MAX_LENGTH, type Conversation } from "@/features/conversations/api";
import {
  useConversation,
  useUpdateConversation,
} from "@/features/conversations/queries";
import { StrategyTag } from "@/features/conversations/strategy-tag";
import { Composer } from "@/features/messages/composer";
import { MessageTurn, StreamingTurn } from "@/features/messages/message-turn";
import { useConversationGraph } from "@/features/messages/queries";
import { buildThread, findGap } from "@/features/messages/thread";
import { useChat } from "@/features/messages/use-chat";

/**
 * One conversation, as a linear thread.
 *
 * Linear is a view of the graph, not the shape of the data: the API hands back
 * every node and every link, and this page walks one path down them --
 * continuations only, newest reply at each step. Branches are counted where
 * they hang off the path, and rendered by their own slice.
 */
export default function ConversationPage() {
  const { conversationId } = useParams<{ conversationId: string }>();

  // The router only matches this route with the param present, so this guard
  // is for types rather than for a reachable state.
  if (!conversationId) return <NotFound />;

  // Keyed on the id so switching conversations remounts. Without it the chat
  // state -- including a reply still streaming -- would follow the user into
  // the next conversation and render there.
  return <Chat key={conversationId} conversationId={conversationId} />;
}

function Chat({ conversationId }: { conversationId: string }) {
  const conversation = useConversation(conversationId);
  const graph = useConversationGraph(conversationId);
  const chat = useChat(conversationId);

  const thread = useMemo(
    () => (graph.data === undefined ? null : buildThread(graph.data)),
    [graph.data],
  );
  const gap = thread === null ? null : findGap(thread);

  // A conversation that is missing or not yours answers 404 either way -- the
  // API refuses to tell them apart, because a 403 would confirm the id exists.
  if (conversation.error?.status === 404 || graph.error?.status === 404) {
    return <NotFound />;
  }

  const live = chat.run;
  // Once a run finishes the graph is read again, so the row it wrote into is
  // in the thread and renders from storage rather than from the stream.
  const liveIsStored =
    live !== null &&
    live.assistantMessageId !== null &&
    (thread?.steps.some((step) => step.message.id === live.assistantMessageId) ?? false);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {conversation.data ? (
        <Header
          conversation={conversation.data}
          messageCount={thread?.steps.length ?? 0}
        />
      ) : (
        <div className="h-[57px] border-b border-line" />
      )}

      <Thread
        pending={graph.isPending}
        steps={thread?.steps ?? []}
        records={chat.records}
        live={live}
        liveIsStored={liveIsStored}
        gap={gap}
        onGenerate={chat.generate}
        busy={chat.isBusy}
        loadError={graph.error === null ? null : graph.error.message}
        onRetryLoad={() => void graph.refetch()}
      />

      {chat.error !== null ? (
        <div className="px-4 pt-3 sm:px-6">
          <div className="mx-auto flex max-w-3xl items-start gap-2">
            <FormAlert className="flex-1">{chat.error}</FormAlert>
            <Button
              variant="ghost"
              size="sm"
              className="px-2"
              onClick={chat.dismissError}
              aria-label="Dismiss"
              title="Dismiss"
            >
              <X />
            </Button>
          </div>
        </div>
      ) : null}

      <Composer
        onSend={(text) => void chat.send(text, thread?.tail?.message.id ?? null)}
        disabled={graph.isPending || chat.isBusy}
        placeholder={
          thread !== null && thread.steps.length === 0
            ? "Start this conversation"
            : "Reply"
        }
      />
    </div>
  );
}

function Thread({
  pending,
  steps,
  records,
  live,
  liveIsStored,
  gap,
  onGenerate,
  busy,
  loadError,
  onRetryLoad,
}: {
  pending: boolean;
  steps: ReturnType<typeof buildThread>["steps"];
  records: ReturnType<typeof useChat>["records"];
  live: ReturnType<typeof useChat>["run"];
  liveIsStored: boolean;
  gap: ReturnType<typeof findGap>;
  onGenerate: (userMessageId: string) => void;
  busy: boolean;
  loadError: string | null;
  onRetryLoad: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // Whether the reader is at the bottom. Scrolling up to re-read something
  // while a reply streams must not be undone by the next chunk arriving.
  const pinned = useRef(true);

  const onScroll = useCallback(() => {
    const element = scrollRef.current;
    if (element === null) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    pinned.current = distance < 80;
  }, []);

  useEffect(() => {
    const element = scrollRef.current;
    if (element === null || !pinned.current) return;
    element.scrollTop = element.scrollHeight;
  }, [steps.length, live?.text, live?.phase, gap?.kind]);

  return (
    <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-7 px-4 py-7 sm:px-6">
        {pending ? (
          <p className="font-mono text-[11px] tracking-[0.12em] text-dim uppercase">
            Loading thread
          </p>
        ) : null}

        {loadError !== null ? (
          <div>
            <FormAlert className="mb-3">
              The thread could not be loaded. {loadError}
            </FormAlert>
            <Button variant="secondary" size="sm" onClick={onRetryLoad}>
              Try again
            </Button>
          </div>
        ) : null}

        {!pending && loadError === null && steps.length === 0 && live === null ? (
          <EmptyThread />
        ) : null}

        {steps.map((step) => (
          <MessageTurn
            key={step.message.id}
            step={step}
            record={records[step.message.id]}
            liveText={
              live !== null && step.message.id === live.assistantMessageId
                ? live.text
                : undefined
            }
            streaming={live !== null && step.message.id === live.assistantMessageId}
          />
        ))}

        {/* The row a reply is being written into is not in the cached graph
            yet: it was inserted server-side after the last read, and it stays
            blank until the whole reply is written at the end. So the stream
            renders it until the run finishes. */}
        {live !== null && !liveIsStored ? (
          <StreamingTurn text={live.text} phase={live.phase} />
        ) : null}

        {gap !== null && live === null ? (
          <Gap
            kind={gap.kind}
            onGenerate={() => void onGenerate(gap.userMessageId)}
            busy={busy}
          />
        ) : null}
      </div>
    </div>
  );
}

/**
 * A question with no reply under it, or a reply that was started and never
 * landed. Both are legal states that survive a reload, and both are recovered
 * the same way: ask for a reply to that question again.
 *
 * Nothing here happens on its own. Generating on mount would call the model
 * every time a thread whose generation keeps failing is reopened, and with a
 * real key that is real money.
 */
function Gap({
  kind,
  onGenerate,
  busy,
}: {
  kind: "unanswered" | "unfinished";
  onGenerate: () => void;
  busy: boolean;
}) {
  return (
    <div className="border-l-2 border-line-strong pl-4">
      <p className="mb-3 max-w-[58ch] text-[13.5px] leading-[1.55] text-muted">
        {kind === "unanswered"
          ? "This message has no reply yet."
          : "A reply was started here and never landed. Asking again writes a new one and leaves the abandoned attempt in the graph."}
      </p>
      <Button variant="secondary" size="sm" onClick={onGenerate} disabled={busy}>
        <RefreshCw />
        {kind === "unanswered" ? "Generate reply" : "Try again"}
      </Button>
    </div>
  );
}

function EmptyThread() {
  return (
    <div className="pt-4">
      <h2 className="mb-2 text-[19px] leading-[1.25] font-semibold tracking-[-0.015em]">
        Nothing here yet
      </h2>
      <p className="max-w-[58ch] text-[14px] leading-[1.6] text-muted">
        Ask the first question below. Every reply becomes a node you can branch
        from later, and the context a branch inherits is composed rather than
        copied.
      </p>
    </div>
  );
}

function Header({
  conversation,
  messageCount,
}: {
  conversation: Conversation;
  messageCount: number;
}) {
  const [renaming, setRenaming] = useState(false);

  return (
    <div className="border-b border-line px-4 py-3 sm:px-6">
      <div className="mx-auto max-w-3xl">
        {renaming ? (
          <RenameForm conversation={conversation} onDone={() => setRenaming(false)} />
        ) : (
          <div className="flex items-center gap-3">
            <h1 className="min-w-0 flex-1 truncate text-[16px] leading-[1.3] font-semibold tracking-[-0.015em]">
              {conversation.title}
            </h1>
            <StrategyTag strategy={conversation.default_strategy} />
            <Button
              variant="ghost"
              size="sm"
              className="shrink-0 px-2"
              onClick={() => setRenaming(true)}
              aria-label="Rename conversation"
              title="Rename conversation"
            >
              <Pencil />
            </Button>
          </div>
        )}

        {/* The facts the schema guarantees, folded away. They were a whole row
            on the old detail page; here the thread is the content and these
            are reference. `details` is native, so it costs no dependency. */}
        <details className="mt-1">
          <summary className="inline-flex cursor-pointer list-none font-mono text-[10px] tracking-[0.1em] text-dim uppercase transition-colors hover:text-muted">
            {messageCount} {messageCount === 1 ? "message" : "messages"} &middot; details
          </summary>
          <dl className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1">
            <Field label="created">
              <span title={formatAbsoluteTime(conversation.created_at)}>
                {formatRelativeTime(conversation.created_at)}
              </span>
            </Field>
            <Field label="updated">
              <span title={formatAbsoluteTime(conversation.updated_at)}>
                {formatRelativeTime(conversation.updated_at)}
              </span>
            </Field>
            <Field label="id">
              <span className="break-all">{conversation.id}</span>
            </Field>
          </dl>
        </details>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="font-mono text-[9.5px] tracking-[0.12em] text-dim uppercase">
        {label}
      </dt>
      <dd className="font-mono text-[11px] text-muted">{children}</dd>
    </div>
  );
}

function RenameForm({
  conversation,
  onDone,
}: {
  conversation: Conversation;
  onDone: () => void;
}) {
  const [title, setTitle] = useState(conversation.title);
  const inputRef = useRef<HTMLInputElement>(null);
  const update = useUpdateConversation(conversation.id);

  useEffect(() => {
    inputRef.current?.select();
  }, []);

  const trimmed = title.trim();
  // Empty would be a 422 -- the backend's title is min_length=1 -- and
  // unchanged would still move updated_at, reordering the sidebar for nothing.
  const canSave = trimmed !== "" && trimmed !== conversation.title;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSave) return;
    update.mutate({ title: trimmed }, { onSuccess: onDone });
  }

  function onKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (event.key === "Escape" && !update.isPending) onDone();
  }

  return (
    <form onSubmit={onSubmit} onKeyDown={onKeyDown} noValidate>
      {update.error ? <FormAlert className="mb-2">{update.error.message}</FormAlert> : null}
      <div className="flex items-center gap-2">
        <Input
          ref={inputRef}
          name="title"
          aria-label="Conversation title"
          maxLength={TITLE_MAX_LENGTH}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          disabled={update.isPending}
        />
        <Button
          type="submit"
          size="sm"
          className="shrink-0"
          disabled={!canSave || update.isPending}
          aria-label="Save title"
          title="Save title"
        >
          <Check />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="shrink-0"
          onClick={onDone}
          disabled={update.isPending}
          aria-label="Cancel rename"
          title="Cancel rename"
        >
          <X />
        </Button>
      </div>
    </form>
  );
}

function NotFound() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-12">
      <h1 className="mb-2 text-[23px] leading-[1.2] font-semibold tracking-[-0.02em]">
        This conversation isn&rsquo;t here
      </h1>
      <p className="max-w-[56ch] text-[14px] leading-[1.6] text-muted">
        Either it does not exist or it is not yours. The API answers both the
        same way on purpose &mdash; telling them apart would confirm which ids
        are real.
      </p>
    </div>
  );
}
