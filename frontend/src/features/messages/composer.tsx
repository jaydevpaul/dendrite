import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

/** Grows with the text, then scrolls. Roughly eight lines. */
const MAX_HEIGHT = 208;

/**
 * The prompt zone. It sits on `raised`, which is the surface the palette
 * assigns to it -- one step up from the page so the thread reads as the
 * document and this reads as the tool.
 *
 * Enter sends and Shift+Enter breaks the line. That is the convention for a
 * chat surface, and a multi-line prompt is common enough here that the
 * alternative would cost a click on every message.
 */
export function Composer({
  onSend,
  disabled,
  placeholder,
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
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

  return (
    <form onSubmit={onSubmit} className="border-t border-line bg-raised px-4 py-3 sm:px-6">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <Textarea
          ref={ref}
          rows={1}
          aria-label="Message"
          className="max-h-[208px] bg-surface"
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
          className="size-9 shrink-0 p-0"
          disabled={!canSend}
          aria-label="Send message"
          title="Send message"
        >
          <ArrowUp />
        </Button>
      </div>
      <p className="mx-auto mt-2 max-w-3xl font-mono text-[10px] text-dim">
        Enter sends · Shift + Enter for a new line
      </p>
    </form>
  );
}
