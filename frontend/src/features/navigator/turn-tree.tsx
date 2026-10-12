import { ChevronDown, ChevronRight, MoreHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { plainPreview } from "@/features/messages/preview";
import {
  branchesOf,
  continuationsOf,
  spineSegments,
  turnCount,
  type SpineSegment,
  type TurnNode,
} from "./turns";

/**
 * The tree view: the thread as a spine, with branches as blocks hanging off it.
 *
 * The row treatment is the landing page's `TreeRow` made real - a coloured
 * rail down the left of each row, a mono kicker above the text, and a tinted
 * card for the row you are reading. That specimen was drawn before the
 * navigator existed, and matching it means the marketing surface and the app
 * are describing the same object rather than two designs that happen to share
 * a palette.
 *
 * **Indentation means "different thread of thought", and nothing else.** The
 * first version indented by depth, which sounds right and reads terribly: a
 * straight conversation marched rightward one step per turn, so a branch - the
 * one thing this panel exists to show - looked exactly like the next reply. So
 * continuations stay at the level of the turn they continue, and an indent now
 * happens for exactly two reasons: a branch, or one of several alternative
 * replies to the same question.
 *
 * **Only the rows that are something get a row.** A stretch of turns that
 * nothing hangs off is the thread carrying on, and drawing one row each meant
 * a twenty-turn conversation buried its single branch in nineteen rows that
 * said nothing. Those stretches fold into one anchor; the root, any turn a
 * branch came out of, and every fork stay where they are.
 *
 * **A branch starts collapsed**, as one row: the span it grew from, its first
 * message, and how many turns are inside. Alternative replies start open,
 * because those are the same thread attempted twice rather than a departure
 * from it.
 *
 * **A click goes there.** Selecting and opening used to be two gestures, with
 * opening on a double-click - which nothing on screen advertised, so half the
 * rows read as inert. Clicking a turn on the path you are already reading
 * changes no view at all; it scrolls the thread to that message, which is the
 * thing the reader wanted from the row they pressed.
 */
export function TurnTree({
  roots,
  selectedId,
  pathMessageIds,
  currentFrom,
  expanded,
  onToggle,
  onOpen,
}: {
  roots: TurnNode[];
  /** The node's own id, i.e. its first message. */
  selectedId: string | null;
  /** Messages on the path the thread is showing right now. */
  pathMessageIds: Set<string>;
  /** Which branch the thread is currently rooted at, for the CURRENT kicker. */
  currentFrom: string | null;
  /** Groups currently open. Seeded by `autoExpanded`, then the reader's. */
  expanded: Set<string>;
  onToggle: (groupId: string) => void;
  /** Go to this turn: its view, and the message inside it. */
  onOpen: (node: TurnNode) => void;
}) {
  const shared: Shared = {
    selectedId,
    pathMessageIds,
    currentFrom,
    expanded,
    onToggle,
    onOpen,
  };

  return (
    <div className="space-y-[3px] px-2 py-2">
      {roots.map((root) => (
        <Chain key={root.id} node={root} shared={shared} root />
      ))}
    </div>
  );
}

interface Shared {
  selectedId: string | null;
  pathMessageIds: Set<string>;
  currentFrom: string | null;
  expanded: Set<string>;
  onToggle: (groupId: string) => void;
  onOpen: (node: TurnNode) => void;
}

/**
 * One turn, then the thread below it with its uneventful stretches folded.
 *
 * The segmentation is done in `spineSegments`, so this only decides how each
 * segment draws. A turn segment draws exactly like the head of the chain -
 * its row and whatever hangs off it - and never descends the spine itself,
 * because the segment list already covers everything below.
 */
function Chain({
  node,
  shared,
  root = false,
  skipSelf = false,
}: {
  node: TurnNode;
  shared: Shared;
  /** The conversation's first turn, which is the only row labelled ROOT. */
  root?: boolean;
  /** Set when a group has already drawn this node's own row as its header. */
  skipSelf?: boolean;
}) {
  return (
    <>
      <Turn node={node} shared={shared} root={root} skipSelf={skipSelf} />

      {spineSegments(node).map((segment) =>
        segment.kind === "turn" ? (
          <Turn key={segment.id} node={segment.node} shared={shared} />
        ) : (
          <Run key={segment.id} segment={segment} shared={shared} />
        ),
      )}
    </>
  );
}

/**
 * One turn's row, plus the branches and alternative replies hanging off it.
 *
 * Branches come before the replies, so a branch sits directly under the turn
 * whose words it was taken out of rather than after the whole thread it
 * departs from.
 */
function Turn({
  node,
  shared,
  root = false,
  skipSelf = false,
}: {
  node: TurnNode;
  shared: Shared;
  root?: boolean;
  skipSelf?: boolean;
}) {
  const continuations = continuationsOf(node);

  return (
    <>
      {skipSelf ? null : <Row node={node} shared={shared} kicker={root ? "ROOT" : null} />}

      {branchesOf(node).map((branch) => (
        <Group key={branch.id} node={branch} shared={shared} />
      ))}

      {/* One continuation is the thread carrying on, and the segment list has
          it. Several are alternative answers, which fork and so indent. */}
      {continuations.length > 1
        ? continuations.map((reply, index) => (
            <Group
              key={reply.id}
              node={reply}
              shared={shared}
              kicker={`REPLY ${index + 1} OF ${continuations.length}`}
            />
          ))
        : null}
    </>
  );
}

/**
 * A folded stretch of the thread: "4 turns", and a chevron.
 *
 * Deliberately not a turn card. It is a hinge, not a message - it carries no
 * text of its own, because the whole reason it exists is that its contents
 * were not worth the rows. Open, it is just those rows, at this same level:
 * they are the thread carrying on, and indenting them would say they were a
 * departure from it.
 */
function Run({
  segment,
  shared,
}: {
  segment: Extract<SpineSegment, { kind: "run" }>;
  shared: Shared;
}) {
  const open = shared.expanded.has(segment.id);
  const count = segment.nodes.length;

  if (open) {
    return (
      <>
        <Hinge
          open
          count={count}
          onToggle={() => shared.onToggle(segment.id)}
        />
        {segment.nodes.map((node) => (
          <Row key={node.id} node={node} shared={shared} kicker={null} />
        ))}
      </>
    );
  }

  return (
    <Hinge open={false} count={count} onToggle={() => shared.onToggle(segment.id)} />
  );
}

function Hinge({
  open,
  count,
  onToggle,
}: {
  open: boolean;
  count: number;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className="group flex w-full items-center gap-[10px] rounded-[6px] px-[9px] py-[5px] text-left transition-colors hover:bg-raised"
    >
      <span className="flex w-[3px] shrink-0 justify-center self-stretch">
        <span className="w-px bg-line-strong" />
      </span>
      <span className="flex min-w-0 flex-1 items-center gap-1.5 font-mono text-[9.5px] tracking-[0.08em] text-dim uppercase">
        {open ? (
          <ChevronDown className="size-3" />
        ) : (
          <MoreHorizontal className="size-3" />
        )}
        {count} {count === 1 ? "turn" : "turns"}
      </span>
    </button>
  );
}

/** An indented, collapsible block: a branch, or one of several replies. */
function Group({
  node,
  shared,
  kicker,
}: {
  node: TurnNode;
  shared: Shared;
  kicker?: string;
}) {
  const open = shared.expanded.has(node.id);
  const inside = turnCount(node) - 1;

  return (
    <div className="mt-[3px] space-y-[3px] pl-[18px]">
      <Row
        node={node}
        shared={shared}
        kicker={kicker ?? "BRANCH"}
        disclosure={{ open, hidden: inside, onToggle: () => shared.onToggle(node.id) }}
      />

      {open ? <Chain node={node} shared={shared} skipSelf /> : null}
    </div>
  );
}

function Row({
  node,
  shared,
  kicker,
  disclosure,
}: {
  node: TurnNode;
  shared: Shared;
  /** Mono label above the text. Null on a continuation, which needs none. */
  kicker: string | null;
  disclosure?: { open: boolean; hidden: number; onToggle: () => void };
}) {
  const selected = node.id === shared.selectedId;
  const onPath = node.messages.some((message) => shared.pathMessageIds.has(message.id));
  // The view the thread is rooted at, which is a stronger claim than being on
  // the path: it is the branch you are inside.
  const current = node.branch && node.id === shared.currentFrom;

  const question = node.messages.find((message) => message.role === "user");
  const reply = node.messages.find((message) => message.role === "assistant");
  // A lone reply - one of two answers to the same question - has no question
  // of its own, so its own text is the title.
  const title = plainPreview((question ?? reply)?.content ?? "");
  const secondary = question === undefined || reply === undefined ? null : reply.content;
  const secondaryText = secondary === null ? null : plainPreview(secondary);
  const span = node.anchoredText === null ? null : plainPreview(node.anchoredText);

  return (
    <div
      className={cn(
        "flex items-stretch gap-[10px] rounded-[6px] px-[9px] py-[7px] transition-colors",
        selected ? "bg-accent-tint-firm" : onPath ? "bg-accent-tint" : "hover:bg-raised",
      )}
    >
      {/* A moss rail means branch; a neutral one means the thread carrying on.
          Same language as the landing page's specimen. */}
      <span
        className={cn(
          "w-[3px] shrink-0 rounded-sm",
          node.branch ? "bg-accent" : "bg-line-strong",
        )}
      />

      <button
        type="button"
        onClick={() => shared.onOpen(node)}
        aria-current={onPath ? "true" : undefined}
        className="min-w-0 flex-1 text-left"
      >
        {kicker === null && !current ? null : (
          <span
            className={cn(
              "mb-[2px] block font-mono text-[9px] tracking-[0.1em] uppercase",
              node.branch ? "text-accent" : "text-dim",
            )}
          >
            {kicker}
            {current ? `${kicker === null ? "" : " · "}current` : ""}
          </span>
        )}

        <span
          className={cn(
            "block truncate text-[12.5px] leading-[1.45]",
            node.branch || selected || onPath ? "text-ink" : "text-muted",
          )}
        >
          {title === "" ? <em className="text-dim">Empty message</em> : title}
        </span>

        {/* On a branch, the span it grew from is the thing worth a second
            line - it says which words this thread came out of. Otherwise the
            reply is. Closed, the count replaces both. */}
        {disclosure !== undefined && !disclosure.open && disclosure.hidden > 0 ? (
          <span className="mt-[3px] block font-mono text-[9.5px] tracking-[0.08em] text-dim uppercase">
            {disclosure.hidden} more {disclosure.hidden === 1 ? "turn" : "turns"} inside
          </span>
        ) : span !== null ? (
          <span className="mt-[3px] block truncate text-[12px] leading-[1.45] text-dim">
            from <q className="text-muted not-italic">{span}</q>
          </span>
        ) : secondaryText !== null ? (
          <span className="mt-[2px] block truncate font-serif text-[12px] leading-[1.45] text-dim">
            {secondaryText === "" ? "unfinished reply" : secondaryText}
          </span>
        ) : null}
      </button>

      {disclosure === undefined ? null : (
        <button
          type="button"
          onClick={disclosure.onToggle}
          aria-expanded={disclosure.open}
          aria-label={disclosure.open ? "Collapse this branch" : "Expand this branch"}
          className="-mr-1 grid size-6 shrink-0 self-start place-items-center rounded-sm text-dim transition-colors hover:bg-raised hover:text-ink"
        >
          {disclosure.open ? (
            <ChevronDown className="size-3.5" />
          ) : (
            <ChevronRight className="size-3.5" />
          )}
        </button>
      )}
    </div>
  );
}
