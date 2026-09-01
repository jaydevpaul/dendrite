import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Check, Pencil, X } from "lucide-react";
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

/**
 * One conversation, rendering GET /conversations/{id} and PATCH
 * /conversations/{id} -- the two routes of the conversation layer the list
 * page does not cover.
 *
 * It deliberately stops where the backend stops. There is no thread and no
 * composer, because nothing composes context or calls a model until Layer C.
 */
export default function ConversationPage() {
  const { conversationId } = useParams<{ conversationId: string }>();

  // Split so the query hook always receives a real id and is never called
  // conditionally. The router only matches this route with the param present,
  // so the guard is for types rather than for a reachable state.
  if (!conversationId) return <NotFound />;
  return <Loaded conversationId={conversationId} />;
}

function Loaded({ conversationId }: { conversationId: string }) {
  const { data: conversation, isPending, isError, error, refetch } =
    useConversation(conversationId);

  if (isPending) {
    return (
      <Frame>
        <p className="font-mono text-[11px] tracking-[0.12em] text-dim uppercase">
          Loading conversation
        </p>
      </Frame>
    );
  }

  // 404 covers both "no such id" and "someone else's" -- the backend refuses
  // to distinguish them, because a 403 would confirm the id exists. The copy
  // must not claim to know which case this is.
  if (isError) {
    if (error.status === 404) return <NotFound />;
    return (
      <Frame>
        <FormAlert className="mb-4">{error.message}</FormAlert>
        <Button variant="secondary" size="sm" onClick={() => void refetch()}>
          Try again
        </Button>
      </Frame>
    );
  }

  return (
    <Frame>
      <Header conversation={conversation} />
      <Meta conversation={conversation} />
      <Thread conversation={conversation} />
    </Frame>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-3xl px-6 py-10 sm:py-12">
      <Link
        to="/app"
        className="mb-7 inline-flex items-center gap-[6px] text-[12.5px] text-muted transition-colors hover:text-ink"
      >
        <ArrowLeft className="size-[15px]" />
        All conversations
      </Link>
      {children}
    </div>
  );
}

function Header({ conversation }: { conversation: Conversation }) {
  const [renaming, setRenaming] = useState(false);

  if (renaming) {
    return (
      <RenameForm
        conversation={conversation}
        onDone={() => setRenaming(false)}
      />
    );
  }

  return (
    <div className="flex items-start gap-3">
      <h1 className="min-w-0 flex-1 text-[27px] leading-[1.15] font-semibold tracking-[-0.02em] break-words">
        {conversation.title}
      </h1>
      <Button
        variant="ghost"
        size="sm"
        className="mt-1 shrink-0"
        onClick={() => setRenaming(true)}
        aria-label="Rename conversation"
        title="Rename conversation"
      >
        <Pencil />
      </Button>
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
  // Unchanged or empty is not a save. Empty would be a 422 (the backend's
  // Title is min_length=1), and unchanged would still move `updated_at`,
  // reordering the list for no reason.
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
      {update.error ? (
        <FormAlert className="mb-3">{update.error.message}</FormAlert>
      ) : null}

      <div className="flex items-center gap-2">
        <Input
          ref={inputRef}
          name="title"
          aria-label="Conversation title"
          maxLength={TITLE_MAX_LENGTH}
          className="h-10 text-[16px]"
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

/**
 * The row of facts the schema actually guarantees. Mono throughout: these are
 * ids, timestamps and a strategy label, which is exactly what section 4
 * reserves the mono face for.
 */
function Meta({ conversation }: { conversation: Conversation }) {
  return (
    <dl className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line pb-6">
      <Field label="strategy">
        <StrategyTag strategy={conversation.default_strategy} className="text-muted" />
      </Field>
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
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="font-mono text-[10px] tracking-[0.12em] text-dim uppercase">
        {label}
      </dt>
      <dd className="mt-[2px] font-mono text-[11.5px] text-muted">{children}</dd>
    </div>
  );
}

/**
 * Where the thread will render. `root_message_id` is null until the first
 * message exists, so an empty conversation is a schema fact rather than a
 * placeholder -- and right now every conversation is empty, because the
 * message routes are not built.
 */
function Thread({ conversation }: { conversation: Conversation }) {
  const empty = conversation.root_message_id === null;

  return (
    <section className="mt-8">
      <h2 className="mb-2 text-[15px] font-semibold tracking-[-0.01em]">
        {empty ? "No messages yet" : "Messages"}
      </h2>
      <p className="max-w-[60ch] text-[13.5px] leading-[1.6] text-muted">
        {empty ? (
          <>
            This conversation has no root message. The message and edge routes
            are the next backend layer; the thread, the composer and streaming
            arrive with them.
          </>
        ) : (
          <>
            This conversation has a root message, but the thread view is not
            built yet.{" "}
            <code className="rounded bg-raised px-[5px] py-px font-mono text-[0.9em] text-ink">
              {conversation.root_message_id}
            </code>
          </>
        )}
      </p>
    </section>
  );
}

function NotFound() {
  return (
    <Frame>
      <h1 className="mb-2 text-[23px] leading-[1.2] font-semibold tracking-[-0.02em]">
        This conversation isn't here
      </h1>
      <p className="max-w-[56ch] text-[14px] leading-[1.6] text-muted">
        Either it does not exist or it is not yours. The API answers both the
        same way on purpose &mdash; telling them apart would confirm which ids
        are real.
      </p>
    </Frame>
  );
}
