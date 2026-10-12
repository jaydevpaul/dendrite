import { cn } from "@/lib/utils";
import { plainPreview } from "@/features/messages/preview";
import { layoutTurns, type TurnLayout, type TurnNode } from "./turns";

/**
 * The graph view: the same tree, drawn.
 *
 * The card language is the landing page's `MiniGraph` made real - a bordered
 * card with a mono kicker, the message clamped to two lines, and a ruled
 * footer carrying either the reply or the span this thread came out of.
 *
 * The connectors are **not** the specimen's, and that is deliberate. It draws
 * a branch as a curve leaving the parent's side from a dot, which is lovely
 * with one branch and a mess with three: they all leave the same point and
 * fan out as long diagonals. So both kinds are elbows, and a branch is told
 * apart by an accent dashed stroke - the same distinction the tree view makes
 * with its rail.
 *
 * **No graph library.** Every node has exactly one parent, so the structure is
 * a tree and the layout is arithmetic. A force-directed engine would settle
 * differently on every load, so two screenshots of one conversation would not
 * match - actively bad for a project whose deliverable is a published
 * evaluation.
 *
 * **Links are SVG, cards are HTML.** Drawing the cards in SVG too would mean
 * truncating their text by counting characters, because SVG has no
 * `text-overflow`. Absolutely-positioned divs over an SVG that draws only the
 * connectors keeps real text handling and real hover states, and the positions
 * are the same numbers either way.
 *
 * The card carries an **explicit height** for a reason the specimen also
 * records: an earlier version assumed a height that did not match what the
 * content rendered to, so every edge started inside its own node and every
 * branch curve ended inside its target.
 *
 * **A click goes there**, the same as in the tree. It was a double-click
 * once, which nothing on the card advertised.
 */

/** Card geometry. The lane and row pitches are derived from it, never eyeballed. */
const NODE_W = 158;
const NODE_H = 88;
const LANE_PITCH = NODE_W + 30;
const ROW_PITCH = NODE_H + 34;
const PADDING = 14;

function leftOf(lane: number): number {
  return PADDING + lane * LANE_PITCH;
}

function topOf(row: number): number {
  return PADDING + row * ROW_PITCH;
}

export function TurnGraph({
  roots,
  selectedId,
  pathMessageIds,
  currentFrom,
  onOpen,
}: {
  roots: TurnNode[];
  selectedId: string | null;
  pathMessageIds: Set<string>;
  currentFrom: string | null;
  /** Go to this turn: its view, and the message inside it. */
  onOpen: (node: TurnNode) => void;
}) {
  const layout: TurnLayout = layoutTurns(roots);
  const width = PADDING * 2 + layout.lanes * LANE_PITCH - (LANE_PITCH - NODE_W);
  const height = PADDING * 2 + (layout.rows + 1) * ROW_PITCH - (ROW_PITCH - NODE_H);

  return (
    <div className="relative" style={{ width, height }}>
      <svg
        width={width}
        height={height}
        fill="none"
        className="absolute inset-0"
        // Decoration: the nesting in the tree view is the accessible
        // expression of the same structure.
        aria-hidden
      >
        {layout.links.map((link) => {
          const x1 = leftOf(link.from.lane) + NODE_W / 2;
          const y1 = topOf(link.from.row) + NODE_H;
          const x2 = leftOf(link.to.lane) + NODE_W / 2;
          const y2 = topOf(link.to.row);
          const mid = y1 + (y2 - y1) / 2;

          // An elbow, not a curve, and the same shape for both kinds: with
          // three branches off one turn, curves leaving a single point fan
          // out as long diagonals and the picture reads as misaligned. What
          // tells a branch apart is the stroke - accent and dashed - which is
          // the same distinction the tree view's rail makes.
          return (
            <path
              key={`${link.from.node.id}-${link.to.node.id}`}
              d={
                x1 === x2
                  ? `M${x1} ${y1}V${y2}`
                  : `M${x1} ${y1}V${mid}H${x2}V${y2}`
              }
              stroke={link.branch ? "var(--color-accent)" : "var(--color-line-strong)"}
              strokeWidth={link.branch ? 1.75 : 1.25}
              strokeDasharray={link.branch ? "3 3" : undefined}
            />
          );
        })}
      </svg>

      {layout.placed.map((entry) => (
        <TurnCard
          key={entry.node.id}
          node={entry.node}
          left={leftOf(entry.lane)}
          top={topOf(entry.row)}
          selected={entry.node.id === selectedId}
          onPath={entry.node.messages.some((message) => pathMessageIds.has(message.id))}
          current={entry.node.branch && entry.node.id === currentFrom}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}

function TurnCard({
  node,
  left,
  top,
  selected,
  onPath,
  current,
  onOpen,
}: {
  node: TurnNode;
  left: number;
  top: number;
  selected: boolean;
  onPath: boolean;
  current: boolean;
  onOpen: (node: TurnNode) => void;
}) {
  const question = node.messages.find((message) => message.role === "user");
  const reply = node.messages.find((message) => message.role === "assistant");
  const title = plainPreview((question ?? reply)?.content ?? "");
  const span = node.anchoredText === null ? null : plainPreview(node.anchoredText);

  // What the card is: the reader's question, or one of several answers to it.
  const kicker = question !== undefined ? "you" : "reply";
  const footer =
    span !== null
      ? `from “${span}”`
      : reply === undefined
        ? "no reply yet"
        : reply.content === ""
          ? "unfinished reply"
          : plainPreview(reply.content);

  return (
    <button
      type="button"
      onClick={() => onOpen(node)}
      title={span === null ? title : `“${span}” → ${title}`}
      aria-current={onPath ? "true" : undefined}
      style={{ left, top, width: NODE_W, height: NODE_H }}
      className={cn(
        "absolute flex flex-col overflow-hidden rounded-md border text-left transition-colors",
        selected
          ? "border-accent bg-accent-tint-firm"
          : current || onPath
            ? "border-accent bg-accent-tint"
            : "border-line bg-surface hover:bg-raised",
      )}
    >
      <span className="min-h-0 flex-1 px-[9px] pt-[6px]">
        <span
          className={cn(
            "mb-[2px] block font-mono text-[8.5px] tracking-[0.13em] uppercase",
            current || node.branch ? "text-accent" : "text-dim",
          )}
        >
          {kicker}
          {current ? " · current" : ""}
        </span>
        <span className="line-clamp-2 text-[11.5px] leading-[1.3] text-ink">
          {title === "" ? "Empty message" : title}
        </span>
      </span>

      <span className="border-t border-line px-[9px] py-[5px]">
        <span
          className={cn(
            "line-clamp-1 text-[10px] leading-[1.4]",
            span === null ? "text-dim" : "font-serif text-muted italic",
          )}
        >
          {footer}
        </span>
      </span>
    </button>
  );
}
