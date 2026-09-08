# Dendrite Frontend — Design & Working Agreement

Companion to `Dendrite_Decision_Record.md` (the authoritative spec) and
`auth_design.md`. This file covers the frontend: stack, working cadence, visual
direction, and the constraints that keep it from looking generic.

Status: agreed 2026-08-30. **Slices 1 and 2 built and verified end to end**
(see section 8).

---

## 1. Working agreement

**Claude writes all frontend code directly with tools.** This is the opposite of
the backend rule, where the user types every line of `app/` Python by hand to
learn it. The frontend is not the learning target — it is the surface that makes
the backend demonstrable. Do not paste frontend code into chat for manual entry.

**Backend and frontend advance in parallel, feature by feature.** The frontend
tracks whatever the backend has actually shipped, rather than being built as one
block at the end. Auth landed on 2026-08-30, so the first frontend slice is the
app shell plus the auth screens — not a conversation UI against endpoints that
do not exist yet.

**One slice at a time**, matching the repo's existing "one layer at a time"
rule. A slice is: the screens for one backend capability, wired to real
endpoints, working end to end.

---

## 2. Stack

| Concern | Choice | Why |
|---|---|---|
| Build | **Vite + React + TypeScript** | User-specified. Fast HMR, no framework ceremony. |
| Styling | **Tailwind CSS v4** | Utility CSS, no runtime cost, no styled-components bundle. |
| Components | **shadcn/ui** (Radix primitives) | Source is copied into the repo, not installed as a dependency — you ship only what you use, and every component is editable. Satisfies "use components, don't build from scratch" without a heavy runtime. |
| Icons | **lucide-react** | Tree-shakeable. Never emoji as UI iconography. |
| Server state | **TanStack Query** | Caching, refetching, and request dedup for `/auth/me`, conversations, messages. Removes most hand-written loading/error state. |
| Routing | **React Router** | Standard, small. |
| Client state | **none initially** | TanStack Query covers server state. Add Zustand only when genuine client-only state appears (e.g. canvas viewport). Do not add a store speculatively. |

### Installed dependencies (slice 1) — every one justified

Runtime: `react`, `react-dom`, `react-router-dom`, `@tanstack/react-query`,
`lucide-react`, plus shadcn/ui's required trio — `class-variance-authority`
(typed component variants), `clsx` (conditional classes) and `tailwind-merge`
(resolves conflicting Tailwind utilities so `px-2 px-4` collapses to `px-4`).
The trio is what makes the copied shadcn source work; it is not optional and
it is not three separate decisions.

Build only: `vite`, `@vitejs/plugin-react`, `typescript`, `@types/react`,
`@types/react-dom`, `tailwindcss`, `@tailwindcss/vite`.

**Nine runtime packages total.** Anything added later is justified here first.

Two deliberate non-installs:

- **No `@types/node`.** The Vite alias uses a root-relative string
  (`"@": "/src"`) rather than `path.resolve`, so no Node API is touched and the
  config typechecks without Node types.
- **The shadcn CLI was not run.** Components are hand-written in shadcn's
  idiom directly into `src/components/ui/`. The CLI's whole output *is* copied
  source, so running it would add an interactive network step to produce files
  we can simply write — and it would have installed Radix packages for
  primitives (button, input, label) that need no Radix behaviour. Reach for the
  CLI when a component genuinely needs Radix: dialog, popover, select.

**Explicitly rejected:**

- **Next.js** — user chose Vite; SSR buys nothing for an authenticated SPA.
- **MUI / Chakra / Ant** — large runtimes, and their defaults are instantly
  recognizable, which fights section 4 below.
- **Framer Motion as a default** — CSS transitions handle everything in the
  auth and shell slices. Revisit only for the tree/canvas work.
- **A component library that owns your theme.** shadcn is copied source
  precisely so the palette in section 5 wins.

---

## 3. Where it lives, and how it talks to the API

```
dendrite/
├── app/          backend (FastAPI)
├── frontend/     React + Vite      <- new
└── docs/
```

### The cookie problem, and why the dev proxy is mandatory

`auth_design.md` section 2.5 flagged this in advance:

> `SameSite=Lax` works because we assume the frontend is served same-origin with
> the API. If the UI ends up on a different origin this changes materially —
> CORS with credentials, `SameSite=None; Secure`, and then explicit CSRF tokens.

That moment is partly now — with an important precision, because CORS and
SameSite are routinely conflated and they fail differently.

**SameSite is NOT the problem here.** `SameSite` is evaluated on *site*, and
**port is not part of a site**. `http://localhost:5173` and
`http://localhost:8000` are same-site (same scheme, same host) but
different-origin. `SameSite=Lax` is satisfied between them.

**CORS is the problem**, because CORS keys on scheme + host + port. With no
CORS configuration the failure is loud: a JSON POST triggers a preflight, the
backend has no handler, and the browser blocks the request before any JS sees
it — a console CORS error, not a 401.

The dangerous case is CORS *half*-configured, which is what happens when
someone hits that error and reaches for the obvious fix:

- `CORSMiddleware` added but `allow_credentials` left at its `False` default —
  the POST succeeds, the backend returns 200 with `Set-Cookie`, and the browser
  hands over the body while **discarding the cookie**. The app concludes login
  worked and 401s on every request after.
- Or CORS correct, but the client `fetch` omits `credentials: "include"` —
  identical symptom.

**The fix is Vite's dev proxy, which sidesteps CORS entirely.** Proxy `/api`
through the Vite dev server to `http://localhost:8000`, so the browser only
ever sees one origin:

```ts
// vite.config.ts
server: {
  proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
}
```

Then all frontend requests use relative paths (`/api/auth/login`) and the
cookie just works, unchanged.

**Do not** reach for `CORSMiddleware` as the fix, and **do not** switch the
cookie to `SameSite=None`. The second is pure downside — it weakens the CSRF
posture `auth_design.md` deliberately chose while fixing nothing, since
SameSite was never blocking anything here. The proxy solves the real (CORS)
problem for free, and mirrors production, where the API and the built frontend
are served from one origin — so the proxy is a dev-only concern that
disappears.

**Decided (slice 1): point the proxy at the backend's existing prefixes.**
`vite.config.ts` proxies `/auth` and `/health` to `http://localhost:8000`.
Re-prefixing the FastAPI routers to `/api/*` is the tidier long-term
convention, but it would have touched every route and every one of the 45
passing backend tests for no behavioural gain. Revisit if a third prefix
appears — at that point a single `/api` mount earns its keep.

### Production topology — deliberately undecided

Section 8.8 of the decision record settles *how* Dendrite is hosted (a
long-lived container, SSE for streaming). It does not settle whether the
frontend and API share an origin. That sub-question is open, and it is the one
that decides whether CORS is ever needed:

| Production shape | Same-site? | Requires |
|---|---|---|
| Container serves the built SPA (one origin) | yes | nothing |
| `app.example.com` + `api.example.com` | yes — subdomains share a registrable domain | CORS with explicit origins; `SameSite=Lax` still works |
| Frontend on Vercel, API on Fly.io | **no** — different registrable domains | CORS **plus** `SameSite=None; Secure` **plus** hand-rolled CSRF tokens |

The third row is the expensive one: a `SameSite=None` cookie forfeits the
browser's built-in CSRF defence, which `auth_design.md` deliberately relied on,
and the replacement has to be built by hand.

**Decision: use the dev proxy for now**, which keeps every option open and
matches the cheapest production shape. *Trigger: revisit when a deployment
target is actually chosen — before the first deploy, not before that.*

An explicit-origin CORS setup (`allow_origins=["http://localhost:5173"]`,
`allow_credentials=True`, and `credentials: "include"` on every client call) is
a perfectly valid alternative and would work today. It is not chosen because it
adds environment-specific config to keep in sync for a benefit that only
materializes if the split-host shape is picked. Note `allow_origins=["*"]` is
silently incompatible with credentials — the browser rejects that combination,
so origins must always be enumerated.

---

## 4. Visual direction: the anti-generic constraints

The goal is a considered, specific interface — not the default look that
AI-generated frontends converge on. That look is recognizable, so it is
avoidable by naming its components:

**Banned outright:**

- Purple/indigo/violet accents (`#6366f1` and neighbours), and the
  purple→blue hero gradient specifically.
- ~~Gradient backgrounds of any kind.~~ **Amended 2026-08-30 — gradients are
  permitted, constrained to the warm/moss family.** Two are defined, both in
  `index.css`: `.brand-panel` (the auth side panel) and `.hero-wash` (the
  landing hero and the app's start surface). The constraint that replaced the
  ban: **contrast is verified against every stop, not the average.** That check
  is not theoretical — it caught `dim` at 4.20:1 against the panel's lightest
  stop, which is why the panel has its own fixed `panel-*` tokens and never
  uses `dim`.

  **Amended 2026-09-08 — `.hero-wash` strengthened, and given per-theme
  pigment.** At 0.09/0.05 it measured exactly as designed and read as nothing
  at all on screen; the brand panel beside it in the login flow is what a
  gradient in this palette is supposed to look like. It is now a directional
  sweep plus two corner glows, driven by `--wash-*` custom properties so the
  two themes differ in pigment as well as strength: dark tints with the accent
  moss to a 0.199 peak, light with its own darker accent to 0.102. **The dark
  moss is not reused in light** — over warm paper it composites to a pale mint,
  which is the one thing this palette must not look like.

  Measured against the worst stop, both themes: `ink` 8.29:1 / 14.37:1,
  `muted` 4.62:1 / 4.70:1, `accent` 5.19:1 / 4.92:1. **`dim` fails on the wash**
  — 3.67:1 and 3.93:1 — so it is not used there, exactly as on the panel. That
  cost two edits: the landing hero's stats row moved its values to `muted` and
  its labels to `ink` (which also puts that hierarchy the right way round), and
  the app's start surface moved three labels off `dim`. `muted` now has only
  0.12 and 0.20 of headroom, so raising the alphas again means re-measuring
  rather than eyeballing.
- Glassmorphism — frosted translucent panels with backdrop blur.
- Emoji used as iconography or in headings.
- Untouched shadcn/Tailwind defaults. If the theme tokens are stock, it will
  look stock.
- Big soft drop shadows on everything, and uniform `rounded-2xl` on every
  surface.
- ~~Hero section → three feature cards → testimonial → CTA.~~ **Amended
  2026-08-30 — a public landing page now exists at `/`.** The ban on the
  *funnel shape* stands; the ban on having a front door does not. The rule that
  replaced it: **the hero must be the mechanism.** The landing page opens with a
  real anchored span, a real navigator and a real composed-context ladder —
  the same components the app renders — rather than illustrations or stock
  feature cards. The three-item section near the bottom states properties the
  data model guarantees (anchor repair, non-destructive regeneration, measured
  quality-per-token), not features. No testimonials, no logos-of-companies
  strip, no pricing.
- "✨ Powered by AI" badges.

**Required instead:**

- **One accent colour**, used sparingly and meaningfully — for the current
  branch and primary actions, not decoration.
- **Real typographic hierarchy.** Distinct sizes, weights, and spacing doing
  the structural work, rather than borders and shadows everywhere.
- **Restraint with borders.** Prefer spacing and background shifts to boxing
  everything in.
- **Density appropriate to a tool.** This is closer to a code editor or a
  research instrument than a marketing site. Comfortable, not airy.

### Brand mark

**A leaf whose veins branch** — `<DendriteMark />` in
`frontend/src/components/brand.tsx`, mirrored in `public/favicon.svg`.

The venation is the product: a midrib carrying straight on (continuation) with
side veins leaving it at an angle (branches). The silhouette is a soft leaf, so
it reads as botanical growth rather than as a diagram.

**Why filled and not stroked.** The first attempt was three 8px strokes plus
three circles — roughly 7% ink coverage on a 64px canvas. At 16px those strokes
land near one physical pixel and the mark dissolves into grey fuzz. Emoji read
at small sizes because they are *mass, not line*: a solid silhouette
recognisable before any detail resolves. This mark is filled for that reason,
and the veins are allowed to vanish at favicon size because the leaf shape
survives without them.

Veins are stroked in translucent black rather than a fixed colour, so they only
ever need contrast against the leaf itself, never against the page behind it —
which is what lets the same mark sit on the app ground, the gradient brand
panel, and a white surface with no per-context variant. The favicon is the only
place colour is hard-coded, because a favicon has no inherited context.

**Typography:** avoid the default-Inter-everywhere look. ~~**IBM Plex Sans**
for UI, **IBM Plex Mono** for token counts, model names, IDs and strategy
labels, and — added 2026-08-30 — **IBM Plex Serif** for hero and section
headlines only. The serif is what stops the landing page reading as a
dashboard; keeping it inside the same superfamily makes it a coherent third
voice rather than an unrelated pairing. It is never used for body copy or
UI.~~ Always give the font stack a real system fallback.

**Amended 2026-09-08 — the sans and the serif both changed, and the serif's
job changed with them.**

| Face | Where |
|---|---|
| **Hanken Grotesk** | All interface text. Replaces IBM Plex Sans. |
| **Source Serif 4** | Model replies, and hero and section headlines. Replaces IBM Plex Serif. |
| **IBM Plex Mono** | Unchanged — token counts, model names, ids, strategy labels. |

**What was asked for and why it could not be done.** The request was Claude's
own fonts. Its reply text is **Copernicus** and its interface is **Styrene
A/B**; both are commercially licensed, neither is on Google Fonts, and neither
is ours to bundle. So this is a substitution, chosen for the closest open
equivalents: Source Serif 4 has Copernicus's moderate contrast and sturdy text
weight, and Hanken Grotesk sits in Styrene's geometric-grotesque territory.
**If the real faces are ever licensed, only these two `--font-*` variables
change** — nothing reads a family name directly.

**The reversal worth noticing: the serif is now used for body copy.** The
sentence above said it never would be. It does now, and only in one place —
what the model writes. A serif for prose and a sans for the controls around it
is the oldest distinction in typesetting, and here it earns its keep twice
over: it separates what was written *for* the reader from what the reader
wrote themselves, with no label and no colour doing that work, and it makes a
reply read as a document rather than as output in a panel. The reader's own
messages stay in the sans for exactly that reason.

**Superfamily coherence was the cost.** The old trio were one family in three
voices, which is a real argument and it is being given up deliberately: two
unrelated families, paired on contrast rather than on shared origin. Replies
also went from 15px/1.68 to 16.5px/1.62, because a text serif needs more size
and less leading than a grotesque to hold the same optical weight.

Sizes went up by one step, so nothing in section 5 needs re-measuring — a
typeface change moves no colour.

---

## 5. Palette — LOCKED 2026-08-30

**Concept: ink on paper, at night.** Dark is the default theme, so it is the
one that was designed first; light is its inverse rather than an afterthought.
The light theme is warm paper with near-black ink; the dark theme is the same
two materials swapped — **paper-coloured ink on a warm-neutral dark ground** —
so the two read as one product at different times of day rather than as two
themes sharing a codebase.

One accent: a yellow-green (hue ≈ 93°) for branches, the current node, primary
actions, and retrieval-restored content. Nothing else.

### How this was chosen (so it is not relitigated)

Four candidate directions were rendered on identical components and compared
side by side: Everforest, Kanagawa, Gruvbox Material, and a palette derived
from Dendrite's own light theme. Monokai and Monokai Pro were tried first and
rejected — Monokai Pro's ground is cool plum, its palette is deliberately
multi-hue, and its signature pink competes with the accent for attention.

**Chosen: Gruvbox Material's neutral ground with Dendrite's own ink and
accent.** The ground is a true neutral (`#232323`, zero colour cast); the ink
and accent carry the identity.

### Dark (default)

| Token | Hex | Ratio vs ground | Use |
|---|---|---|---|
| `ground` | `#1A1A1A` | — | Page ground — neutral, no cast |
| `surface` | `#222222` | 1.09× | Cards, inputs |
| `raised` | `#2D2D2D` | 1.26× | Hover, prompt zone, raised surfaces |
| `line` | `#333333` | 1.38:1 | **Dividers only** — see the warning below |
| `line-strong` | `#837E74` | 4.31:1 | Control edges (inputs, secondary buttons) |
| `ink` | `#EDE6D6` | 14.00:1 | Primary text — warm paper tone |
| `muted` | `#B5AD9A` | 7.80:1 | Secondary text; **fidelity decay step 1** |
| `dim` | `#A09A88` | 6.19:1 | Metadata; **fidelity decay step 2** |
| `accent` | `#9BC47A` | 8.76:1 | Branch edges, current node, primary action |
| `accent-hover` | `#B4D998` | — | Hover / pressed |
| `accent-ink` | `#1A1A1A` | 8.76:1 | Text on a filled accent surface |
| `danger` | `#E58358` | 6.40:1 | Destructive actions, errors |
| `warn` | `#DDC172` | 9.90:1 | Semantic only — never decorative |
| `scrim` | `rgb(0 0 0 / 0.58)` | — | Behind an overlay panel — added 2026-09-08 |

### Light

| Token | Hex | Ratio vs ground | Use |
|---|---|---|---|
| `ground` | `#FBFAF7` | — | Warm paper |
| `surface` | `#FFFFFF` | 1.04× | Cards, inputs |
| `raised` | `#F2F0EA` | — | Hover, raised surfaces |
| `line` | `#E4E0D8` | 1.26:1 | **Dividers only** |
| `line-strong` | `#8D8980` | 3.34:1 | Control edges |
| `ink` | `#1C1B18` | 16.50:1 | Primary text — warm near-black |
| `muted` | `#6B675E` | 5.40:1 | Decay step 1 |
| `dim` | `#787369` | 4.52:1 | Decay step 2 |
| `accent` | `#456F2A` | 5.65:1 | Same hue family as the dark accent |
| `accent-hover` | `#395C21` | 7.38:1 | |
| `accent-ink` | `#FFFFFF` | 5.90:1 | Text on filled accent |
| `danger` | `#B4522E` | 4.81:1 | |
| `warn` | `#8A6A1F` | 4.83:1 | |
| `scrim` | `rgb(28 27 24 / 0.38)` | — | Warm near-black, from `ink` — added 2026-09-08 |

**Amended 2026-09-08 — one token added: `scrim`.** An addition to the locked
set, not a change to it: no existing value moved and no new hue entered. The
mobile conversation drawer needed something behind it, and it shipped as a raw
`black/55`, which is wrong here. A 58%-black scrim over a warm-neutral dark
ground is fine, but the same value over light's warm paper reads as a cold grey
wash and fights the ink-on-paper premise — so light gets a warmer, lighter
scrim derived from its own `ink` (`#1C1B18`) instead of pure black. No contrast
measurement applies: a scrim is decorative, and the panel above it carries its
own contrast against its own background.

### Two things that are easy to get wrong

**`line` is deliberately below 3:1, and `line-strong` exists because of it.**
WCAG exempts purely decorative dividers, so a 1.26:1 hairline is correct for a
rule between rows. It is *not* correct for the edge of a text input, where the
border is the only thing indicating where to click. Never draw a control edge
with `line`.

**The ground's depth is the palette's contrast budget.** The original
near-black (`#191714`) gave 14.39:1 on text; lifting it to `#232323` cost about
1.7 points across every token and pushed `dim` and `line-strong` below their
floors, which is why both were lifted from their original values. Deepening it
again to `#1A1A1A` on 2026-09-08 handed roughly 1.4 of those points back — see
the amendment below. Either direction, **re-measure every pair; do not
assume.** The `dim`-on-`raised` failure was found that way and would not have
been found any other way.

**Amended 2026-09-08 — the dark ground deepened to `#1A1A1A`.** Supersedes the
`#232323` row above; the lock stands, this is the written superseding entry it
requires. The reason was that the app read as mid-grey rather than as night,
next to references that sit much deeper.

**The four greys were solved, not picked.** The three relationships the palette
was designed around are preserved to three decimal places: `surface` sits
1.094× above the ground (was 1.095×), `raised` 1.264× (was 1.262×), `line`
1.378× (was 1.382×). Only the depth changed, so every surface still separates
from every other one by the amount it was designed to. **`#1A1A1A` is also
about the floor**: below roughly `#171717` no lighter grey lands on the 1.095×
`surface` relationship at all, so a deeper ground would mean redesigning the
ramp rather than moving it.

**It repaired a live failure.** `dim` on `raised` measured **4.43:1** against a
4.5:1 floor — shipped, and missed because the original measurement pass
compared each token against the *ground* rather than against every surface it
actually sits on. It is now 4.90:1. Every token now clears its floor on all
three surfaces: worst cases are `dim` 4.90:1 and `line-strong` 3.41:1, both on
`raised`.

**Two follow-ons.** `accent-ink` is the page colour punched out of a filled
accent, so it moved with the ground (`#1A1A1A`, 8.76:1 on the accent). The
brand panel's gradient landed its 70% stop exactly on the old ground; left
alone it would have read as *lighter* than the page beside it, so its two dark
stops moved to `#1A1A1A` and `#141310`. Its lightest stop is untouched, and
that is the one every `panel-*` token was measured against — `panel-ink`
9.48:1, `panel-muted` 5.28:1, `panel-accent` 5.94:1, unchanged. The favicon's
tile, which hard-codes the ground because a favicon has no inherited context,
moved too.

**The light theme is untouched.** The request was for a darker background; light
is warm paper, and darkening it is not the same change — it would be a
different concept, not a deeper one.

Ratios above were computed directly (WCAG relative luminance), not estimated.
Body text targets 4.5:1 and interactive boundaries 3:1, in **both** themes.

### Implementation

Tokens live in `frontend/src/index.css`. Dark values sit in Tailwind v4's
`@theme` block (which Tailwind emits onto `:root`), and light overrides them
under `[data-theme="light"]`. Because v4 utilities compile to
`var(--color-*)`, redefining the variables under a selector reskins the whole
app with no class churn.

Dark is applied on first load regardless of OS preference — a stated product
default beats a guess for a tool used in long night sessions — with a toggle
persisted to `localStorage` and resolved by an inline script in `index.html`
before first paint, so there is no flash.

---

## 6. The palette has a job beyond looking good

This is what makes Dendrite's UI specific rather than decorative. The interface
has to express three things from the data model, and colour is how:

1. **Fidelity decay** (thesis, section 1). Context is composed at decaying
   fidelity: span full → parent full → ancestors summarized. The UI must make
   that legible — full-fidelity content in full-strength ink, summarized
   ancestors in `muted` with a distinguishing treatment (dotted rule, reduced
   weight), retrieved-and-restored content marked with the accent. A reader
   should see the decay gradient without being told.

2. **Branch vs continuation** (section 6, locked). An `Edge` with anchor fields
   populated is a branch; null is a continuation. These are structurally
   different and must be visually different — accent for branch edges, neutral
   for continuations.

3. **The anchored span.** The highlighted range inside a parent response that a
   branch grew from. It needs a persistent, distinct treatment that survives
   reload — this is the product's single most important interaction.

A palette that cannot express these is the wrong palette, regardless of how it
looks on a button.

---

## 7. Performance

The user's requirement is "smooth, not heavy."

- Route-level code splitting via `React.lazy`.
- No animation library in the early slices; CSS transitions only.
- shadcn components are copied in individually — never bulk-add the catalogue.
- Keep the dependency count deliberately low; every addition is justified in
  this file.
- The conversation tree will eventually need virtualization
  (`@tanstack/react-virtual`) once a DAG gets large. Not before.

---

## 8. Build order, paired with the backend

| Slice | Backend prerequisite | Frontend |
|---|---|---|
| ~~**1. Shell + auth**~~ **DONE** | done (2026-08-30) | Vite scaffold, Tailwind v4 + shadcn-idiom components, palette tokens, app shell, signup/login pages, route guards on `/auth/me`, logout, theme toggle |
| ~~**2. Conversation list**~~ **DONE** | done (2026-08-31) | List, inline create, empty state, conversation detail with rename |
| ~~**3. Linear chat**~~ **DONE** | done (2026-09-07) | Persistent sidebar, message thread, composer, SSE streaming, retry on an unanswered or unfinished reply |
| 4. Span branching | edge routes + anchors | Text selection → branch action; anchored-span rendering |
| 5. Tree navigation | ancestor walk | Sidebar tree, branch/continuation distinction |
| 6. Strategy + eval | eval framework | Strategy picker, per-branch context inspector, token counts |

### Slice 1 — what shipped, and how it was verified

```
frontend/
├── index.html              pre-paint theme script (no flash)
├── vite.config.ts          proxy: /auth + /health -> :8000
└── src/
    ├── index.css           design tokens, both themes
    ├── main.tsx            QueryClient + BrowserRouter
    ├── App.tsx             routes, React.lazy code splitting
    ├── lib/                api.ts (ApiError, request), utils.ts (cn), theme.ts
    ├── features/auth/      api.ts (typed endpoints), queries.ts (hooks)
    ├── components/         app-shell, route-guards, theme-toggle, ui/
    └── routes/             landing, login, signup, home, auth-layout
```

**Routing.** `/` is the public landing page — it renders for logged-in users
too, swapping its call to action for "Open Dendrite" rather than bouncing them
away from their own front door. `/login` and `/signup` are guest-only and
redirect to `/app`. `/app` is the authenticated surface behind `RequireAuth`.

**Auth screens are two-panel.** A gradient brand panel sits left carrying both
navigators — the tree and the graph — and the form sits right, inside a bordered
card on the page ground rather than floating on it. The panel is dark in *both*
themes because it is a brand surface, not a page surface, which is why it has
fixed `panel-*` tokens.

> **Rule: anything rendered on the brand panel needs a `tone="panel"` variant.**
> A fixed-dark surface inside a themed app is a standing trap. A component that
> reads `ink` / `muted` / `accent` looks right in dark mode and breaks in light,
> where those resolve to near-black text and a dark green rail on a dark ground.
> `TreeRow`, `MiniGraph` and `DendriteMark` all take `tone`; the panel tokens
> (`panel-ink`, `panel-muted`, `panel-line`, `panel-line-strong`,
> `panel-accent`, `panel-accent-tint`) are defined once in `@theme` and
> deliberately **never** redefined under `[data-theme="light"]`. When adding a
> component to the panel, grep the panel markup for theme-flipping classes
> before shipping. It is dropped entirely below `lg` rather than stacked —
on a narrow screen it would push the form below the fold, and the form is the
job.

**The landing hero is centred** over `.hero-wash`, with the product itself in a
browser frame beneath it (`<AppMock />`). Structure follows a reference the user
supplied; the palette, typography and content are Dendrite's own.

Verified against the live backend **through the proxy on :5173**, not against
the API directly — the proxy is the thing under test. All nine steps passed:
401 without a cookie → 201 signup with `Set-Cookie: HttpOnly; SameSite=lax;
Max-Age=604800; Path=/` → 200 `/auth/me` returning the same user → 409 on
duplicate email → 401 on wrong password → 422 on a short password → 204 logout
→ 401 after logout. `npm run build` typechecks clean and emits separate chunks
for `login`, `signup` and `home`. The backend's 45 tests still pass.

### Slice 2 — what shipped, and how it was verified

```
src/
├── lib/format.ts                  relative + absolute time via Intl
├── features/conversations/
│   ├── api.ts                     typed endpoints, NonSpanStrategy mirror
│   ├── queries.ts                 key factory + four hooks
│   └── strategy-tag.tsx           the strategy name, in mono
└── routes/
    ├── conversations.tsx          /app       list + composer + empty state
    │                                             (removed 2026-09-08 — see slice 3)
    └── conversation.tsx           /app/c/:id detail + rename
```

`routes/home.tsx` is gone — it was slice 1's placeholder and said so.

**All four conversation routes are rendered, not just the list.** The slice
row above says "list, create, empty state"; the detail page was added because a
list whose rows lead nowhere is not a usable list, and `GET|PATCH
/conversations/{id}` are shipped backend capability, so rendering them is
inside section 8.10 rather than scaffolding ahead. The detail page stops
exactly where the backend stops: it shows the conversation's facts and says
plainly that the thread arrives with the message layer.

**The composer is inline, not a modal.** A dialog is the one component in this
slice that would genuinely have needed Radix (section 2), for a single optional
field and no destructive choice. `Input` gained `forwardRef` — shadcn's own
convention — so the composer can focus itself on mount and re-focus after a
failed submit, which `autoFocus` cannot do.

**An empty title is omitted from the POST body, never sent as `""`.** The
backend's `Title` is `min_length=1`, so `{"title": ""}` is a 422; omitting the
field is what asks for the `'Untitled'` server default. Verified both ways.

**No strategy picker here.** POST accepts `default_strategy`, but the picker is
slice 6, so a new conversation takes the server default and the composer says
so rather than making a silent choice. `NON_SPAN_STRATEGIES` is mirrored in
`features/conversations/api.ts` in the same order as `app/models/_shared.py`,
ready for it.

**A mutation invalidates the list, not just the detail entry.** `updated_at` is
the list's sort key, so a rename genuinely reorders the list rather than only
changing a label — confirmed live in step 10 below.

**404 copy does not guess.** The backend answers 404 for both "no such id" and
"someone else's" on purpose, so the not-found page says exactly that instead of
claiming to know which.

Verified against the live backend **through the proxy on :5173**, with
`/conversations` added to `vite.config.ts` — miss that entry and Vite returns
`index.html` where JSON was expected. Thirteen steps passed: 401 with no cookie
→ 201 signup → `[]` for a new user → 201 create with no title returning
`'Untitled'` → **422 on `{"title": ""}`** → 201 create with a title, whitespace
stripped → list ordered newest-first → 200 on GET one → 200 PATCH moving
`updated_at` → list reordered by it → 404 on an unknown id → 404 on both GET
and PATCH for another user's id, whose own list stays `[]` → owner re-reads and
the rejected write never landed. `npm run build` typechecks clean and emits
`conversations` and `conversation` as separate chunks. The backend's 69 tests
still pass.

### Slice 3 — what shipped, and how it was verified

```
src/
├── components/
│   ├── app-shell.tsx              sidebar + thread pane, drawer below lg
│   ├── conversation-sidebar.tsx   the list, moved out of its own page
│   └── ui/textarea.tsx            new primitive, same edge rule as Input
├── features/messages/
│   ├── api.ts                     typed endpoints, MessageOut/EdgeOut mirrors
│   ├── queries.ts                 graph query + folding a 201 into the cache
│   ├── stream.ts                  the SSE frame reader
│   ├── thread.ts                  graph -> one linear path, and the gap in it
│   ├── use-chat.ts                send, generate, live run, per-run records
│   ├── message-turn.tsx           one turn, its run metadata, its hidden kin
│   └── composer.tsx               the prompt zone
│   ├── start-pane.tsx             the prompt with nothing above it
│   └── composer.tsx               the prompt zone, two shapes
├── components/
│   ├── ui/menu-select.tsx         a listbox whose list is part of the page
│   └── conversation-sidebar.tsx   collapsible, persisted
├── lib/sidebar.ts                 the collapsed preference
└── routes/
    ├── new-conversation.tsx       /app       the prompt, and nothing else
    └── conversation.tsx           /app/c/:id the thread
```

**Revised 2026-09-08.** `routes/conversations.tsx` — the title form — is gone,
and the sections below carry the change. What shipped first asked for a title
on its own screen with the thread a click further on; that was a form standing
between the user and the thing they came to do, for a field that is now filled
in from the first message anyway.

**The list is a sidebar, and `/app` is the prompt.** The app should read the
way a chat app reads — a thread you are in, everything else you have open
beside it — so the list moved into the shell. `/app` is `StartPane`: a short
greeting and a centred prompt over a soft glow, the same component an empty
conversation renders, so typing there and pressing Enter does not make the
prompt jump to a different place on the next screen.

**Nothing is created until something is sent.** `/app` creating a conversation
on mount would leave an empty row behind every time that page was opened and
abandoned, and the sidebar would fill with untouched `Untitled`s. The order is
create, then navigate, then send — and **the typed text rides along in history
state** rather than being posted from `/app`, because posting it there would
mean streaming the reply into a component that is about to unmount, which
aborts it. The receiving side drops it out of history before sending, so a
reload or a back-navigation cannot post the same first message twice, and a ref
guards the development double-effect.

**A conversation is named from its first message.** Only when the name is still
exactly the server's `Untitled`, so a title typed or renamed to is never
overwritten, and only from the root message. It is **truncation, not
summarisation**: whitespace collapsed, cut at a word boundary, 48 characters.
The tools that read like this ask a model for a short title, and doing that here
would mean either a second provider call per conversation or — with no key
today — a title written by the fake, so every conversation would be called *"A
fake reply in two parts."* A failed rename is swallowed: it is cosmetic, and it
must not take the message that was just written down with it. When there is a
real key, swapping in a generated title is one function.

*Consequence, accepted:* the strategy is no longer announced before a
conversation exists. The old form said "strategy: server default" next to its
create button. The header shows the strategy from the moment there is anything
to show, so nothing is hidden — it is just not pre-announced, and that is worth
one less thing on an empty screen.

**The sidebar collapses, and stays collapsed** (added 2026-09-08). The
`PanelLeftClose` button in its top row hides the column; a `PanelLeft` button
takes its place at the top-left of the thread pane to bring it back. The
preference is in `localStorage` and is read in a `useState` initialiser rather
than an effect — read it in an effect and the sidebar renders open on every
load and then snaps shut.

**Collapsed and drawer-open are separate states**, because the list is two
different things at two widths. One shared flag would mean collapsing the
column on a desktop also disarms the drawer button on a phone. One button
reveals it either way, and both state changes are harmless in the layout that
does not own them — the drawer is `lg:hidden`, the column is `lg:block`.

**The chat page was stripped down** (2026-09-08), against Claude's as a
reference. Off it came: the bordered header band and its message-count line,
the `DENDRITE` role label over every reply, `conversation default` and the
model name from the metadata line (now in its tooltip), the composer's raised
band and top border, and the `Enter sends` hint everywhere except the empty
state — the one place the convention is worth teaching. What is left in the
header is the title and a rename pencil.

**The conversation's own facts sit under the prompt, not over the thread.**
Message count, created and updated, as one centred line of plain text where
Claude puts its disclaimer. They were behind a disclosure first, which is a
click and a panel to read two timestamps; and above the thread before that,
which put settings between the reader and the thing they came to read. **The
conversation id is not shown at all** — it is in the address bar, and a uuid
was the widest thing on the row for something nobody reads off a screen.

**A strategy switch, in the prompt box.** `PATCH /conversations/{id}` has
accepted `default_strategy` since the conversation layer, so this drives a
route that already exists — the same argument that justified slice 2 rendering
the detail page. It is **not** slice 6's picker, which chooses at creation time
and shows the composed context and token cost beside each arm so the choice can
be made on evidence. `SpanOnly` is absent because it is branch-only and the API
answers 422 for it. *Consequence:* there is still no way to choose before the
first message, because on `/app` no conversation exists yet to PATCH.

**`MenuSelect`, and why it is not a `select`.** A native `select` cannot be
themed: its dropdown is drawn by the OS, not the document. `option {
background-color }` is honoured by some browsers and ignored by Chrome on
Windows, and the row highlight is never reachable from CSS at all — the popup
arrived as a white card with a system-blue bar in the middle of a dark app.
Two cheaper fixes were tried first and both failed, and the reason they failed
is that those pixels are outside the page. `MenuSelect` is a button, a list and
the keyboard handling that makes them a listbox: arrows, Home/End, Enter,
Escape, Tab, click-outside, with focus held on the button and the active row
tracked by `aria-activedescendant`. Still no dependency. It carries **the only
shadow in the app** — a popup is the one place elevation does real work rather
than decorating — and it opens upward unconditionally, because the only place
it is used is the prompt box at the bottom of the viewport.

**Mono is for values being *reported*, not values being *chosen*.** The picker
and the facts line are in the interface sans even though the picker's values
are identifiers; the metadata under a stored reply stays mono. So the same
strategy name appears in two faces, and that is the distinction rather than an
inconsistency: a control typeset as data reads as something to look at rather
than something to operate.

**Sidebar rows are one line** (revised 2026-09-08). They shipped as two — title
over a relative timestamp — which is roughly 46px a row against about 30px for
the same list in any other chat app. A relative timestamp is not what anyone
scans a list by, so it moved into the row's tooltip alongside the absolute
time, where it costs no height. Inactive rows read `muted` and go to `ink` on
hover, so the active row is the only bright one.

**One gradient, on every entry surface, and none in the thread.**
`.hero-wash` carries the landing hero, `/app`, and an empty conversation.

A second gradient was tried for the empty conversation and reverted the same
day: a centred radial bloom, the shape other chat tools put behind their
prompt. Two lessons kept from it. The mechanical one — **a two-stop radial
bands on a dark ground, and two of them crossing shows as a mottled corner**;
if a radial is ever wanted here, it needs an eased four-stop falloff and a
single centre. The one that actually mattered — **it was a different gradient
language.** The brand panel is directional, the wash is directional, and a
centred bloom in the middle of them read as borrowed from somewhere else. Fit
beat novelty, and the fix was to delete the new thing rather than tune it.

The thread and the sidebar stay flat on purpose: in there, ink strength carries
fidelity decay, the accent marks branches and the current node, and the
anchored span has to stay the loudest thing on screen. A gradient behind that
competes with all three.

The shell now owns the viewport height and hides its own overflow, so the
thread scrolls inside its pane and the prompt zone stays put. A page that
scrolled as a whole would carry the composer off the bottom of the screen.
Below `lg` the list is a drawer rather than a column, for the same reason the
auth brand panel is dropped there: stacking it would push the actual work below
the fold.

**A linear view has to choose a path, and the rule is: continuation edges only,
newest child at each step.** The API returns the whole graph as two flat lists
because a conversation is a tree and there is no single order to serialise it
in. Both halves of the rule are load-bearing:

- *Continuation-only* keeps branches off the main path. A branch grown from a
  highlighted span is a different thread of thought, and once slice 4 can
  create one it must not silently take over this view.
- *Newest-wins* is what makes retrying work. A retry writes a **second**
  assistant child of the same question rather than replacing the first, so the
  newer attempt becomes the path and the abandoned one drops off it — counted
  on the question as "1 earlier reply not shown here", not hidden.

Every message on the path also reports how many children the view is *not*
showing, replies and branches separately. They are real rows in the graph;
making them navigable is the tree view's job, but pretending they do not exist
is not.

**A question with no reply is a legal state, and it gets a button.** Generation
can fail on its own, and a tab closed mid-stream leaves a blank assistant row
that `MessageOut.pending` reports as pending forever. The thread renders both
cases and offers the same recovery — ask for a reply to that question again.
Nothing generates on its own: a page that generated on mount would call the
model every time a thread whose generation keeps failing is reopened, and with
a real key that is real money.

**`EventSource` cannot read this stream.** The reply streams from a `POST`, and
`EventSource` only ever issues a `GET`, so `stream.ts` uses `fetch` plus the
response's `ReadableStream`: decode with `stream: true` so a multi-byte
character split across two network chunks survives, split frames on the blank
line, and `JSON.parse` each `data:` payload. Chunk text is JSON on the wire
because a frame ends at the first blank line and model output is full of
newlines — the symptom of getting that wrong is the model appearing to write
broken markdown, not a transport error.

Everything that can fail with a status code — an unknown message, a message
that is not a user message — fails before the first byte, so `postStream`
checking `response.ok` is meaningful. Once the stream is open the status cannot
change, and a mid-stream failure arrives as an `error` event instead.

**The row a reply is being written into is not in the cache, so the stream
renders it.** The blank assistant row is inserted server-side after the last
read, and it stays blank until the whole reply is written in one go at the end.
So the live text renders as its own turn, and when `done` arrives the graph is
**refetched before** the live text is dropped — clearing first would flash an
unfinished reply between the last chunk and the refetch.

The route is keyed on the conversation id, so switching conversations remounts.
Without that, a reply still streaming would follow the user into the next
conversation and render there.

**Run metadata is on the message, not behind a panel.** The arm that composed
the context, why that arm was chosen, the model, and the provider's own token
counts sit under each reply in mono — that measurement is the point of the
project. Degradations render in `warn`, which is exactly the semantic use that
token is reserved for. It is per-session by construction: nothing reads
`Generation` rows back yet, so a reload shows no numbers rather than stale or
invented ones.

**Two things deliberately not built.** There is no markdown renderer — it is a
dependency, and it is also the thing that will have to cooperate with character
offsets when a branch is taken from a highlighted span, so it waits until that
constraint is on the table. And there is still no strategy picker; the header
shows the conversation's default and each reply shows what actually ran.

**No new proxy entry was needed.** All three routes nest under
`/conversations`, which `vite.config.ts` already forwards — the reason to
prefer nesting, not just tidiness.

Verified against the live backend **through the proxy on :5173**. Fifteen steps
passed: 401 with no cookie → 201 signup → 201 create → 201 root message with
`edge: null` → the graph reads one message, no edges, `pending: false` →
generate streams `start` (naming `HierarchicalDecayWithRetrieval`,
`conversation_default`, `gpt-5.6-luna`), one `chunk` frame per chunk, then
`done` with the provider's `74 in / 6 out` and no degradations → the stored
reply is complete and its `created_at` equals its `updated_at`, so it reads as
never edited → a second turn under the reply streams four frames →
regenerating the *same* question writes a second assistant sibling, and the
path walk picks it while reporting "1 earlier reply" on the question → 422
generating on an assistant message → 404 on an unknown message id → 422 on
whitespace-only content → 409 on a second root → 404 on another user's graph →
the conversation's `updated_at` moved past `created_at`, which is the sidebar's
sort key.

The unfinished-reply state was verified separately, because the fake finishes
too fast to abandon: a blank assistant row and its edge were inserted directly
into the dev database, the API reported `pending: true`, the path walk resolved
the gap as "unfinished" and named the right question to retry, and the retry
then took over the path with the blank row counted off it. `npm run build`
typechecks clean and emits `conversation` as its own chunk.

**Flagged, not decided: there is still no frontend test runner.** Slices 1 and
2 were verified live and so was this one, but the path walk in `thread.ts` is
the first piece of frontend logic that is pure, load-bearing and has real edge
cases — a fork, an abandoned reply, an anchored child. It is the natural first
thing to unit test, and adding Vitest is the decision that would let that
happen.

Note the graph view (decision record section 8.9) ships *after* slices 1–4
and the eval framework, not before them.
