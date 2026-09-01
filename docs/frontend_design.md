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
  `index.css`: `.brand-panel` (the auth side panel) and `.hero-wash` (a faint
  moss glow behind the landing hero). The constraint that replaced the ban:
  **contrast is verified against every stop, not the average.** That check is
  not theoretical — it caught `dim` at 4.20:1 against the panel's lightest
  stop, which is why the panel has its own fixed `panel-*` tokens and never
  uses `dim`.
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

**Typography:** avoid the default-Inter-everywhere look. **IBM Plex Sans** for
UI, **IBM Plex Mono** for token counts, model names, IDs and strategy labels,
and — added 2026-08-30 — **IBM Plex Serif** for hero and section headlines
only. The serif is what stops the landing page reading as a dashboard; keeping
it inside the same superfamily makes it a coherent third voice rather than an
unrelated pairing. It is never used for body copy or UI. Always give the font
stack a real system fallback.

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
| `ground` | `#232323` | — | Page ground — neutral, no cast |
| `surface` | `#2A2A2A` | 1.09× | Cards, inputs |
| `raised` | `#343434` | 1.26× | Hover, prompt zone, raised surfaces |
| `line` | `#3A3A3A` | 1.54:1 | **Dividers only** — see the warning below |
| `line-strong` | `#837E74` | 3.89:1 | Control edges (inputs, secondary buttons) |
| `ink` | `#EDE6D6` | 12.64:1 | Primary text — warm paper tone |
| `muted` | `#B5AD9A` | 7.04:1 | Secondary text; **fidelity decay step 1** |
| `dim` | `#A09A88` | 5.59:1 | Metadata; **fidelity decay step 2** |
| `accent` | `#9BC47A` | 7.91:1 | Branch edges, current node, primary action |
| `accent-hover` | `#B4D998` | — | Hover / pressed |
| `accent-ink` | `#232323` | 7.91:1 | Text on a filled accent surface |
| `danger` | `#E58358` | 5.78:1 | Destructive actions, errors |
| `warn` | `#DDC172` | 8.94:1 | Semantic only — never decorative |

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

### Two things that are easy to get wrong

**`line` is deliberately below 3:1, and `line-strong` exists because of it.**
WCAG exempts purely decorative dividers, so a 1.26:1 hairline is correct for a
rule between rows. It is *not* correct for the edge of a text input, where the
border is the only thing indicating where to click. Never draw a control edge
with `line`.

**Lifting the ground spends contrast.** An earlier near-black ground
(`#191714`) gave 14.39:1 on text; moving to `#232323` cost roughly 1.7 points
across every token and pushed `dim` and `line-strong` below their floors, which
is why both were lifted from their original values. If the ground ever changes
again, re-measure every pair — do not assume.

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
| 3. Linear chat | message routes + generation | Message thread, composer, streaming via SSE |
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

**Slice 3 (linear chat) is blocked** until the message routes and generation
exist — section 8.10. Note the graph view (decision record section 8.9) ships
*after* slices 1–4 and the eval framework, not before them.
