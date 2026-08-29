# Dendrite Frontend — Design & Working Agreement

Companion to `Dendrite_Decision_Record.md` (the authoritative spec) and
`auth_design.md`. This file covers the frontend: stack, working cadence, visual
direction, and the constraints that keep it from looking generic.

Status: agreed 2026-08-30. Nothing built yet.

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

That moment is now. Vite dev serves on `:5173`, FastAPI on `:8000` — different
origins. The browser would refuse to send the session cookie, and login would
appear to succeed while every subsequent request came back 401.

**The fix is Vite's dev proxy, not CORS.** Proxy `/api` through the Vite dev
server to `http://localhost:8000`, so the browser only ever sees one origin:

```ts
// vite.config.ts
server: {
  proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
}
```

Then all frontend requests use relative paths (`/api/auth/login`) and the
cookie just works, unchanged.

**Do not** add `CORSMiddleware` with `allow_credentials=True`, and **do not**
switch the cookie to `SameSite=None`. Both weaken the CSRF posture that
`auth_design.md` deliberately chose, to solve a problem the proxy solves for
free. In production the API and the built frontend are served from one origin,
so the proxy is a dev-only concern that disappears.

*(Note: backend routes are currently mounted at `/auth/*`, not `/api/auth/*`.
Either prefix the API router or point the proxy at `/auth` — decide when
wiring the first slice.)*

---

## 4. Visual direction: the anti-generic constraints

The goal is a considered, specific interface — not the default look that
AI-generated frontends converge on. That look is recognizable, so it is
avoidable by naming its components:

**Banned outright:**

- Purple/indigo/violet accents (`#6366f1` and neighbours), and gradient
  backgrounds of any kind, especially purple→blue.
- Glassmorphism — frosted translucent panels with backdrop blur.
- Emoji used as iconography or in headings.
- Untouched shadcn/Tailwind defaults. If the theme tokens are stock, it will
  look stock.
- Big soft drop shadows on everything, and uniform `rounded-2xl` on every
  surface.
- Hero section → three feature cards → testimonial → CTA. Dendrite is a tool,
  not a landing page funnel.
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

**Typography:** avoid the default-Inter-everywhere look. **IBM Plex Sans** for
UI and **IBM Plex Mono** for token counts, model names, IDs, and strategy
labels reads as technical and precise, which suits a tool whose thesis is
measured quality-per-token. Always give the font stack a real system fallback.

---

## 5. Palette — starting proposal

The next session finalizes this with the user. It is written down as a concrete
proposal because "invent a palette" with no constraints is exactly how the
generic look happens.

**Concept: ink on paper.** A dendrite is a branching neural structure; the
project is a research instrument with published evaluation. Warm paper ground,
near-black ink, one botanical accent for growth and branching. No blue-violet
anywhere.

### Light

| Token | Hex | Use |
|---|---|---|
| `bg` | `#FBFAF7` | Page ground — warm paper, not blue-grey |
| `surface` | `#FFFFFF` | Cards, panels, inputs |
| `border` | `#E4E0D8` | Hairlines, dividers |
| `text` | `#1C1B18` | Primary text — warm near-black, never pure `#000` |
| `muted` | `#6B675E` | Secondary text, labels, metadata |
| `accent` | `#2F6B4F` | Deep moss — primary actions, active branch |
| `accent-hover` | `#26573F` | Hover/pressed |
| `danger` | `#B4442E` | Rust — destructive actions, errors |

### Dark

| Token | Hex | Use |
|---|---|---|
| `bg` | `#171613` | Warm charcoal, not slate-blue |
| `surface` | `#1F1E1A` | |
| `border` | `#34322C` | |
| `text` | `#EDEAE3` | |
| `muted` | `#9A958A` | |
| `accent` | `#6FA97F` | Lighter moss for contrast on dark |
| `danger` | `#D2705A` | |

Verify every text/background pair against a contrast checker before locking —
target 4.5:1 for body text, 3:1 for large text and UI boundaries.

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
| **1. Shell + auth** | done (2026-08-30) | Vite scaffold, Tailwind + shadcn, palette tokens, app shell, signup/login pages, protected-route wrapper on `/auth/me`, logout |
| 2. Conversation list | conversation routes | List, create, empty state |
| 3. Linear chat | message routes + generation | Message thread, composer, streaming via SSE |
| 4. Span branching | edge routes + anchors | Text selection → branch action; anchored-span rendering |
| 5. Tree navigation | ancestor walk | Sidebar tree, branch/continuation distinction |
| 6. Strategy + eval | eval framework | Strategy picker, per-branch context inspector, token counts |

Slice 1 is the whole of the next frontend session. Do not scaffold ahead.
