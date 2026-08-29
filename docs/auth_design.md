# Dendrite Authentication — Design

Companion to `Dendrite_Decision_Record.md`. The *decision* (roll-your-own
minimal auth) is recorded in section 8.8 of that document and is the
authoritative statement. This file is the *design* behind it: architecture,
flows, and the reasoning for each security choice.

Status: agreed 2026-08-02, not yet implemented.

---

## 1. What we're building, and what we're defending against

Auth is two distinct jobs that get conflated:

- **Authentication** — *who are you?* Proving the request comes from a
  particular `User` row.
- **Authorization** — *are you allowed to touch this?* Once we know you're
  user X, ensuring you can't read user Y's conversations.

This document covers authentication end-to-end, plus the hook that makes
authorization possible. Authorization itself lands with the conversation
routes (every query filtered by `user_id`) — not a separate system, just a
discipline applied at every query.

### Threat model

| Threat | Defense |
|---|---|
| Database is leaked, attacker reads passwords | Passwords never stored — only argon2 hashes |
| Attacker brute-forces leaked hashes offline | Argon2id is deliberately slow and memory-hard |
| Two users share a password; cracking one cracks both | Per-user random salt |
| XSS on the page steals the session token | `HttpOnly` cookie — JavaScript cannot read it |
| Another site forges a request from a logged-in user (CSRF) | `SameSite=Lax` cookie |
| Attacker forges or edits a token to impersonate a user | JWT signature verified server-side every request |
| Attacker sniffs the cookie over the network | `Secure` flag (HTTPS-only) in production |
| Attacker probes which emails have accounts | Uniform error messages + constant-time login path |

### Explicitly out of scope

Email verification, password reset, login rate limiting, refresh-token
rotation, OAuth, 2FA, RBAC.

Of these, **rate limiting is the one genuine production gap** — without it,
online password guessing is unthrottled. It is cheap to add later at the
reverse-proxy layer and is meaningless on a local Docker instance with one
user. Revisit before Dendrite is exposed to the internet.

---

## 2. Core concepts

### 2.1 Why hash, and why argon2 specifically

A hash is one-way: easy forward, infeasible to reverse. We store
`hash(password)`; at login we hash the submitted password and compare.

The non-obvious part is *which* hash. SHA-256 is the wrong tool — it is
engineered to be **fast**, so an attacker with a GPU tries billions of
candidates per second against a leaked database. Password hashes must be
deliberately **slow** and **memory-hard** (requiring significant RAM per
attempt, which defeats the massive parallelism of GPUs and ASICs).

Argon2id won the Password Hashing Competition in 2015 and is the current
default recommendation. Three tunable axes:

- **time cost** — number of passes
- **memory cost** — RAM per hash
- **parallelism** — threads

Tune so a single hash takes roughly 100–500ms on the target hardware. Slow
enough to wreck offline cracking, fast enough that login doesn't feel broken.

### 2.2 Salt

A **salt** is random bytes mixed into each password before hashing. Per-user,
generated fresh at signup, and **not secret** — stored alongside the hash. It
does two things: two users with the same password get completely different
hashes, and precomputed rainbow tables become useless (an attacker would need
a separate table per salt).

This is not managed manually. `passlib` generates the salt and embeds it in
the output string:

```
$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$RdescudvJCsgt3ub+b+dWRWJTmaaJObG
 └ algo  └ ver └── parameters ──┘ └─ salt ─┘ └─────── the hash ──────────┘
```

One `text` column holds all of it. Because the parameters travel with the
hash, cost can be raised later and old hashes still verify.

### 2.3 Sessions: stateful vs stateless

HTTP is stateless — the server forgets you between requests. After login the
browser needs something to send on every subsequent request.

**Stateful (server-side sessions).** Random opaque token, stored in a
`session` row (token → user_id, expiry). Each request looks it up.
- Revocation is trivial: delete the row, session dies instantly.
- Costs a table and a lookup per request.

**Stateless (signed token / JWT).** User id inside a token signed with a
server secret. Each request verifies the signature — no storage needed,
because a valid signature proves we issued it.
- No table, no schema change.
- **Cannot be revoked** before expiry. A stolen token works until `exp`.

**Chosen: stateless JWT.** The deciding reason is that a session table would
be an eighth table the decision record never contemplated, and revocation is
worthless at this scale.

An honest caveat, because the usual pitch for JWT is misleading: it is sold as
"no database hit per request," but **we hit the database anyway** to load the
`User` the route needs. That benefit does not apply here. What we get is *no
extra table and no schema churn*.

Expiry is kept short-ish (7 days) to bound the revocation window.

### 2.4 What a JWT actually is

Three base64url segments joined by dots: `header.payload.signature`.

```
eyJhbGciOiJIUzI1NiJ9 . eyJzdWIiOiIwMTkyLi4uIiwiZXhwIjoxNzk...} . 4pQr7v...
      header                        payload                      signature
   {"alg":"HS256"}      {"sub":"<user uuid>","exp":...,"iat":...}
```

Critical to internalize: **a JWT is signed, not encrypted.** Anyone holding
the token can base64-decode the payload and read it. The signature guarantees
only *integrity* (nobody altered it) and *authenticity* (we issued it). The
payload therefore carries a user id and timestamps — never anything secret.

Our claims:

- `sub` — the user's UUID (the "subject")
- `exp` — expiry; the library rejects expired tokens automatically
- `iat` — issued-at

Signed with HS256 using a server secret. Anyone who steals that secret can
mint tokens for any user, so it lives in `.env`, never in git.

### 2.5 Why a cookie, and what each flag stops

The token could travel in an `Authorization: Bearer` header instead. The
tradeoff is real:

- **Header** — immune to CSRF by default, but the frontend must store the
  token in JS-reachable storage, so any XSS steals it.
- **Cookie** — attached automatically by the browser, and `HttpOnly` puts it
  out of JavaScript's reach entirely, but CSRF must now be considered.

We take the cookie: XSS token theft is the harder problem, and `SameSite`
handles CSRF cleanly.

| Flag | Value | What it does |
|---|---|---|
| `HttpOnly` | `true` | JS can't read the cookie — XSS can't exfiltrate the session |
| `Secure` | `true` in prod, `false` in dev | Cookie only sent over HTTPS. Must be off for local `http://` |
| `SameSite` | `Lax` | Browser withholds the cookie on cross-site POSTs — closes the main CSRF vector while still allowing normal inbound links |
| `Max-Age` | matches token TTL | Browser drops it on schedule |
| `Path` | `/` | Sent to all our routes |

**Flagged for later:** `SameSite=Lax` works because we assume the frontend is
served same-origin with the API. If the UI ends up on a different origin this
changes materially — CORS with credentials, `SameSite=None; Secure`, and then
explicit CSRF tokens, since `SameSite` would no longer protect us. Tied to the
frontend decision; do not pre-solve.

---

## 3. Architecture

Each layer has one job and can be tested without the ones above it.

```
app/
├── api/
│   ├── deps.py              ← NEW  get_current_user() dependency
│   └── routes/
│       ├── auth.py          ← NEW  signup / login / logout / me
│       └── health.py               (exists)
├── core/
│   ├── config.py                   + secret key, TTL, cookie flags
│   ├── db.py                       (exists — get_session)
│   └── security.py          ← NEW  pure crypto: hash, verify, encode, decode
├── models/
│   └── user.py                     + email, password_hash
├── schemas/                 ← NEW package
│   └── auth.py              ← NEW  Pydantic request/response shapes
└── services/                ← NEW package
    └── auth.py              ← NEW  signup_user(), authenticate_user()
```

**Why `core/security.py` is separate from `services/auth.py`:**

- `core/security.py` holds **pure functions**. No database, no FastAPI, no
  request. `hash_password`, `verify_password`, `create_access_token`,
  `decode_access_token`. Unit-testable with no fixtures, no DB, no async.
- `services/auth.py` holds **business logic that needs the database**. Takes
  an `AsyncSession`, enforces rules (email uniqueness, credential
  verification). Knows nothing about HTTP — no status codes, no cookies.
- `api/routes/auth.py` is **thin and HTTP-only**. Parse request, call service,
  translate result into a status code, set or clear the cookie.

The payoff: when an arq worker or a CLI script later needs to create a user,
it calls the service directly. None of that logic is trapped inside an HTTP
handler.

`api/deps.py` holds `get_current_user()` — a FastAPI dependency, i.e. a
function FastAPI calls before the route and injects the result of. Writing
`user: User = Depends(get_current_user)` in a route signature makes that route
authenticated. That one line is the entire mechanism, and it is what gives
`Conversation.user_id` a real value.

---

## 4. Flows

### 4.1 Signup

```
Client                    Route              Service            Security      DB
  │  POST /auth/signup      │                   │                   │          │
  │  {email, password}      │                   │                   │          │
  ├────────────────────────>│                   │                   │          │
  │                    [Pydantic validates:     │                   │          │
  │                     EmailStr, len >= 8]     │                   │          │
  │                         ├──signup_user()───>│                   │          │
  │                         │            [lowercase + strip email]  │          │
  │                         │                   ├──SELECT by email─────────────>│
  │                         │                   │<──── exists? ────────────────┤
  │                         │                   │                   │          │
  │                         │      (if exists) ─┼─> raise EmailTaken │         │
  │                         │                   │                   │          │
  │                         │                   ├─hash_password()──>│          │
  │                         │                   │<── argon2 hash ───┤          │
  │                         │                   ├──INSERT user (uuid7 id)─────>│
  │                         │<──── User ────────┤                   │          │
  │                    [create token, set cookie]                   │          │
  │<── 201 + {id, email} ───┤                   │                   │          │
       Set-Cookie: session=...; HttpOnly; SameSite=Lax
```

**Signup auto-logs-in** (sets the cookie immediately) rather than redirecting
to a login form. Standard for apps without email verification.

### 4.2 Login

```
1.  POST /auth/login {email, password}
2.  Normalize email → SELECT * FROM "user" WHERE email = ?
3.  ┌─ user NOT found ──> verify_password(submitted, DUMMY_HASH)
    │                     discard result → 401 "Invalid email or password"
    └─ user found ─────> verify_password(submitted, user.password_hash)
                          ├─ False → 401 "Invalid email or password"
                          └─ True  → continue
4.  token = create_access_token(user.id)
5.  Set-Cookie: session=<token>; HttpOnly; SameSite=Lax; Max-Age=...
6.  200 {id, email}
```

Two details in step 3 that are easy to get wrong:

**Identical error messages.** "No such email" and "wrong password" must return
the *same* message. Distinguishing them hands an attacker a free oracle for
discovering which emails have accounts — useful for targeted phishing and
credential stuffing.

**The dummy hash.** Uniform messages are not sufficient alone. If the email
does not exist, the naive implementation returns immediately, skipping the
~200ms argon2 verify. That timing difference is measurable over the network
and leaks exactly what the uniform message was hiding. Fix: when no user is
found, verify the submitted password against a hardcoded dummy hash and
discard the result, so both paths burn comparable time. This is a **timing
side channel**; the same reasoning recurs throughout cryptographic code.

Signup still leaks account existence via "email already registered." Closing
that properly requires an email-verification flow, which is out of MVP scope.
Accepted and documented.

### 4.3 Authenticated request

```
GET /conversations
Cookie: session=eyJhbGci...

   │
   ▼
get_current_user()  ← FastAPI runs this before the route body
   │
   ├─ 1. Read "session" cookie          ── missing ──────────────> 401
   ├─ 2. Verify JWT signature           ── tampered ─────────────> 401
   ├─ 3. Check exp claim                ── expired ──────────────> 401
   ├─ 4. Parse sub → UUID               ── malformed ────────────> 401
   ├─ 5. SELECT user WHERE id = sub     ── deleted since issue ──> 401
   └─ 6. return User
   │
   ▼
route body runs, with a guaranteed-valid `user` in hand
   │
   └─ authorization happens here:
      SELECT * FROM conversation WHERE user_id = user.id   ← always scoped
```

Steps 2 and 3 make the token trustworthy without stored state. Step 5 is why
the DB round-trip happens regardless — and why the "stateless means no DB hit"
pitch does not apply here.

The last line is the authorization discipline: **every** conversation/message
query filters by `user.id`. Missing it on one endpoint is an IDOR
vulnerability where user A reads user B's conversations by guessing a UUID.
UUIDv7 makes guessing impractical, but "hard to guess" is not access control.

### 4.4 Logout

```
1.  POST /auth/logout
2.  Set-Cookie: session=; Max-Age=0     ← instructs the browser to drop it
3.  204 No Content
```

Honest limitation of the stateless choice: this clears the *browser's* copy,
but a token already captured by an attacker stays valid until `exp`. Short
TTLs bound the damage. Real revocation would need a denylist table — the exact
complexity we chose to avoid.

---

## 5. Data model change

`User` currently has `id` + `created_at`. Adding:

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `email` | `text` | `NOT NULL`, `UNIQUE` | Unique constraint creates its own index |
| `password_hash` | `text` | `NOT NULL` | Argon2 string — algorithm, params, salt, hash all inside |

Section 8.7 already established that the stub gets *extended* when auth lands,
so this does not touch anything LOCKED in section 9.

**Case sensitivity.** `Alice@x.com` and `alice@x.com` are the same mailbox,
but a plain unique index treats them as two accounts, so both could register.
Two options:

1. **Normalize on write** — lowercase and strip in the service before insert
   or lookup; plain unique index.
2. **Postgres `citext`** — case-insensitive text type; the database enforces
   it.

**Chosen: (1).** No extension to install and manage, and normalization is one
line in one place because all writes funnel through the service. `citext` is
the more bulletproof answer if writes ever arrive from outside that service.

---

## 6. Config additions

```python
secret_key: str            # HS256 signing key — .env only, NEVER committed
access_token_ttl: timedelta = timedelta(days=7)
cookie_secure: bool = False    # True in production (HTTPS)
cookie_samesite: str = "lax"
```

**This forces a `.env` for the first time** — the project has run entirely on
defaults with no `.env` file to date. A signing key cannot ship a real
default; a hardcoded dev key reaching production makes every token in the
world forgeable. Plan: read from `.env`; if absent, generate an ephemeral
random key at startup with a loud warning (which invalidates all sessions on
restart — annoying in exactly the way that prompts setting it properly).
`.env` is already in `.gitignore`.

---

## 7. Testing

Three tiers, cheapest first:

- **`core/security.py`** — pure unit tests, no DB, no async. Hash round-trip,
  wrong password fails, tampered token rejected, expired token rejected.
- **`services/auth.py`** — needs a DB session. Duplicate email raises, correct
  password authenticates, wrong password does not, email case normalized.
- **Routes** — full request/response. Signup sets a cookie with correct flags,
  bad credentials return 401 with a generic message, a protected route without
  a cookie returns 401 and with one returns the right user.

The last tier needs dev dependencies the project lacks: `httpx` is missing
(which is why `TestClient` could not be used on 2026-07-27), plus `pytest` and
`pytest-asyncio`.

---

## 8. Build order

Each step leaves the app working:

1. `pyproject.toml` — add `passlib[argon2]`, `pyjwt`, `pydantic[email]`; dev:
   `pytest`, `pytest-asyncio`, `httpx`
2. `core/config.py` — the four settings above
3. `core/security.py` — four pure functions + their unit tests
4. `models/user.py` — the two columns
5. Alembic revision — `--sql` dry run reviewed first, then applied to
   `dendrite-pg`
6. `schemas/auth.py` + `services/auth.py` + tests
7. `api/routes/auth.py` + `api/deps.py`, mounted in `main.py`
8. End-to-end verification against the live DB

---

## 9. Settled parameters

Agreed 2026-08-02:

| Question | Decision |
|---|---|
| Session TTL | **7 days** |
| Signup auto-login | **Yes** — cookie set on successful signup |
| `GET /auth/me` | **Yes** — first consumer of `get_current_user`, makes the flow testable end-to-end |
| Password policy | **Minimum length 8, nothing else.** Composition rules ("one uppercase, one symbol") produce weaker, more predictable passwords; NIST dropped that guidance years ago |
