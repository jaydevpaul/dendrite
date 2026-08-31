import { Link } from "react-router-dom";
import { DendriteMark } from "@/components/brand";
import { MiniGraph, TreeRow } from "@/components/specimen";
import { ThemeToggle } from "@/components/theme-toggle";

/**
 * Split auth screen: brand panel left, boxed form right.
 *
 * Sized to fit one viewport with no page scroll: `lg:h-dvh` with
 * `overflow-hidden` on the grid. Both columns carry their own
 * `overflow-y-auto` as a safety valve — on an unusually short window a column
 * scrolls internally rather than the page breaking or the panel clipping.
 *
 * At `xl` the two navigator cards sit SIDE BY SIDE rather than stacked. The
 * panel column is wide and short, so spending horizontal space buys back the
 * vertical space that was pushing content past the fold, and leaves room for
 * the tree to show real depth instead of two token rows.
 *
 * Between `lg` and `xl` the column is only ~500px, where side-by-side would
 * squeeze the tree to nothing and stacking would overflow. The graph is the one
 * dropped there because it has a fixed intrinsic width; the tree is fluid and
 * still carries the branch-versus-continuation distinction by itself.
 *
 * The panel is dark in BOTH themes (it is a brand surface, not a page surface),
 * so it uses the fixed `panel-*` tokens and never `dim`, which fails contrast
 * against the gradient's lightest stop. Below `lg` it is dropped rather than
 * stacked: on a narrow screen it would push the form under the fold.
 */
export function AuthLayout({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <div className="grid min-h-dvh lg:h-dvh lg:grid-cols-2 lg:overflow-hidden">
      {/* ---------------- brand panel ---------------- */}
      <aside className="brand-panel relative hidden flex-col justify-between overflow-y-auto px-10 py-9 lg:flex xl:px-14 2xl:px-20">
        <Link
          to="/"
          className="inline-flex items-center gap-[10px] self-start rounded-sm"
        >
          <span className="grid size-9 shrink-0 place-items-center rounded-[9px] border border-panel-line bg-[rgb(237_230_214_/_0.07)]">
            <DendriteMark className="size-[23px]" tone="panel" />
          </span>
          <span className="text-[16.5px] font-semibold tracking-[-0.017em] text-panel-ink">
            Dendrite
          </span>
        </Link>

        <div className="w-full py-6">
          <h2 className="mb-4 max-w-[20ch] font-serif text-[clamp(1.6rem,2.3vw,2.05rem)] leading-[1.14] font-medium tracking-[-0.02em] text-panel-ink text-balance">
            Branch from a sentence, not the whole conversation.
          </h2>
          <p className="mb-7 max-w-[56ch] text-[14.5px] leading-[1.6] text-panel-muted">
            Two ways to move through a conversation graph — a navigator for
            reading one path, a canvas for seeing every branch at once. Both
            read the same selection, so switching never loses your place.
          </p>

          {/* Side by side: the tree stretches to fill, the graph takes its
              intrinsic width so no dead space is left beside it. */}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto]">
            <div className="rounded-lg border border-panel-line bg-[rgb(237_230_214_/_0.05)] p-3">
              <p className="mb-1 px-1 font-mono text-[9px] tracking-[0.13em] text-panel-muted uppercase">
                Tree
              </p>
              <TreeRow
                tone="panel"
                kind="continuation"
                label="Root"
                text="How should drill-down score ancestors?"
              />
              <TreeRow
                tone="panel"
                kind="continuation"
                label="Continuation"
                text="And what does that cost per composition?"
                depth={1}
              />
              <TreeRow
                tone="panel"
                kind="branch"
                label="Branch"
                text="Does HNSW recall loss matter?"
                depth={1}
              />
              <TreeRow
                tone="panel"
                kind="continuation"
                label="Continuation"
                text="Can we measure that directly?"
                depth={2}
              />
              <TreeRow
                tone="panel"
                kind="branch"
                label="Branch · current"
                text="What about recall on the tail?"
                depth={2}
                current
              />
            </div>

            <div className="hidden rounded-lg border border-panel-line bg-[rgb(237_230_214_/_0.05)] p-3 xl:block">
              <p className="mb-2 px-1 font-mono text-[9px] tracking-[0.13em] text-panel-muted uppercase">
                Graph
              </p>
              <MiniGraph tone="panel" />
            </div>
          </div>
        </div>

        <p className="font-mono text-[11px] text-panel-muted">
          Dendrite · a research instrument, evaluated in public
        </p>
      </aside>

      {/* ---------------- form side ---------------- */}
      <div className="flex flex-col bg-ground lg:overflow-y-auto">
        <header className="flex items-center gap-3 px-6 py-4">
          <Link
            to="/"
            className="inline-flex items-center gap-2 rounded-sm lg:hidden"
          >
            <DendriteMark className="size-6" />
            <span className="text-sm font-semibold tracking-[-0.015em]">
              Dendrite
            </span>
          </Link>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </header>

        <main className="flex flex-1 items-center justify-center px-6 pb-12">
          <div className="w-full max-w-[420px]">
            <div className="rounded-xl border border-line bg-surface p-7 shadow-[0_20px_50px_-32px_rgb(0_0_0_/_0.7)] sm:p-8">
              <h1 className="mb-[6px] text-[23px] leading-[1.2] font-semibold tracking-[-0.02em]">
                {title}
              </h1>
              <p className="mb-6 text-[13.5px] leading-[1.55] text-muted">
                {subtitle}
              </p>
              {children}
            </div>
            <p className="mt-5 text-center text-[13px] text-muted">{footer}</p>
          </div>
        </main>
      </div>
    </div>
  );
}

export function AuthLink({
  to,
  children,
}: {
  to: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      to={to}
      className="border-b border-accent-tint-firm text-accent hover:border-accent"
    >
      {children}
    </Link>
  );
}
