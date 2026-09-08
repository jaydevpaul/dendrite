import { Link } from "react-router-dom";
import { ArrowRight, GitBranch, Layers, Scale } from "lucide-react";
import { Logo } from "@/components/brand";
import {
  AnchoredSpan,
  AppMock,
  DecayLadder,
  TreeRow,
} from "@/components/specimen";
import { ThemeToggle } from "@/components/theme-toggle";
import { useMe } from "@/features/auth/queries";
import { buttonVariants } from "@/components/ui/button";

/**
 * The public front door.
 *
 * Left-aligned hero over a moss wash, with the product beside it rather than
 * beneath it — still the rule set in the design doc: the hero is the mechanism,
 * not a pitch. The sections below state properties the data model guarantees
 * rather than features, and there are no testimonials, logo strips or pricing.
 */

function Eyebrow({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <p
      className={
        "font-mono text-[11px] font-medium tracking-[0.13em] text-accent uppercase " +
        (className ?? "")
      }
    >
      {children}
    </p>
  );
}

function Panel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface">
      <div className="border-b border-line px-4 py-[9px] font-mono text-[10.5px] tracking-[0.11em] text-dim uppercase">
        {title}
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

export default function LandingPage() {
  const { data: user } = useMe();

  return (
    <div className="min-h-dvh">
      {/* ---------------- hero: left-aligned, product beside it ---------------- */}
      <section className="hero-wash relative overflow-hidden px-6 pt-6 pb-16">
        <header className="mx-auto mb-16 flex max-w-6xl items-center gap-3">
          <Logo size="md" />
          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            {user ? (
              <Link to="/app" className={buttonVariants({ size: "sm" })}>
                Open Dendrite
              </Link>
            ) : (
              <>
                <Link
                  to="/login"
                  className={buttonVariants({ variant: "ghost", size: "sm" })}
                >
                  Log in
                </Link>
                <Link to="/signup" className={buttonVariants({ size: "sm" })}>
                  Create account
                </Link>
              </>
            )}
          </div>
        </header>

        <div className="mx-auto grid max-w-6xl items-center gap-14 pb-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,430px)]">
          <div>
            <Eyebrow className="mb-4">Graph-aware context composition</Eyebrow>

            <h1 className="mb-6 max-w-[15ch] font-serif text-[clamp(2.15rem,4.6vw,3.4rem)] leading-[1.07] font-medium tracking-[-0.028em] text-balance">
              Branch from a sentence, not the whole conversation.
            </h1>

            <p className="mb-8 max-w-[56ch] text-[16.5px] leading-[1.6] text-muted">
              Every other branching chat tool hands the child either everything
              the parent knew or nothing at all. Dendrite composes context by
              walking the graph: the highlighted span at full fidelity, the
              parent behind it, older ancestors decaying to summaries — and
              retrieval pulls one back when it earns its tokens.
            </p>

            <div className="mb-9 flex flex-wrap items-center gap-3">
              <Link
                to={user ? "/app" : "/signup"}
                className={buttonVariants({ size: "lg", className: "gap-2" })}
              >
                {user ? "Open Dendrite" : "Create an account"}
                <ArrowRight />
              </Link>
              {user ? null : (
                <Link
                  to="/login"
                  className={buttonVariants({ variant: "secondary", size: "lg" })}
                >
                  Log in
                </Link>
              )}
            </div>

            <dl className="flex flex-wrap gap-x-8 gap-y-3 border-t border-line pt-5 font-mono text-[11.5px] text-muted tabular-nums">
              <div>
                <dt className="text-ink">Storage</dt>
                <dd>Postgres + pgvector, one system</dd>
              </div>
              <div>
                <dt className="text-ink">Metric</dt>
                <dd>answer quality per token</dd>
              </div>
              <div>
                <dt className="text-ink">Budget</dt>
                <dd>1–2s composition</dd>
              </div>
            </dl>
          </div>

          <Panel title="Assistant · select a span to branch">
            <AnchoredSpan
              before="For the drill-down step you are scoring maybe forty ancestor summaries, not four million vectors, so the index barely matters yet. The reason to care later is that "
              anchor="HNSW is approximate"
              after=" — it trades a small amount of recall for a very large speed win, and the recall you lose is not uniformly distributed."
              branches={2}
            />
            <div className="mt-6 border-t border-line pt-4">
              <p className="mb-2 font-mono text-[9.5px] tracking-[0.12em] text-dim uppercase">
                Navigator
              </p>
              <TreeRow
                kind="continuation"
                label="Root"
                text="How should drill-down score ancestors?"
              />
              <TreeRow
                kind="branch"
                label="Branch"
                text="Does HNSW recall loss matter?"
                anchor="HNSW is approximate"
                depth={1}
              />
              <TreeRow
                kind="branch"
                label="Branch · current"
                text="What about recall on the tail?"
                depth={2}
                current
              />
            </div>
          </Panel>
        </div>
      </section>

      {/* ---------------- the app itself ---------------- */}
      <section className="border-t border-line px-6 py-20">
        <div className="mx-auto max-w-6xl">
          <div className="mb-9 flex flex-wrap items-end gap-x-10 gap-y-3">
            <div>
              <Eyebrow className="mb-3">Two navigators, one selection</Eyebrow>
              <h2 className="max-w-[22ch] font-serif text-[28px] leading-[1.15] font-medium tracking-[-0.02em] text-balance">
                A tree for reading one path, a graph for seeing every branch
              </h2>
            </div>
            <p className="max-w-[44ch] text-[14.5px] leading-[1.6] text-muted">
              Switching views never loses your place — both read the same
              selected node, so the tree and the canvas are two lenses on one
              state rather than two screens.
            </p>
          </div>
          <AppMock />
        </div>
      </section>

      {/* ---------------- the thesis, shown ---------------- */}
      <section className="border-t border-line px-6 py-20">
        <div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-[minmax(0,400px)_minmax(0,1fr)]">
          <div>
            <Eyebrow className="mb-3">Hierarchical fidelity decay</Eyebrow>
            <h2 className="mb-4 font-serif text-[28px] leading-[1.15] font-medium tracking-[-0.02em] text-balance">
              What the child branch actually receives
            </h2>
            <p className="mb-4 text-[15px] leading-[1.62] text-muted">
              Context is not a transcript. Closer to the branch point means
              higher fidelity; distance decays toward summary. Beyond a depth
              threshold, ancestors are stored as summaries and embeddings, and a
              relevance step decides when a summary is worth swapping back for
              the original.
            </p>
            <p className="text-[15px] leading-[1.62] text-muted">
              You can read the gradient in the ink: full strength, then muted,
              then a dashed rule where the original was elided. Only retrieval
              reverses it — which is why restored content is the one thing
              wearing the accent.
            </p>
          </div>

          <Panel title="Composed context · 1,266 tokens">
            <DecayLadder
              showGutter
              layers={[
                {
                  label: "Anchor span",
                  tokens: "full · 88 tok",
                  fidelity: "full",
                  text: "HNSW is approximate — it trades a small amount of recall for a very large speed win, and the recall you lose is not uniformly distributed.",
                },
                {
                  label: "Parent",
                  tokens: "full · 604 tok",
                  fidelity: "full",
                  text: "For the drill-down step you are scoring maybe forty ancestor summaries, not four million vectors, so the index barely matters yet.",
                },
                {
                  label: "Depth 2",
                  tokens: "trimmed · 210 tok",
                  fidelity: "trimmed",
                  text: "Cosine distance over 1536-dimension embeddings, one table for all message vectors, isolation by query rather than by table.",
                },
                {
                  label: "Depth 3",
                  tokens: "summary · 46 tok",
                  fidelity: "summary",
                  text: "Established that pgvector and Postgres stay a single system; no separate vector store.",
                },
                {
                  label: "Depth 5",
                  tokens: "restored · 318 tok",
                  fidelity: "restored",
                  text: "Quality per token is a ratio, which is why a strategy that improves raw answer quality by adding context can still score worse than the baseline it beat.",
                },
              ]}
            />
          </Panel>
        </div>
      </section>

      {/* ---------------- three properties ---------------- */}
      <section className="border-t border-line px-6 py-20">
        <div className="mx-auto max-w-6xl">
          <Eyebrow className="mb-3">Why it is built this way</Eyebrow>
          <h2 className="mb-10 max-w-[24ch] font-serif text-[28px] leading-[1.15] font-medium tracking-[-0.02em] text-balance">
            Three properties the data model exists to guarantee
          </h2>

          <div className="grid gap-10 sm:grid-cols-3">
            {[
              {
                icon: GitBranch,
                title: "A branch remembers its span",
                body: "Anchors store character offsets and the text itself. Offsets render fast and disambiguate repeated phrases; the stored text is the repair mechanism if the parent is ever edited. Nothing is silently reattached.",
              },
              {
                icon: Layers,
                title: "Regeneration never deletes",
                body: "A regenerated answer is a new message beside the old one, not a replacement — so branches anchored into the original keep working. Storage grows; trust does not shrink.",
              },
              {
                icon: Scale,
                title: "Measured, not asserted",
                body: "Every strategy is scored against linear-context and full-inheritance baselines with an LLM judge. The number that matters is the ratio: quality per token, not quality alone.",
              },
            ].map(({ icon: Icon, title, body }) => (
              <div key={title} className="border-t-2 border-accent pt-4">
                <Icon
                  className="mb-3 size-[18px] text-accent"
                  aria-hidden="true"
                />
                <h3 className="mb-2 text-[15px] font-semibold">{title}</h3>
                <p className="text-[13.5px] leading-[1.6] text-muted">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="border-t border-line px-6 py-8">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4">
          <Logo size="sm" />
          <span className="font-mono text-[11px] text-dim">
            A research instrument, evaluated in public.
          </span>
          <Link
            to={user ? "/app" : "/signup"}
            className="ml-auto border-b border-accent-tint-firm text-[13px] text-accent hover:border-accent"
          >
            {user ? "Open Dendrite" : "Create an account"}
          </Link>
        </div>
      </footer>
    </div>
  );
}
