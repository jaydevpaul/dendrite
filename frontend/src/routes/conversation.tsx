import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Check, ChevronRight, Pencil, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FormAlert } from "@/components/ui/form-alert";
import { Input } from "@/components/ui/input";
import { MenuSelect } from "@/components/ui/menu-select";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/format";
import {
  NON_SPAN_STRATEGIES,
  TITLE_MAX_LENGTH,
  type Conversation,
} from "@/features/conversations/api";
import {
  useConversation,
  useUpdateConversation,
} from "@/features/conversations/queries";
import { anchorFromUtf16, type AnchorPayload } from "@/features/messages/anchor";
import type { AnyStrategy, Message } from "@/features/messages/api";
import { Composer } from "@/features/messages/composer";
import {
  MessageTurn,
  PendingUserTurn,
  StreamingTurn,
} from "@/features/messages/message-turn";
import { useConversationGraph } from "@/features/messages/queries";
import {
  clearSelection,
  readSpanSelection,
  type SpanSelection,
} from "@/features/messages/selection";
import { BranchComposer, BranchOffer } from "@/features/messages/span-branch";
import { StartPane } from "@/features/messages/start-pane";
import {
  branchTrail,
  buildThread,
  findGap,
  type TrailStep,
} from "@/features/messages/thread";
import { useChat } from "@/features/messages/use-chat";

/**
 * One conversation, as a linear thread.
 *
 * Linear is a view of the graph, not the shape of the data: the API hands back
 * every node and every link, and this page walks one path down them --
 * continuations only, newest reply at each step.
 *
 * A branch is read by moving where that walk starts. `?from=<message id>`
 * re-roots it at a branch's first message and the walk from there is the
 * same one, so a branch needs no second kind of view and no second request --
 * it is already in the graph this page has. The crumb above the thread says
 * which view is on screen and gets back out of it.
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
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [renaming, setRenaming] = useState(false);

  // Which path is on screen. Null is the main thread; a message id re-roots
  // the walk at a branch. It lives in the address bar rather than in state so
  // a branch can be linked to, reloaded and reached with the back button.
  const from = searchParams.get("from");

  const openView = useCallback(
    (fromMessageId: string | null) => {
      setSearchParams(
        (params) => {
          const next = new URLSearchParams(params);
          if (fromMessageId === null) next.delete("from");
          else next.set("from", fromMessageId);
          return next;
        },
        // A new entry, not a replacement: moving into a branch is a place the
        // reader went, and the back button should take them out of it.
        { replace: false },
      );
    },
    [setSearchParams],
  );

  // A message typed on the start surface, before this conversation existed to
  // send it to. Read once, on mount, so that clearing it out of history below
  // cannot take it away again mid-flight.
  const [handoff] = useState(
    () => (location.state as { firstMessage?: string } | null)?.firstMessage,
  );
  // A ref, not state, and that distinction is load-bearing. React re-runs this
  // effect a second time on mount in development, reusing the same closure --
  // so a state flag still reads false on the second run and the first message
  // is posted twice. A ref is written synchronously and read at call time.
  const handoffSent = useRef(false);
  const send = chat.send;

  useEffect(() => {
    if (handoff === undefined || handoffSent.current) return;
    // Sending does not wait for the graph. A handed-off message is by
    // definition the first one in a conversation that was just created, so
    // its parent is null either way, and waiting would put a loading state on
    // screen for no information.
    handoffSent.current = true;
    // Drop it out of history before sending, so a reload or a
    // back-navigation cannot post the same first message a second time.
    navigate(location.pathname, { replace: true, state: null });
    void send(handoff, null);
  }, [handoff, navigate, location.pathname, send]);

  const thread = useMemo(
    () => (graph.data === undefined ? null : buildThread(graph.data, from)),
    [graph.data, from],
  );
  const trail = useMemo(
    () => (graph.data === undefined ? [] : branchTrail(graph.data, from)),
    [graph.data, from],
  );
  const gap = thread === null ? null : findGap(thread);

  /**
   * Write the branch, move into it, then let the reply stream where it can be
   * read.
   */
  const createBranch = useCallback(
    (
      parentMessageId: string,
      anchor: AnchorPayload,
      text: string,
      strategy: AnyStrategy,
    ) => {
      void send(text, parentMessageId, {
        anchor,
        // SpanOnly is what the anchored link answers with unprompted, so it
        // is sent as no override at all rather than as a stored value saying
        // the same thing.
        strategyOverride: strategy === "SpanOnly" ? undefined : strategy,
        onCreated: (messageId) => openView(messageId),
      });
    },
    [send, openView],
  );

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
  // A reply belongs to the question it answers, so it is only drawn on a path
  // that question is on. Without this, walking out of a branch while its
  // first reply is still arriving would keep rendering that reply at the
  // bottom of the main thread, under a question that is not there.
  const liveOnPath =
    live !== null &&
    (thread?.steps.some((step) => step.message.id === live.userMessageId) ?? false);

  // The handed-off text, shown until the write comes back and the real row
  // takes over. Without this the receiving page renders a loading line, then
  // the start prompt with an empty field, then the message -- three states for
  // one keystroke, which is the flicker.
  // Dropped again if the write fails, so a message that never landed does not
  // sit on screen looking written. The pane falls back to the prompt with the
  // failure above it -- the typed text is lost, which is the accepted cost of
  // not lying about what was saved.
  const inbound =
    handoff !== undefined &&
    chat.error === null &&
    (thread === null || thread.steps.length === 0)
      ? handoff
      : undefined;

  // Nothing written yet, and nothing arriving. The prompt belongs in the
  // middle of the pane rather than pinned to the bottom of an empty one.
  const isEmpty =
    thread !== null &&
    thread.steps.length === 0 &&
    live === null &&
    !graph.isPending &&
    inbound === undefined;

  const sendToTail = (text: string) =>
    void send(text, thread?.tail?.message.id ?? null);

  const sendError =
    chat.error === null ? null : (
      <div className="mx-auto flex w-full max-w-3xl items-start gap-2">
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
    );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {conversation.data ? (
        renaming ? (
          <div className="px-4 pt-3 pb-1 sm:px-6">
            <div className="mx-auto max-w-3xl">
              <RenameForm
                conversation={conversation.data}
                onDone={() => setRenaming(false)}
              />
            </div>
          </div>
        ) : (
          <Header
            conversation={conversation.data}
            onRename={() => setRenaming(true)}
          />
        )
      ) : (
        <div className="h-[36px]" />
      )}

      {isEmpty ? (
        <StartPane error={sendError} onSend={sendToTail} disabled={chat.isBusy} />
      ) : (
        <>
          <Thread
            inbound={inbound}
            // A handed-off message is already on screen, so the thread is not
            // waiting on anything the reader can see.
            pending={graph.isPending && inbound === undefined}
            trail={trail}
            steps={thread?.steps ?? []}
            messagesById={thread?.messagesById ?? EMPTY_MESSAGES}
            records={chat.records}
            live={live}
            liveIsStored={liveIsStored}
            liveOnPath={liveOnPath}
            gap={gap}
            onGenerate={chat.generate}
            onOpenView={openView}
            onCreateBranch={createBranch}
            busy={chat.isBusy}
            loadError={graph.error === null ? null : graph.error.message}
            onRetryLoad={() => void graph.refetch()}
          />

          {sendError ? <div className="px-4 pt-3 sm:px-6">{sendError}</div> : null}

          <Composer
            onSend={sendToTail}
            disabled={graph.isPending || chat.isBusy}
            placeholder="Reply"
            controls={
              conversation.data ? (
                <StrategyControl conversation={conversation.data} />
              ) : null
            }
          />
        </>
      )}

      {/* The last row of the column in both shapes, so it sits under whichever
          prompt is on screen. */}
      {conversation.data ? (
        <ConversationFacts
          conversation={conversation.data}
          // Every message in the conversation, not the length of the path on
          // screen. Reading a branch does not make the rest of it disappear.
          messageCount={graph.data?.messages.length ?? 0}
        />
      ) : null}
    </div>
  );
}

/** A stable empty map, so a loading render does not remount every turn. */
const EMPTY_MESSAGES: Map<string, Message> = new Map();

function Thread({
  inbound,
  pending,
  trail,
  steps,
  messagesById,
  records,
  live,
  liveIsStored,
  liveOnPath,
  gap,
  onGenerate,
  onOpenView,
  onCreateBranch,
  busy,
  loadError,
  onRetryLoad,
}: {
  inbound: string | undefined;
  pending: boolean;
  trail: TrailStep[];
  steps: ReturnType<typeof buildThread>["steps"];
  messagesById: Map<string, Message>;
  records: ReturnType<typeof useChat>["records"];
  live: ReturnType<typeof useChat>["run"];
  liveIsStored: boolean;
  liveOnPath: boolean;
  gap: ReturnType<typeof findGap>;
  onGenerate: (userMessageId: string) => void;
  onOpenView: (fromMessageId: string | null) => void;
  onCreateBranch: (
    parentMessageId: string,
    anchor: AnchorPayload,
    text: string,
    strategy: AnyStrategy,
  ) => void;
  busy: boolean;
  loadError: string | null;
  onRetryLoad: () => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  // Whether the reader is at the bottom. Scrolling up to re-read something
  // while a reply streams must not be undone by the next chunk arriving.
  const pinned = useRef(true);

  // A highlighted span waiting to be branched from, and then the branch being
  // written. Only one at a time: the offer is what turns into the composer.
  const [selection, setSelection] = useState<SpanSelection | null>(null);
  // The rect travels with the draft: the composer opens where the highlight
  // was, and the highlight itself is gone by then - focusing the field drops
  // it - so the measurement has to be kept rather than re-read.
  const [draft, setDraft] = useState<{
    messageId: string;
    anchor: AnchorPayload;
    rect: DOMRect;
  } | null>(null);

  // One listener for the whole thread rather than one per reply. It finds the
  // message a selection lies in by walking up the DOM, so a drag that starts
  // in a reply and runs off the end of it still belongs to that reply.
  useEffect(() => {
    function sync() {
      setSelection(readSpanSelection());
    }
    document.addEventListener("mouseup", sync);
    document.addEventListener("keyup", sync);
    return () => {
      document.removeEventListener("mouseup", sync);
      document.removeEventListener("keyup", sync);
    };
  }, []);

  // The offer is placed by a viewport rectangle, so it stops describing the
  // text the moment anything moves. Dropping it beats chasing it. Passing the
  // updater keeps this free when there is nothing to drop.
  const dismissOffer = useCallback(
    () => setSelection((current) => (current === null ? current : null)),
    [],
  );

  useEffect(() => {
    window.addEventListener("resize", dismissOffer);
    return () => window.removeEventListener("resize", dismissOffer);
  }, [dismissOffer]);

  const onScroll = useCallback(() => {
    dismissOffer();
    const element = scrollRef.current;
    if (element === null) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    pinned.current = distance < 80;
  }, [dismissOffer]);

  useEffect(() => {
    const element = scrollRef.current;
    if (element === null || !pinned.current) return;
    element.scrollTop = element.scrollHeight;
  }, [steps.length, live?.text, live?.phase, gap?.kind, inbound]);

  /**
   * Turn the highlight into an anchor now, not at submit time. The browser
   * drops the selection as soon as focus moves into the composer's field, so
   * the offsets have to be taken while they still exist -- and taking them
   * here means the quote shown above the field is the exact text that will be
   * sent, rather than a second reading of the same range.
   */
  function beginBranch() {
    if (selection === null) return;
    const content = messagesById.get(selection.messageId)?.content;
    if (content === undefined) return;
    const anchor = anchorFromUtf16(content, selection.start, selection.end);
    // Null means the highlight was nothing but whitespace once trimmed. The
    // API refuses that, so no composer opens - and the offer is dropped with
    // it rather than left sitting there doing nothing when pressed.
    if (anchor === null) {
      setSelection(null);
      clearSelection();
      return;
    }
    setDraft({ messageId: selection.messageId, anchor, rect: selection.rect });
    setSelection(null);
    clearSelection();
  }

  return (
    <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
      {selection !== null && draft === null ? (
        <BranchOffer rect={selection.rect} onClick={beginBranch} />
      ) : null}

      {/* Floating at the span rather than inline in the thread: a reply can be
          pages long, and inline meant scrolling away from the words being
          asked about in order to ask. */}
      {draft !== null ? (
        <BranchComposer
          rect={draft.rect}
          quote={draft.anchor.anchored_text}
          busy={busy}
          onCancel={() => setDraft(null)}
          onSubmit={(text, strategy) => {
            onCreateBranch(draft.messageId, draft.anchor, text, strategy);
            setDraft(null);
          }}
        />
      ) : null}

      <div className="mx-auto flex max-w-3xl flex-col gap-7 px-4 py-7 sm:px-6">
        {trail.length > 1 ? <BranchTrail trail={trail} onOpen={onOpenView} /> : null}

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

        {inbound !== undefined ? <PendingUserTurn text={inbound} /> : null}

        {steps.map((step) => (
          <Fragment key={step.message.id}>
            <MessageTurn
              step={step}
              record={records[step.message.id]}
              liveText={
                live !== null && step.message.id === live.assistantMessageId
                  ? live.text
                  : undefined
              }
              streaming={live !== null && step.message.id === live.assistantMessageId}
              messagesById={messagesById}
              onOpenBranch={onOpenView}
            />
          </Fragment>
        ))}

        {/* The row a reply is being written into is not in the cached graph
            yet: it was inserted server-side after the last read, and it stays
            blank until the whole reply is written at the end. So the stream
            renders it until the run finishes -- and only on the path its
            question is on, so walking out of a branch mid-reply leaves the
            reply behind with the question it answers. */}
        {live !== null && liveOnPath && !liveIsStored ? (
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
 * Which path is on screen, and the way back out of it.
 *
 * A branch can be taken from inside a branch, so "back" is not always the
 * main thread -- each crumb is one anchored link crossed on the way down,
 * named by the span it grew from. Only the crumbs behind the reader are
 * buttons; the last one is where they are.
 *
 * This is not the branch navigator. That is a panel holding a tree and a
 * graph over one selection state, and it answers a different question: what
 * else is in this conversation. This one only answers where am I.
 */
function BranchTrail({
  trail,
  onOpen,
}: {
  trail: TrailStep[];
  onOpen: (fromMessageId: string | null) => void;
}) {
  return (
    <nav aria-label="Branch trail" className="flex flex-wrap items-center gap-y-1">
      {trail.map((step, index) => {
        const current = index === trail.length - 1;
        const label =
          step.anchoredText === null
            ? step.fromMessageId === null
              ? "main thread"
              : "this branch"
            : `“${step.anchoredText}”`;

        return (
          <Fragment key={step.fromMessageId ?? "main"}>
            {index > 0 ? (
              <ChevronRight className="size-3 shrink-0 text-line-strong" aria-hidden />
            ) : null}
            {current ? (
              <span
                aria-current="page"
                className="max-w-[24ch] truncate px-1 text-[11.5px] text-ink sm:max-w-[36ch]"
                title={step.anchoredText ?? undefined}
              >
                {label}
              </span>
            ) : (
              <button
                type="button"
                onClick={() => onOpen(step.fromMessageId)}
                className="max-w-[18ch] truncate rounded px-1 text-[11.5px] text-dim transition-colors hover:text-ink sm:max-w-[28ch]"
                title={step.anchoredText ?? "Back to the main thread"}
              >
                {label}
              </button>
            )}
          </Fragment>
        );
      })}
    </nav>
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

function Header({
  conversation,
  onRename,
}: {
  conversation: Conversation;
  onRename: () => void;
}) {
  return (
    <div className="px-4 pt-3 pb-1 sm:px-6">
      <div className="mx-auto flex max-w-3xl items-center gap-2">
        <h1 className="min-w-0 flex-1 truncate text-[15px] leading-[1.3] font-semibold tracking-[-0.015em]">
          {conversation.title}
        </h1>
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0 px-2"
          onClick={onRename}
          aria-label="Rename conversation"
          title="Rename conversation"
        >
          <Pencil />
        </Button>
      </div>
    </div>
  );
}

/**
 * The conversation's own facts, on the line under the prompt.
 *
 * Sans, not mono: "2 messages, created an hour ago" is a sentence with a
 * number in it, not an identifier, and mono was making it look like a
 * readout.
 *
 * Three short values, in plain sight. They were behind a disclosure, which
 * meant a click and a panel to read a message count and two timestamps --
 * more machinery than the information is worth. The conversation id is not
 * here: it is already in the address bar, and nobody reads a uuid off a
 * screen.
 */
function ConversationFacts({
  conversation,
  messageCount,
}: {
  conversation: Conversation;
  messageCount: number;
}) {
  return (
    <p className="px-4 pt-2 pb-3 text-center text-[11px] text-dim sm:px-6">
      {messageCount} {messageCount === 1 ? "message" : "messages"}
      <Dot />
      created{" "}
      <span title={formatAbsoluteTime(conversation.created_at)}>
        {formatRelativeTime(conversation.created_at)}
      </span>
      <Dot />
      updated{" "}
      <span title={formatAbsoluteTime(conversation.updated_at)}>
        {formatRelativeTime(conversation.updated_at)}
      </span>
    </p>
  );
}

function Dot() {
  return <span className="px-[7px] text-line-strong">&middot;</span>;
}

/**
 * The conversation's default composition strategy, in the prompt box.
 *
 * It belongs beside the field for the same reason a model picker does: it is
 * the setting that governs what the next thing you send will do, so it should
 * be where you are about to send it from, not behind a panel somewhere else.
 *
 * `PATCH /conversations/{id}` has accepted this since the conversation layer,
 * so this drives a route that already exists. It is deliberately *not* the
 * strategy picker that belongs with the eval harness: that one chooses at
 * creation time and shows the composed context and token cost beside each arm,
 * so the choice can be made on evidence. This one only stops the default being
 * unchangeable.
 *
 * `SpanOnly` is absent because it is branch-only -- it needs an anchor to
 * compose from, so it can never be a conversation default, and the API answers
 * 422 if you send it. The list mirrors the backend's, in the same order.
 */
function StrategyControl({ conversation }: { conversation: Conversation }) {
  const update = useUpdateConversation(conversation.id);

  return (
    <MenuSelect
      label="Default composition strategy"
      // The explanation lives in the tooltip rather than beside the control:
      // the obvious misreading is that changing this recomposes what has
      // already been answered, and there is no room on this row for a
      // sentence.
      title={
        "Composition strategy for replies generated from now on. " +
        "Replies already in the thread keep the strategy they ran under, " +
        "and a branch can override this."
      }
      value={conversation.default_strategy}
      options={NON_SPAN_STRATEGIES}
      disabled={update.isPending}
      onChange={(strategy) => update.mutate({ default_strategy: strategy })}
      className="max-w-[52vw] sm:max-w-none"
    />
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
