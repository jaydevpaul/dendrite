import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { GitBranch, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MenuSelect } from "@/components/ui/menu-select";
import { Textarea } from "@/components/ui/textarea";
import { BRANCH_STRATEGIES, type AnyStrategy } from "./api";

/**
 * The two pieces of taking a branch from a highlighted span: the offer that
 * follows a selection, and the prompt that replaces it.
 */

/** Roughly the button's own height, used to decide above or below the span. */
const OFFER_HEIGHT = 40;

/**
 * The offer, floating at the end of the selection.
 *
 * Fixed rather than absolutely positioned inside the thread, because the
 * measurement it is placed by is a viewport rectangle. Fixed positioning also
 * means it does not move with the scroller, which is why the caller dismisses
 * it on scroll instead of trying to keep it attached.
 *
 * It sits *below* the selection where there is room. Above would cover the
 * last line the reader just highlighted, which is the line they are looking
 * at when they decide to branch.
 */
export function BranchOffer({ rect, onClick }: { rect: DOMRect; onClick: () => void }) {
  const below = rect.bottom + OFFER_HEIGHT + 8 < window.innerHeight;
  const centre = Math.min(Math.max(rect.left + rect.width / 2, 90), window.innerWidth - 90);

  return (
    <div
      className="fixed z-50 -translate-x-1/2"
      style={{ left: centre, top: below ? rect.bottom + 8 : rect.top - OFFER_HEIGHT - 8 }}
    >
      <Button
        size="sm"
        // `onMouseDown` with the default prevented, not `onClick`: a mousedown
        // anywhere outside the highlighted text collapses the selection, and
        // the selection is the thing being acted on.
        onMouseDown={(event) => {
          event.preventDefault();
          onClick();
        }}
      >
        <GitBranch />
        Branch from this
      </Button>
    </div>
  );
}

/** Enough room for the panel below the span before it flips above it. */
const COMPOSER_HEIGHT = 168;
/** Wide enough for a question, narrow enough to read as attached to a phrase. */
const COMPOSER_WIDTH = 520;

/**
 * The prompt for a new branch, floating where the span is.
 *
 * It opens **at the selection**, taking the place of the offer that was just
 * pressed, rather than inline under the reply. Inline was tried and was wrong
 * for one plain reason: a reply can be pages long, so the field would open far
 * below the words it is about and the reader had to scroll away from them to
 * type. The referent staying on screen is the whole point of anchoring - the
 * question gets to say "that" and mean something.
 *
 * The span is also quoted in the panel, because opening this moves focus into
 * a textarea and the browser drops the highlight when it does. So the quote is
 * what survives that, and the marked words are still a few lines away.
 *
 * Fixed, and deliberately not tracking the scroller: the position comes from a
 * viewport rectangle taken when the selection was read. Unlike the offer it is
 * *not* dismissed on scroll, because by then there is typing in it to lose -
 * it stays where it was opened until it is sent, cancelled, or Escaped.
 *
 * The strategy decides how much of the conversation above the span comes with
 * the question -- nothing but the span, the parent turn, the whole chain, or
 * the chain at decaying fidelity. It writes `strategy_override` on the
 * anchored link, which the schema has carried since the message layer.
 *
 * `SpanOnly` leads and is the default, because that is what the link resolves
 * to with no override at all -- so choosing it sends nothing rather than
 * storing a value that says the same thing.
 *
 * It is **not** the picker that belongs with the eval harness. That one shows
 * the composed context and the token cost beside each arm, so the choice can
 * be made on evidence. This one only stops the choice being unavailable.
 */
export function BranchComposer({
  rect,
  quote,
  onSubmit,
  onCancel,
  busy,
}: {
  /** Where the highlight ended, in viewport coordinates. */
  rect: DOMRect;
  quote: string;
  onSubmit: (text: string, strategy: AnyStrategy) => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const [text, setText] = useState("");
  const [strategy, setStrategy] = useState<AnyStrategy>("SpanOnly");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // `preventScroll`, because focusing a field the browser considers off
    // centre scrolls it into view - and this one opens in the middle of a
    // thread, so the reply the span was taken from would slide away at the
    // moment the reader is about to write about it.
    ref.current?.focus({ preventScroll: true });
  }, []);

  const trimmed = text.trim();
  const canSend = trimmed !== "" && !busy;

  function submit() {
    if (!canSend) return;
    onSubmit(trimmed, strategy);
  }

  function onFormSubmit(event: FormEvent) {
    event.preventDefault();
    submit();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Escape") {
      if (!busy) onCancel();
      return;
    }
    if (event.key !== "Enter" || event.shiftKey) return;
    if (event.nativeEvent.isComposing) return;
    event.preventDefault();
    submit();
  }

  // Below the span where there is room, above it otherwise, and never past
  // either edge of the window.
  const below = rect.bottom + COMPOSER_HEIGHT + 8 < window.innerHeight;
  const half = Math.min(COMPOSER_WIDTH, window.innerWidth - 32) / 2;
  const centre = Math.min(
    Math.max(rect.left + rect.width / 2, half + 16),
    window.innerWidth - half - 16,
  );

  return (
    <form
      onSubmit={onFormSubmit}
      style={{
        left: centre,
        top: below ? rect.bottom + 8 : undefined,
        bottom: below ? undefined : window.innerHeight - rect.top + 8,
      }}
      className={
        // A floating layer over the thread, so it carries a shadow -- the same
        // reason the one menu in the app has one. The accent edge marks it as
        // a branch being made, which is the accent's own job.
        "fixed z-50 w-[min(520px,calc(100vw-2rem))] -translate-x-1/2 rounded-xl " +
        "border border-line-strong border-l-2 border-l-accent bg-surface p-2 " +
        "shadow-[0_12px_34px_rgb(0_0_0/0.42)]"
      }
      noValidate
    >
      {/* The referent, and the controls that belong to it. Truncated rather
          than wrapped: this says which words the question is about, and the
          words themselves are still on screen behind the panel. */}
      <div className="flex items-center gap-1.5 pl-1">
        <p
          className="min-w-0 flex-1 truncate font-serif text-[13px] leading-[1.5] text-muted"
          title={quote}
        >
          &ldquo;{quote}&rdquo;
        </p>
        <MenuSelect
          label="Context for this branch"
          title={
            "How much of the conversation above the span comes with this " +
            "question. SpanOnly sends the highlight and nothing else; the " +
            "others add the parent turn, the whole chain, or the chain at " +
            "decaying fidelity. Later messages in this branch inherit it."
          }
          value={strategy}
          options={BRANCH_STRATEGIES}
          disabled={busy}
          onChange={setStrategy}
          // Down, not up: this sits in the middle of the thread, and a list
          // opening upward would cover the reply the span was taken from.
          direction="down"
          className="max-w-[40vw] shrink-0 sm:max-w-none"
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="shrink-0 px-1.5"
          onClick={onCancel}
          disabled={busy}
          aria-label="Cancel branch"
          title="Cancel branch"
        >
          <X />
        </Button>
      </div>

      {/* The field is the panel's own surface: a second border inside a
          bordered, floating box is one edge too many. */}
      <Textarea
        ref={ref}
        rows={2}
        aria-label="Ask about this span"
        className="max-h-[120px] border-0 bg-transparent px-1 py-1 text-[14.5px] focus-visible:shadow-none"
        placeholder="Ask about this"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
      />

      <div className="mt-1 flex items-center gap-2 pl-1">
        <p className="font-mono text-[10px] tracking-[0.08em] text-dim uppercase">
          Enter branches
        </p>
        <Button type="submit" size="sm" className="ml-auto" disabled={!canSend}>
          <GitBranch />
          Branch
        </Button>
      </div>
    </form>
  );
}
