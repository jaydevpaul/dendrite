import { Composer } from "./composer";

/**
 * The prompt with nothing above it: a new conversation, or one that exists but
 * has no messages in it yet.
 *
 * Centred over the page wash rather than pinned to the bottom of an empty
 * pane, and it is the same wash the landing hero and `/app` carry -- the app
 * has one gradient language, directional and warm, and an empty conversation
 * is not the place to introduce a second one.
 *
 * What this replaced was a heading, a paragraph of explanation and a prompt at
 * the far bottom of the screen with nothing between them; the explanation
 * belongs on the landing page, which is where someone who has not written
 * anything yet actually reads.
 *
 * The same component serves both routes on purpose. Typing here and pressing
 * Enter navigates into a real conversation, and the prompt has to be in the
 * same place afterwards or the whole surface appears to jump.
 */
export function StartPane({
  error,
  onSend,
  disabled,
}: {
  /** A failed create or a failed send, shown above the prompt. */
  error?: React.ReactNode;
  onSend: (text: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="hero-wash flex min-h-0 flex-1 flex-col items-center justify-center px-4 py-8">
      <h2 className="mb-6 text-center text-[19px] leading-[1.3] font-semibold tracking-[-0.015em]">
        What are you exploring?
      </h2>

      {error ? <div className="mb-4 w-full max-w-2xl">{error}</div> : null}

      <Composer variant="centred" onSend={onSend} disabled={disabled} />
    </div>
  );
}
