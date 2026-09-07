import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { FormAlert } from "@/components/ui/form-alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TITLE_MAX_LENGTH } from "@/features/conversations/api";
import {
  useConversations,
  useCreateConversation,
} from "@/features/conversations/queries";

/**
 * Starting a conversation.
 *
 * This used to be the list page. The list is a persistent sidebar now, so what
 * is left here is the one thing the sidebar cannot do -- name a new graph and
 * open it -- plus the empty state for someone who has none.
 *
 * The title is asked for here rather than derived from the first message. A
 * conversation is the root of one graph and gets read back in a list, so it
 * carries a name of its own; nothing in the API names it for you.
 */
export default function ConversationsPage() {
  const navigate = useNavigate();
  const { data: conversations } = useConversations();
  const [title, setTitle] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const create = useCreateConversation({
    onSuccess: (conversation) => navigate(`/app/c/${conversation.id}`),
  });

  const isFirst = conversations !== undefined && conversations.length === 0;

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = title.trim();
    // An empty string is a 422: the backend's title is min_length=1. Omitting
    // the field is what asks for the server's 'Untitled', so send undefined.
    create.mutate({ title: trimmed === "" ? undefined : trimmed });
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-xl px-6 py-14 sm:py-20">
        <p className="mb-[6px] font-mono text-[11px] tracking-[0.12em] text-dim uppercase">
          New conversation
        </p>
        <h1 className="mb-3 text-[27px] leading-[1.15] font-semibold tracking-[-0.02em]">
          {isFirst ? "Start your first graph" : "Start a graph"}
        </h1>
        <p className="mb-7 max-w-[58ch] text-[14px] leading-[1.6] text-muted">
          A conversation is the root of one graph. It begins as an ordinary
          linear thread; every reply in it is a node you can later branch from
          by highlighting a span, and each branch inherits a context composed
          from what came before rather than a copy of it.
        </p>

        <form onSubmit={onSubmit} noValidate>
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

          <div className="mt-4 flex items-center gap-3">
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create and open"}
            </Button>
            {/* Strategy is not offered here: the picker is its own slice, and
                until then a new conversation takes the server default. Saying
                so beats a silent choice the user cannot see. */}
            <span className="font-mono text-[11px] text-dim">
              strategy: server default
            </span>
          </div>
        </form>
      </div>
    </div>
  );
}
