import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ChevronRight, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FormAlert } from "@/components/ui/form-alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/format";
import { TITLE_MAX_LENGTH, type Conversation } from "@/features/conversations/api";
import {
  useConversations,
  useCreateConversation,
} from "@/features/conversations/queries";
import { StrategyTag } from "@/features/conversations/strategy-tag";

/**
 * Frontend slice 2 -- the conversation list.
 *
 * Renders exactly what the backend conversation layer ships: GET
 * /conversations for the list and POST /conversations for the composer. There
 * is no message UI here and no tree in the shell; both wait for their own
 * backend layer (design doc section 8.10).
 */
export default function ConversationsPage() {
  const navigate = useNavigate();
  const { data: conversations, isPending, isError, error, refetch } = useConversations();
  const [composing, setComposing] = useState(false);

  const isEmpty = conversations !== undefined && conversations.length === 0;

  return (
    <div className="mx-auto max-w-3xl px-6 py-10 sm:py-14">
      <div className="mb-7 flex items-end justify-between gap-4">
        <div>
          <p className="mb-[6px] font-mono text-[11px] tracking-[0.12em] text-dim uppercase">
            Conversations
          </p>
          <h1 className="text-[27px] leading-[1.15] font-semibold tracking-[-0.02em]">
            Your graphs
          </h1>
        </div>

        {/* Suppressed while the composer is open (it has its own submit) and
            on the empty state, which carries the primary action itself.
            Two filled accent buttons on one screen means no primary action. */}
        {!composing && !isEmpty ? (
          <Button onClick={() => setComposing(true)}>
            <Plus />
            New conversation
          </Button>
        ) : null}
      </div>

      {composing ? (
        <Composer
          onCancel={() => setComposing(false)}
          onCreated={(conversation) => navigate(`/app/c/${conversation.id}`)}
        />
      ) : null}

      {isPending ? <Quiet>Loading conversations</Quiet> : null}

      {isError ? (
        <div>
          <FormAlert className="mb-4">
            Conversations could not be loaded. {error.message}
          </FormAlert>
          <Button variant="secondary" size="sm" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : null}

      {isEmpty && !composing ? (
        <EmptyState onStart={() => setComposing(true)} />
      ) : null}

      {conversations && conversations.length > 0 ? (
        <ul className="border-t border-line">
          {conversations.map((conversation) => (
            <li key={conversation.id}>
              <ConversationRow conversation={conversation} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/**
 * Inline rather than a modal, on purpose. A dialog is the one component in
 * this slice that would genuinely need Radix (design doc section 2), and it
 * buys nothing: there is a single optional field and no destructive choice.
 */
function Composer({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (conversation: Conversation) => void;
}) {
  const [title, setTitle] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const create = useCreateConversation({ onSuccess: onCreated });

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = title.trim();
    // An empty string would be a 422: the backend's Title type is
    // min_length=1. Omitting the field is what asks for the 'Untitled'
    // server default, so send undefined rather than "".
    create.mutate({ title: trimmed === "" ? undefined : trimmed });
  }

  function onKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (event.key === "Escape" && !create.isPending) onCancel();
  }

  return (
    <form
      onSubmit={onSubmit}
      onKeyDown={onKeyDown}
      noValidate
      className="mb-7 rounded-xl border border-line bg-surface p-5"
    >
      {create.error ? (
        <FormAlert className="mb-4">{create.error.message}</FormAlert>
      ) : null}

      <Label htmlFor="conversation-title" className="mb-[5px]">
        Title{" "}
        <span className="font-normal text-dim">
          &mdash; optional, defaults to Untitled
        </span>
      </Label>
      <Input
        id="conversation-title"
        ref={inputRef}
        name="title"
        maxLength={TITLE_MAX_LENGTH}
        placeholder="What are you working through?"
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        disabled={create.isPending}
      />

      <div className="mt-4 flex items-center gap-2">
        <Button type="submit" size="sm" disabled={create.isPending}>
          {create.isPending ? "Creating…" : "Create"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onCancel}
          disabled={create.isPending}
        >
          Cancel
        </Button>
        {/* Strategy is not offered here: the picker is slice 6, and until then
            a new conversation takes the server default. Saying so beats a
            silent choice the user cannot see. */}
        <span className="ml-auto hidden font-mono text-[11px] text-dim sm:inline">
          strategy: server default
        </span>
      </div>
    </form>
  );
}

function ConversationRow({ conversation }: { conversation: Conversation }) {
  const { title, default_strategy, root_message_id, updated_at } = conversation;

  return (
    <Link
      to={`/app/c/${conversation.id}`}
      className="group flex items-center gap-4 border-b border-line px-3 py-[13px] transition-colors hover:bg-raised"
    >
      <div className="min-w-0 flex-1">
        <p className="truncate text-[14.5px] leading-[1.35] font-medium text-ink">
          {title}
        </p>
        <span className="mt-[3px] flex items-center gap-2 truncate">
          <StrategyTag strategy={default_strategy} />
          <span className="text-dim">&middot;</span>
          <span
            className="font-mono text-[11px] text-dim"
            title={formatAbsoluteTime(updated_at)}
          >
            {formatRelativeTime(updated_at)}
          </span>
        </span>
      </div>

      {/* root_message_id is null until the first message exists, so this is a
          fact from the schema, not a guess. */}
      {root_message_id === null ? (
        <span className="hidden rounded border border-line px-[7px] py-[3px] font-mono text-[10px] tracking-[0.08em] text-dim uppercase sm:inline">
          no messages
        </span>
      ) : null}

      <ChevronRight className="size-4 shrink-0 text-dim transition-colors group-hover:text-ink" />
    </Link>
  );
}

function EmptyState({ onStart }: { onStart: () => void }) {
  return (
    <div className="border-t border-line pt-9">
      <h2 className="mb-2 text-[19px] leading-[1.25] font-semibold tracking-[-0.015em]">
        Nothing to branch from yet
      </h2>
      <p className="mb-6 max-w-[56ch] text-[14px] leading-[1.6] text-muted">
        A conversation is the root of one graph. Every branch you take later
        hangs off a span inside a response in this conversation, and inherits a
        context composed from it.
      </p>
      <Button onClick={onStart}>
        <Plus />
        New conversation
      </Button>
    </div>
  );
}

/** Loading text, not a spinner: on a warm cache this is on screen for ms. */
function Quiet({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-mono text-[11px] tracking-[0.12em] text-dim uppercase">
      {children}
    </p>
  );
}
