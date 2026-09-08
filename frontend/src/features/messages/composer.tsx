import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

/** Grows with the text, then scrolls. Roughly eight lines. */
const MAX_HEIGHT = 208;

/**
 * The prompt zone.
 *
 * Enter sends and Shift+Enter breaks the line. That is the convention for a
 * chat surface, and a multi-line prompt is common enough here that the
 * alternative would cost a click on every message.
 */
export function Composer({
  onSend,
  disabled,
  placeholder,
  controls,
  variant = "bar",
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
  /**
   * Per-conversation controls, on the bottom row of the box beside the send
   * button. Only the `bar` shape has one -- the empty state is a bare field,
   * and on the start surface there is no conversation to control yet.
   */
  controls?: React.ReactNode;
  /**
   * `bar` pins it to the bottom of a thread, as one box holding the field and
   * its controls. `centred` is the empty-state shape: a bare field in the
   * middle of the pane.
   */
  variant?: "bar" | "centred";
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  const resize = useCallback(() => {
    const element = ref.current;
    if (element === null) return;
    // Reset first: without it the height only ever ratchets upwards, because
    // scrollHeight can never report less than the height already set.
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT)}px`;
  }, []);

  useEffect(() => {
    ref.current?.focus();
  }, []);

  // Content is min_length=1 after stripping on the backend, so whitespace-only
  // text is a 422 rather than an empty message. Trim before deciding.
  const trimmed = text.trim();
  // Only sending is blocked while a reply streams, never typing. Disabling the
  // field would take focus away mid-reply and hand it back to nobody, and
  // sending would abort the reply that is still arriving.
  const canSend = trimmed !== "" && !disabled;

  function submit() {
    if (!canSend) return;
    onSend(trimmed);
    setText("");
    // The height has to be reset by hand: clearing the value does not fire the
    // change handler that would otherwise shrink it back.
    requestAnimationFrame(() => {
      if (ref.current !== null) ref.current.style.height = "auto";
      ref.current?.focus();
    });
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    submit();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    // An IME fires Enter to accept the candidate it is composing, so sending
    // on that keystroke would swallow the word the user was still choosing.
    if (event.nativeEvent.isComposing) return;
    event.preventDefault();
    submit();
  }

  const centred = variant === "centred";

  if (centred) {
    return (
      <form onSubmit={onSubmit} className="w-full px-4">
        <div className="mx-auto flex max-w-2xl items-end gap-2">
          <Textarea
            ref={ref}
            rows={1}
            aria-label="Message"
            className="max-h-[208px] min-h-11 rounded-xl bg-surface px-4 py-[13px] text-[15px]"
            placeholder={placeholder ?? "Ask something"}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              resize();
            }}
            onKeyDown={onKeyDown}
          />
          <Button
            type="submit"
            className="size-11 shrink-0 rounded-xl p-0"
            disabled={!canSend}
            aria-label="Send message"
            title="Send message"
          >
            <ArrowUp />
          </Button>
        </div>
        {/* Only on the empty state, which is the first thing anyone sees and
            the one place the convention is worth teaching. Repeating it under
            every reply says something the reader demonstrated they knew one
            message ago.

            `muted`, not `dim`: this shape sits on the page wash, where dim
            does not clear the contrast floor. */}
        <p className="mx-auto mt-2 max-w-2xl text-center font-mono text-[10px] text-muted">
          Enter sends · Shift + Enter for a new line
        </p>
      </form>
    );
  }

  return (
    <form onSubmit={onSubmit} className="px-4 pt-2 sm:px-6">
      {/* One box holding the field and its controls, rather than a field with
          things arranged around it. The edge is on the box and the field
          inside is bare, so there is one outline rather than two competing
          ones -- and the box takes the focus ring, so typing lights up the
          whole control. */}
      <div
        className={cn(
          "mx-auto max-w-3xl rounded-xl border border-line-strong bg-surface transition-[border-color,box-shadow]",
          "focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--color-accent-tint)]",
        )}
      >
        <Textarea
          ref={ref}
          rows={1}
          aria-label="Message"
          className="max-h-[208px] resize-none rounded-none border-0 bg-transparent px-[13px] pt-3 pb-1 focus-visible:border-0 focus-visible:shadow-none"
          placeholder={placeholder ?? "Ask something"}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            resize();
          }}
          onKeyDown={onKeyDown}
        />

        <div className="flex items-center gap-2 px-2 pt-1 pb-2">
          {controls}
          <Button
            type="submit"
            className="ml-auto size-8 shrink-0 rounded-lg p-0"
            disabled={!canSend}
            aria-label="Send message"
            title="Send message"
          >
            <ArrowUp />
          </Button>
        </div>
      </div>
    </form>
  );
}
