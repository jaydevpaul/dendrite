import { cn } from "@/lib/utils";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/format";
import type { Message } from "./api";
import type { RunRecord } from "./use-chat";
import type { ThreadStep } from "./thread";

/**
 * One turn in the thread.
 *
 * Content is rendered as plain text with newlines preserved. Nothing parses
 * markdown yet: that is a dependency, and it is also the thing that will have
 * to cooperate with character offsets when a branch is taken from a
 * highlighted span, so it waits until that constraint is on the table.
 */

const ROLE_LABEL: Record<Message["role"], string> = {
  user: "you",
  assistant: "dendrite",
};

export function MessageTurn({
  step,
  record,
  liveText,
  streaming,
}: {
  step: ThreadStep;
  /** What the run reported when it finished, if it finished in this tab. */
  record?: RunRecord;
  /** Text arriving right now, used instead of the stored (still blank) row. */
  liveText?: string;
  streaming?: boolean;
}) {
  const { message } = step;
  const isUser = message.role === "user";
  const text = liveText ?? message.content;

  if (isUser) {
    return (
      <article className="flex justify-end">
        <div className="max-w-[85%] rounded-xl bg-surface px-4 py-[11px]">
          <p className="text-[14.5px] leading-[1.6] break-words whitespace-pre-wrap text-ink">
            {text}
          </p>
          <Siblings step={step} align="right" />
        </div>
      </article>
    );
  }

  return (
    <article>
      <p className="mb-[7px] font-mono text-[10px] tracking-[0.14em] text-dim uppercase">
        {ROLE_LABEL.assistant}
      </p>
      {text === "" ? (
        <p className="text-[14px] leading-[1.6] text-muted italic">
          This reply was started and never landed.
        </p>
      ) : (
        <div className="text-[15px] leading-[1.68] break-words whitespace-pre-wrap text-ink">
          {text}
          {streaming ? <Caret /> : null}
        </div>
      )}
      {record ? <RunMeta record={record} /> : null}
      <Siblings step={step} align="left" />
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
    <div className="mt-[10px] flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.5px] text-dim">
      <span className="text-muted">{record.strategy}</span>
      <span>{SOURCE_LABEL[record.source]}</span>
      <span>{record.model}</span>
      {tokens ? <span>{tokens}</span> : null}
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
 * Children this linear view is not showing. Earlier replies to the same
 * question, and branches taken off a highlighted span. Both are real rows in
 * the graph, so the thread says they are there rather than hiding them; making
 * them navigable is the tree view's job.
 */
function Siblings({ step, align }: { step: ThreadStep; align: "left" | "right" }) {
  const parts: string[] = [];
  if (step.otherReplies > 0) {
    parts.push(`${step.otherReplies} earlier ${step.otherReplies === 1 ? "reply" : "replies"}`);
  }
  if (step.branches > 0) {
    parts.push(`${step.branches} ${step.branches === 1 ? "branch" : "branches"}`);
  }
  if (parts.length === 0) return null;

  return (
    <p
      className={cn(
        "mt-[7px] font-mono text-[10px] tracking-[0.06em] text-dim",
        align === "right" && "text-right",
      )}
    >
      {parts.join(" · ")} not shown here
    </p>
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
 * Before the first chunk there is real work happening and nothing to show for
 * it: the strategy is being resolved, the chain walked, and the context
 * composed. Saying so beats an empty bubble.
 */
export function StreamingTurn({ text, phase }: { text: string; phase: "opening" | "streaming" }) {
  return (
    <article>
      <p className="mb-[7px] font-mono text-[10px] tracking-[0.14em] text-dim uppercase">
        {ROLE_LABEL.assistant}
      </p>
      {phase === "opening" && text === "" ? (
        <p className="font-mono text-[11px] tracking-[0.1em] text-dim uppercase">
          Composing context
        </p>
      ) : (
        <div className="text-[15px] leading-[1.68] break-words whitespace-pre-wrap text-ink">
          {text}
          <Caret />
        </div>
      )}
    </article>
  );
}
