import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------------------
   Static renderings of Dendrite's actual mechanism, used on the landing page
   and beside the auth forms.

   These are presentational only -- no data, no state. They exist because
   showing the anchored span and the decay ladder explains the product faster
   than a paragraph does, and because they are the real components' visual
   language rather than marketing illustration.
   --------------------------------------------------------------------------- */

/** The span a branch grew from: a rail marks the region, a rule marks the words. */
export function AnchoredSpan({
  before,
  anchor,
  after,
  branches,
  className,
}: {
  before: string;
  anchor: string;
  after: string;
  branches?: number;
  className?: string;
}) {
  return (
    <div className={cn("border-l-2 border-accent pl-[13px]", className)}>
      <p className="text-[13.5px] leading-[1.7] text-ink">
        {before}
        <span className="rounded-t-[2px] border-b-2 border-accent bg-accent-tint px-[2px]">
          {anchor}
        </span>
        {after}
      </p>
      {branches ? (
        <span className="mt-[10px] inline-flex items-center gap-[6px] rounded border border-accent-tint-firm bg-accent-tint px-[7px] py-[3px] font-mono text-[10.5px] tracking-[0.06em] text-accent tabular-nums">
          {branches} branches from this span
        </span>
      ) : null}
    </div>
  );
}

type Fidelity = "full" | "trimmed" | "summary" | "restored";

const fidelityText: Record<Fidelity, string> = {
  full: "text-ink",
  trimmed: "text-muted",
  summary: "text-dim italic",
  restored: "text-ink",
};

/**
 * The composed context, top to bottom, at decaying fidelity. Ink strength
 * carries the decay; the accent marks the one layer retrieval brought back.
 */
export function DecayLadder({
  layers,
  showGutter = false,
  className,
}: {
  layers: { label: string; tokens: string; fidelity: Fidelity; text: string }[];
  showGutter?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col", className)}>
      {layers.map((layer, index) => (
        <div
          key={layer.label}
          className={cn(
            "grid items-start gap-[14px] py-3",
            showGutter ? "grid-cols-[92px_1fr]" : "grid-cols-1",
            index > 0 && "border-t border-line",
            layer.fidelity === "restored" && "-mx-3 rounded bg-accent-tint px-3",
          )}
        >
          {showGutter ? (
            <div className="pt-[2px] font-mono text-[10.5px] tabular-nums text-dim">
              <b
                className={cn(
                  "block text-[11px] font-medium",
                  layer.fidelity === "restored" ? "text-accent" : "text-ink",
                )}
              >
                {layer.label}
              </b>
              <span className="mt-[3px] block">{layer.tokens}</span>
            </div>
          ) : null}

          <div className={cn("text-[13px] leading-[1.6]", fidelityText[layer.fidelity])}>
            {layer.fidelity === "summary" ? (
              <span className="mb-[8px] block w-[46px] border-t border-dashed border-line-strong" />
            ) : null}
            {layer.fidelity === "restored" ? (
              <span className="mb-[6px] flex items-center gap-[5px] font-mono text-[10px] tracking-[0.08em] text-accent uppercase not-italic">
                <span className="size-[5px] rounded-full bg-accent" />
                Retrieved · relevance 0.81
              </span>
            ) : null}
            {layer.text}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * One row of the navigator. A moss rail means branch; a neutral rail means
 * continuation.
 *
 * `tone="panel"` swaps every theme token for the fixed `panel-*` set. Without
 * it, this row reads `ink`/`muted`/`accent`, which in the LIGHT theme resolve
 * to near-black text and a dark green rail — correct on paper, invisible on the
 * fixed-dark brand panel.
 */
export function TreeRow({
  kind,
  label,
  text,
  anchor,
  depth = 0,
  current = false,
  tone = "app",
}: {
  kind: "branch" | "continuation";
  label: string;
  text: string;
  anchor?: string;
  depth?: number;
  current?: boolean;
  tone?: "app" | "panel";
}) {
  const panel = tone === "panel";

  return (
    <div
      className={cn(
        "flex gap-[10px] rounded-[5px] px-[9px] py-[7px] text-[12.5px]",
        current && (panel ? "bg-panel-accent-tint" : "bg-accent-tint"),
      )}
      style={{ marginLeft: depth * 20 }}
    >
      <span
        className={cn(
          "w-[3px] shrink-0 self-stretch rounded-sm",
          kind === "branch"
            ? panel
              ? "bg-panel-accent"
              : "bg-accent"
            : panel
              ? "bg-panel-line-strong"
              : "bg-line-strong",
        )}
      />
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "mb-[2px] block font-mono text-[9px] tracking-[0.1em] uppercase",
            kind === "branch"
              ? panel
                ? "text-panel-accent"
                : "text-accent"
              : panel
                ? "text-panel-muted"
                : "text-dim",
          )}
        >
          {label}
        </span>
        <span
          className={cn(
            "block truncate",
            kind === "branch" || current
              ? panel
                ? "text-panel-ink"
                : "text-ink"
              : panel
                ? "text-panel-muted"
                : "text-muted",
          )}
        >
          {text}
        </span>
        {anchor ? (
          <span
            className={cn(
              "mt-1 block text-[12px]",
              panel ? "text-panel-muted" : "text-dim",
            )}
          >
            from{" "}
            <q className={cn("not-italic", panel ? "text-panel-ink" : "text-ink")}>
              {anchor}
            </q>
          </span>
        ) : null}
      </span>
    </div>
  );
}

/** Faint branch geometry, used as hero background structure. Never a gradient. */
export function BranchField({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 400 520"
      fill="none"
      aria-hidden="true"
      preserveAspectRatio="xMidYMid slice"
      className={cn("text-line", className)}
    >
      <g stroke="currentColor" strokeWidth="1.5">
        <path d="M200 520V330" />
        <path d="M200 330C200 250 120 240 92 170" />
        <path d="M200 330C200 250 280 240 308 170" />
        <path d="M92 170C70 118 30 112 16 60" />
        <path d="M92 170C112 120 150 118 166 66" />
        <path d="M308 170C330 120 366 116 382 64" />
      </g>
      <g fill="currentColor">
        <circle cx="16" cy="56" r="4" />
        <circle cx="166" cy="62" r="4" />
        <circle cx="382" cy="60" r="4" />
        <circle cx="200" cy="330" r="4" />
      </g>
    </svg>
  );
}

/* ---------------------------------------------------------------------------
   Graph view — the second navigator (decision record section 8.9).

   Fused turn cards: one card holds a user message and its assistant reply,
   because in the ordinary case the edge between them carries no information.
   A continuation drops straight down its lane; a branch leaves sideways FROM A
   DOT marking the anchored span inside the parent, which is the one thing a
   tree cannot show and a graph can.

   Geometry is derived from the constants below rather than eyeballed. Cards
   carry an explicit height for exactly that reason -- an earlier version
   assumed a card height that did not match what the content rendered to, so
   every edge started inside its own node and the branch curve ended inside its
   target. Section 4 locks one parent per node, so this is a tree: depth sets
   the row, sibling order sets the lane, and no layout engine is needed.
   --------------------------------------------------------------------------- */
const NODE_W = 134;
const NODE_H = 76;
const LANE = 154; // horizontal pitch between lanes
const PITCH = 106; // vertical pitch between rows

const GRAPH_W = LANE + NODE_W; // 288
const GRAPH_H = PITCH + NODE_H; // 182

export function MiniGraph({
  className,
  tone = "app",
}: {
  className?: string;
  /** `panel` swaps theme tokens for the fixed brand-panel colours. */
  tone?: "app" | "panel";
}) {
  const panel = tone === "panel";
  const edgeStroke = panel
    ? "rgb(237 230 214 / 0.3)"
    : "var(--color-line-strong)";
  const card = panel
    ? "border-[rgb(237_230_214_/_0.16)] bg-[rgb(237_230_214_/_0.06)]"
    : "border-line bg-surface";
  const rule = panel ? "border-[rgb(237_230_214_/_0.14)]" : "border-line";
  const label = panel ? "text-panel-muted" : "text-dim";
  const body = panel ? "text-panel-ink" : "text-ink";
  const accent = panel ? "var(--color-panel-accent)" : "var(--color-accent)";
  const accentText = panel ? "text-panel-accent" : "text-accent";
  const accentBorder = panel ? "border-panel-accent" : "border-accent";

  const laneX = (lane: number) => lane * LANE;
  const rowY = (row: number) => row * PITCH;

  const nodes = [
    { lane: 0, row: 0, kind: "You", text: "How should drill-down score ancestors?", current: false },
    { lane: 0, row: 1, kind: "You", text: "And what does that cost per composition?", current: false },
    { lane: 1, row: 1, kind: "You · current", text: "Does HNSW recall loss matter?", current: true },
  ];

  // continuation: bottom-centre of row 0 straight down to top-centre of row 1
  const contX = laneX(0) + NODE_W / 2;
  // branch: leaves the parent's right edge at the anchored span, lands on the
  // left edge of the branch node, vertically centred
  const bx = laneX(0) + NODE_W;
  const by = rowY(0) + NODE_H * 0.68;
  const tx = laneX(1);
  const ty = rowY(1) + NODE_H / 2;

  return (
    <div
      className={cn("relative", className)}
      style={{ width: GRAPH_W, height: GRAPH_H }}
    >
      <svg
        viewBox={`0 0 ${GRAPH_W} ${GRAPH_H}`}
        width={GRAPH_W}
        height={GRAPH_H}
        fill="none"
        aria-hidden="true"
        className="absolute inset-0"
      >
        <path
          d={`M${contX} ${rowY(0) + NODE_H}V${rowY(1)}`}
          stroke={edgeStroke}
          strokeWidth="1.5"
        />
        <path
          d={`M${bx} ${by}C${bx + 14} ${by + 2}, ${tx - 10} ${ty - 2}, ${tx} ${ty}`}
          stroke={accent}
          strokeWidth="2"
          fill="none"
        />
        <circle cx={bx} cy={by} r="4" fill={accent} />
      </svg>

      {nodes.map((n) => (
        <div
          key={`${n.lane}-${n.row}`}
          className={cn(
            "absolute flex flex-col overflow-hidden rounded-md border",
            card,
            n.current && accentBorder,
          )}
          style={{
            left: laneX(n.lane),
            top: rowY(n.row),
            width: NODE_W,
            height: NODE_H,
          }}
        >
          <div className="flex-1 px-[9px] pt-[6px]">
            <span
              className={cn(
                "mb-[2px] block font-mono text-[8px] tracking-[0.13em] uppercase",
                n.current ? accentText : label,
              )}
            >
              {n.kind}
            </span>
            <span className={cn("line-clamp-2 text-[10.5px] leading-[1.3]", body)}>
              {n.text}
            </span>
          </div>
          <div className={cn("border-t px-[9px] py-[5px]", rule)}>
            <span className={cn("line-clamp-1 text-[10px]", label)}>
              Cosine over stored summaries…
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * The app, in a browser frame — the landing page's product shot.
 * Navigator on the left, message pane with an anchored span on the right.
 */
export function AppMock({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "overflow-hidden rounded-xl border border-line bg-surface shadow-[0_24px_70px_-30px_rgb(0_0_0_/_0.65)]",
        className,
      )}
    >
      <div className="flex items-center gap-3 border-b border-line px-4 py-[10px]">
        <span className="flex gap-[6px]">
          <span className="size-[9px] rounded-full bg-line-strong/50" />
          <span className="size-[9px] rounded-full bg-line-strong/50" />
          <span className="size-[9px] rounded-full bg-line-strong/50" />
        </span>
        <span className="font-mono text-[11px] text-dim">
          dendrite · hybrid retrieval for the drill-down step
        </span>
      </div>

      <div className="grid sm:grid-cols-[210px_1fr]">
        <div className="hidden border-r border-line bg-ground p-3 sm:block">
          <p className="mb-2 px-1 font-mono text-[9px] tracking-[0.12em] text-dim uppercase">
            Navigator
          </p>
          <TreeRow kind="continuation" label="Root" text="How should drill-down score…" />
          <TreeRow kind="continuation" label="Continuation" text="And what does that cost?" depth={1} />
          <TreeRow kind="branch" label="Branch" text="Does HNSW recall loss matter?" depth={1} />
          <TreeRow kind="branch" label="Branch · current" text="Recall on the tail?" depth={2} current />
        </div>

        <div className="p-5">
          <p className="mb-1 font-mono text-[9px] tracking-[0.12em] text-dim uppercase">
            Assistant
          </p>
          <AnchoredSpan
            before="For the drill-down step you are scoring forty ancestor summaries, not four million vectors. The reason to care later is that "
            anchor="HNSW is approximate"
            after=" — it trades a small amount of recall for a very large speed win."
            branches={2}
          />
          <div className="mt-5 border-t border-line pt-4">
            <div className="mb-3 flex items-center gap-2">
              <span className="font-mono text-[9px] tracking-[0.12em] text-dim uppercase">
                Graph
              </span>
              <span className="ml-auto inline-flex rounded-md border border-line-strong bg-ground p-[2px]">
                <span className="rounded px-[9px] py-[3px] text-[10.5px] text-muted">
                  Tree
                </span>
                <span className="rounded bg-accent-tint-firm px-[9px] py-[3px] text-[10.5px] text-accent">
                  Graph
                </span>
              </span>
            </div>
            <div className="overflow-x-auto">
              <MiniGraph />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
