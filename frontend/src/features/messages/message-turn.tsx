import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/format";
import { resolveAnchor, type AnchorRange } from "./anchor";
import { plainPreview } from "./preview";
import { ReplyMarkdown } from "./reply-markdown";
import { SOURCE_END_ATTRIBUTE, SOURCE_START_ATTRIBUTE } from "./source-spans";
import { ANCHOR_SOURCE_ATTRIBUTE, TURN_ATTRIBUTE } from "./selection";
import type { Edge, Message } from "./api";
import type { RunRecord } from "./use-chat";
import type { ThreadStep } from "./thread";

/**
 * One turn in the thread.
 *
 * The reader's own messages are plain text with newlines preserved - they were
 * typed, not authored in markdown, and rendering someone's asterisks as bold
 * would be putting words in their mouth. A model reply is rendered markdown,
 * because the model writes markdown whether or not anyone renders it.
 *
 * That difference is why a reply's offsets cannot be measured off the screen:
 * the rendered text and the stored text are different strings. The renderer
 * stamps each run of text with where it began in the stored message and the
 * selection layer measures within a run, so highlighting a phrase in a table
 * cell still anchors to the right characters of the source.
 *
 * The model's words are set in the serif and the reader's own in the sans.
 * That is not decoration: it separates what was written for you from what you
 * wrote, without a label or a colour doing the work.
 */

export function MessageTurn({
  step,
  record,
  liveText,
  streaming,
  messagesById,
  onOpenBranch,
}: {
  step: ThreadStep;
  /** What the run reported when it finished, if it finished in this tab. */
  record?: RunRecord;
  /** Text arriving right now, used instead of the stored (still blank) row. */
  liveText?: string;
  streaming?: boolean;
  /** Every message in the conversation, for naming the branches off this one. */
  messagesById: Map<string, Message>;
  /** Open a branch: re-root the thread at that message. */
  onOpenBranch: (messageId: string) => void;
}) {
  const { message } = step;
  const isUser = message.role === "user";
  const text = liveText ?? message.content;

  // Branching needs the stored text under the cursor, so it is offered only
  // where the two are the same string: a reply that is finished and in the
  // cache. A streaming turn renders from the stream and the row behind it is
  // still blank, so offsets taken from it would point into nothing.
  const branchable = !isUser && liveText === undefined && !streaming && message.content !== "";

  // Where each branch's span sits in this text, and which branches have no
  // span to sit in. The second list is normally empty; it holds a branch
  // whose anchor no longer resolves, and any branch off a message that is not
  // a selection surface at all. Without it those become unreachable the
  // moment the standing list under the message goes away.
  const anchors = useMemo(
    () =>
      !branchable
        ? []
        : step.branchEdges
            .map((edge) => resolveAnchor(text, edge))
            .filter((anchor): anchor is AnchorRange => anchor !== null),
    [branchable, step.branchEdges, text],
  );

  const marked = new Set(anchors.map((anchor) => anchor.edgeId));
  const unmarked = step.branchEdges.filter((edge) => !marked.has(edge.id));

  const branches =
    unmarked.length === 0 ? null : (
      <UnmarkedBranches edges={unmarked} messagesById={messagesById} onOpen={onOpenBranch} />
    );

  if (isUser) {
    return (
      <article {...{ [TURN_ATTRIBUTE]: message.id }} className="flex flex-col items-end">
        <div className="max-w-[85%] rounded-xl bg-surface px-4 py-[11px]">
          <p className="text-[14.5px] leading-[1.6] break-words whitespace-pre-wrap text-ink">
            {text}
          </p>
          <Siblings step={step} align="right" />
        </div>
        {branches}
      </article>
    );
  }

  return (
    <article {...{ [TURN_ATTRIBUTE]: message.id }}>
      {text === "" ? (
        <p className="text-[14px] leading-[1.6] text-muted italic">
          This reply was started and never landed.
        </p>
      ) : (
        <div
          // Only set where the rendered text equals the stored text. One
          // listener over the thread finds the message a selection lies in by
          // looking for this, so its absence is what makes a turn
          // unbranchable rather than a check somewhere else.
          {...(branchable ? { [ANCHOR_SOURCE_ATTRIBUTE]: message.id } : {})}
          className="reply-prose font-serif text-[16.5px] leading-[1.62] break-words text-ink"
        >
          <Reply
            text={text}
            anchors={anchors}
            branchEdges={step.branchEdges}
            messagesById={messagesById}
            onOpenBranch={onOpenBranch}
          />
          {streaming ? <Caret /> : null}
        </div>
      )}
      {record ? <RunMeta record={record} /> : null}
      <Siblings step={step} align="left" />
      {branches}
      {!streaming && record === undefined && text !== "" ? (
        <p
          className="mt-[6px] font-mono text-[10px] text-dim"
          title={formatAbsoluteTime(message.created_at)}
        >
          {formatRelativeTime(message.created_at)}
        </p>
      ) : null}
    </article>
  );
}

/**
 * The reply's text, with every span a branch grew from marked.
 *
 * A span whose stored text no longer matches its offsets is not drawn. That
 * only happens if the parent message was edited underneath it, and relocating
 * the anchor is a repair step that does not exist yet; an unmarked span is
 * honest, a mark at stale offsets highlights the wrong words. Those branches
 * are listed under the message instead, so nothing becomes unreachable.
 */
function Reply({
  text,
  anchors,
  branchEdges,
  messagesById,
  onOpenBranch,
}: {
  text: string;
  anchors: AnchorRange[];
  branchEdges: Edge[];
  messagesById: Map<string, Message>;
  onOpenBranch: (messageId: string) => void;
}) {
  const edgesById = useMemo(
    () => new Map(branchEdges.map((edge) => [edge.id, edge])),
    [branchEdges],
  );

  // The renderer cuts the text at every anchor boundary and hands each covered
  // run back here to be wrapped. It knows where the anchors fall; it knows
  // nothing about branches, which is why the mark is built out here.
  const renderMark = useCallback(
    (edgeIds: string[], children: React.ReactNode, stamp: { start: string; end: string }) => (
      <MarkedSpan
        edges={edgeIds
          .map((id) => edgesById.get(id))
          .filter((edge): edge is Edge => edge !== undefined)}
        stamp={stamp}
        messagesById={messagesById}
        onOpen={onOpenBranch}
      >
        {children}
      </MarkedSpan>
    ),
    [edgesById, messagesById, onOpenBranch],
  );

  return <ReplyMarkdown content={text} anchors={anchors} renderMark={renderMark} />;
}

/** How long the popover survives the pointer leaving, in milliseconds. */
const POPOVER_GRACE = 160;

/**
 * One marked run of text, and the branches that grew from it.
 *
 * **The branches appear on hover, not as a standing list.** Three or four of
 * them under a reply was more furniture than the reply itself, and it said
 * nothing about *which* words each one came from -- the span was quoted a
 * second time in every row. Putting them on the mark makes the connection the
 * layout instead of a repeated quotation.
 *
 * The mark is not a link. Every reply is a selection surface, and a click
 * inside one is how a reader places the caret before dragging out a phrase, so
 * a mark that navigated on click would fire exactly when someone was reaching
 * for the text around it. Hovering costs nothing and takes nothing away;
 * the rows inside the popover are the things that navigate.
 *
 * Where two anchors overlap, the run they share belongs to both, so hovering
 * it offers both. That is the whole reason the text is cut at every anchor
 * boundary rather than once per anchor.
 */
function MarkedSpan({
  children,
  edges,
  stamp,
  messagesById,
  onOpen,
}: {
  children: React.ReactNode;
  edges: Edge[];
  /** Where this run started in the stored text; see `renderMark`. */
  stamp: { start: string; end: string };
  messagesById: Map<string, Message>;
  onOpen: (messageId: string) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const closing = useRef<number | undefined>(undefined);

  const open = useCallback(() => {
    window.clearTimeout(closing.current);
    if (ref.current !== null) setRect(ref.current.getBoundingClientRect());
  }, []);

  // Not closed the instant the pointer leaves: the pointer has to cross the
  // gap between the mark and the popover to reach it, and closing on the way
  // would make the rows unclickable.
  const close = useCallback(() => {
    window.clearTimeout(closing.current);
    closing.current = window.setTimeout(() => setRect(null), POPOVER_GRACE);
  }, []);

  useEffect(() => () => window.clearTimeout(closing.current), []);

  // Placed by a viewport rectangle, so scrolling moves the text out from
  // under it. Same answer as the branch offer: drop it rather than chase it.
  useEffect(() => {
    if (rect === null) return;
    function drop() {
      window.clearTimeout(closing.current);
      setRect(null);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") drop();
    }
    // Capture, because the thread scrolls in its own pane rather than the
    // window, and a scroll event does not bubble.
    window.addEventListener("scroll", drop, true);
    window.addEventListener("resize", drop);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("scroll", drop, true);
      window.removeEventListener("resize", drop);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [rect]);

  return (
    <>
      <mark
        ref={ref}
        // Carried through from the renderer. This element replaces the one it
        // stamped, so without these a selection inside the mark has nothing to
        // measure against and the branch offer never appears.
        {...{ [SOURCE_START_ATTRIBUTE]: stamp.start, [SOURCE_END_ATTRIBUTE]: stamp.end }}
        // Reachable by keyboard, or the branches exist only for a mouse.
        // Focus opens it and blur closes it, which is the same pair of
        // states hover uses.
        tabIndex={0}
        aria-label={
          edges.length === 1
            ? "One branch grew from this span"
            : `${edges.length} branches grew from this span`
        }
        onMouseEnter={open}
        onMouseLeave={close}
        onFocus={open}
        onBlur={close}
        className={cn(
          "rounded-[3px] bg-accent-tint text-ink outline-none",
          "decoration-accent underline decoration-[1.5px] underline-offset-[3px]",
          // Where two anchors overlap the tint doubles, so a phrase several
          // branches grew from reads as the busiest part of the reply.
          edges.length > 1 && "bg-accent-tint-firm",
          "hover:bg-accent-tint-firm focus-visible:bg-accent-tint-firm",
        )}
      >
        {children}
      </mark>
      {rect !== null ? (
        <BranchPopover
          rect={rect}
          edges={edges}
          messagesById={messagesById}
          onOpen={onOpen}
          onMouseEnter={open}
          onMouseLeave={close}
        />
      ) : null}
    </>
  );
}

/**
 * The branches off one span, floating under it.
 *
 * Fixed rather than positioned inside the reply, because the thread scrolls
 * in a pane that clips its own overflow -- an absolutely positioned panel
 * near the bottom of it would be cut off rather than overlapping the composer.
 */
function BranchPopover({
  rect,
  edges,
  messagesById,
  onOpen,
  onMouseEnter,
  onMouseLeave,
}: {
  rect: DOMRect;
  edges: Edge[];
  messagesById: Map<string, Message>;
  onOpen: (messageId: string) => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}) {
  const estimated = 20 + edges.length * 30;
  const below = rect.bottom + estimated + 12 < window.innerHeight;
  const left = Math.min(rect.left, Math.max(window.innerWidth - 332, 8));

  return (
    <div
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      style={{ left, top: below ? rect.bottom + 6 : undefined, bottom: below ? undefined : window.innerHeight - rect.top + 6 }}
      className="fixed z-50 w-[320px] rounded-lg border border-line-strong bg-surface p-1 shadow-[0_8px_28px_rgb(0_0_0_/_0.32)]"
    >
      {edges.map((edge) => {
        const child = messagesById.get(edge.child_message_id);
        return (
          <button
            key={edge.id}
            type="button"
            onClick={() => onOpen(edge.child_message_id)}
            className="flex w-full items-center gap-2 rounded-md px-2 py-[7px] text-left text-[12.5px] text-muted transition-colors hover:bg-accent-tint hover:text-ink"
          >
            <GitBranch className="size-[13px] shrink-0 text-accent" />
            <span className="min-w-0 flex-1 truncate">
              {plainPreview(child?.content ?? "") || "a branch"}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** The live cursor. It marks the node text is currently landing in. */
function Caret() {
  return (
    <span
      aria-hidden
      className="ml-[2px] inline-block h-[1.05em] w-[2px] translate-y-[2px] animate-pulse bg-accent align-baseline"
    />
  );
}

/**
 * What the generation reported about itself: the arm that composed its
 * context, why that arm was chosen, the model, and the provider's own token
 * counts. This is the measurement the whole project is about, so it is on the
 * message rather than hidden behind a panel.
 *
 * It is only here for replies generated in this tab. Nothing reads generation
 * records back from the database yet, so a reload loses the numbers rather
 * than showing stale or invented ones.
 */
function RunMeta({ record }: { record: RunRecord }) {
  const tokens =
    record.inputTokens === null && record.outputTokens === null
      ? null
      : `${record.inputTokens ?? "?"} in / ${record.outputTokens ?? "?"} out`;

  return (
    <div
      className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.5px] text-dim"
      // Why this arm ran, which model, and what it cost -- all in the tooltip.
      // The arm is the only one of the four worth a line under every reply.
      title={[SOURCE_LABEL[record.source], record.model, tokens]
        .filter((part) => part !== null)
        .join(" · ")}
    >
      <span>{record.strategy}</span>
      {record.degradations.map((degradation) => (
        <span key={degradation} className="text-warn">
          {DEGRADATION_LABEL[degradation] ?? degradation}
        </span>
      ))}
    </div>
  );
}

/**
 * Why this message got the strategy it got. Four of the five values mean the
 * conversation default was used, so the distinction is between "nothing
 * overrode it", "a branch answered" and "a guard fired".
 */
const SOURCE_LABEL: Record<RunRecord["source"], string> = {
  edge: "set on this link",
  branch_default: "branch default",
  branch_boundary: "branch boundary",
  conversation_default: "conversation default",
  depth_cap: "depth guard",
};

/**
 * A degradation is the composition telling you it could not do the thing it
 * was asked to do. `warn` is reserved for exactly this kind of semantic
 * signal, never for decoration.
 */
const DEGRADATION_LABEL: Record<string, string> = {
  walk_truncated: "chain truncated",
  summary_missing: "summaries missing",
  embedding_missing: "retrieval unavailable",
};

/**
 * Earlier replies to the same question, which this path is not showing. They
 * are real rows in the graph, so the thread says they are there rather than
 * hiding them; opening one is the tree view's job.
 */
function Siblings({ step, align }: { step: ThreadStep; align: "left" | "right" }) {
  if (step.otherReplies === 0) return null;

  return (
    <p
      className={cn(
        "mt-[7px] font-mono text-[10px] tracking-[0.06em] text-dim",
        align === "right" && "text-right",
      )}
    >
      {step.otherReplies} earlier {step.otherReplies === 1 ? "reply" : "replies"} not shown
      here
    </p>
  );
}

/**
 * Branches with no span to hover.
 *
 * Normally there are none: a branch is reached by hovering the words it grew
 * from. Two things land here. A branch off a message that is not a selection
 * surface -- a question, or a reply still streaming -- and a branch whose
 * anchor no longer matches the text, which happens when the parent is edited
 * underneath it. Neither can be marked, and dropping them would make a real
 * row in the graph unreachable, so they keep a line of their own.
 */
function UnmarkedBranches({
  edges,
  messagesById,
  onOpen,
}: {
  edges: Edge[];
  messagesById: Map<string, Message>;
  onOpen: (messageId: string) => void;
}) {
  return (
    <div className="mt-3 flex flex-col items-start gap-1">
      {edges.map((edge) => {
        const child = messagesById.get(edge.child_message_id);
        return (
          <button
            key={edge.id}
            type="button"
            onClick={() => onOpen(edge.child_message_id)}
            className="flex max-w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[12.5px] text-muted transition-colors hover:bg-accent-tint hover:text-ink"
            title={`Branch from “${plainPreview(edge.anchored_text ?? "")}”`}
          >
            <GitBranch className="size-[13px] shrink-0 text-accent" />
            <span className="min-w-0 truncate">
              {plainPreview(child?.content ?? "") || "a branch"}
            </span>
            <span className="min-w-0 shrink truncate font-mono text-[10px] text-dim">
              &ldquo;{plainPreview(edge.anchored_text ?? "")}&rdquo;
            </span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * The reply arriving right now.
 *
 * It is a separate component because the row it is being written into is not
 * in the cached graph yet -- it was inserted server-side after the last fetch,
 * and it is blank until the whole reply is written in one go at the end. So
 * this renders from the stream, and the stored row takes over once the run
 * finishes and the graph is read again.
 *
 * Nothing is branchable here for the same reason: the stored row is blank, so
 * an offset taken from this text would point into nothing.
 *
 * Before the first chunk there is real work happening and nothing to show for
 * it: the strategy is being resolved, the chain walked, and the context
 * composed. Saying so beats an empty bubble.
 */
export function StreamingTurn({ text, phase }: { text: string; phase: "opening" | "streaming" }) {
  return (
    <article {...{ [TURN_ATTRIBUTE]: "streaming" }}>
      {phase === "opening" && text === "" ? (
        <p className="font-mono text-[11px] tracking-[0.1em] text-dim uppercase">
          Composing context
        </p>
      ) : (
        <div className="reply-prose font-serif text-[16.5px] leading-[1.62] break-words text-ink">
          {/* Rendered while it arrives, so the reply does not reflow the
              instant the stream ends. Nothing is branchable here: the stored
              row is still blank, so it carries no anchors to mark. */}
          <ReplyMarkdown content={text} anchors={[]} />
          <Caret />
        </div>
      )}
    </article>
  );
}

/**
 * The user's own text, before the write has come back.
 *
 * Only used for the message typed on the start surface and carried into a
 * conversation that was created for it. The alternative is to render nothing
 * until the POST returns, which means the page someone just pressed Enter on
 * arrives empty and then jumps twice. This is their own text; there is nothing
 * to wait for before showing it.
 */
export function PendingUserTurn({ text }: { text: string }) {
  return (
    <article {...{ [TURN_ATTRIBUTE]: "inbound" }} className="flex justify-end">
      <div className="max-w-[85%] rounded-xl bg-surface px-4 py-[11px]">
        <p className="text-[14.5px] leading-[1.6] break-words whitespace-pre-wrap text-ink">
          {text}
        </p>
      </div>
    </article>
  );
}
