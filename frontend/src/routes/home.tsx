import { useMe } from "@/features/auth/queries";

/**
 * Placeholder landing surface for slice 1. The conversation list replaces this
 * in slice 2 -- deliberately not scaffolded ahead.
 */
export default function HomePage() {
  const { data: user } = useMe();

  return (
    <div className="mx-auto max-w-2xl px-6 py-14">
      <p className="mb-2 font-mono text-[11px] tracking-[0.12em] text-dim uppercase">
        Signed in
      </p>
      <h1 className="mb-3 text-[27px] font-semibold tracking-[-0.02em]">
        Nothing to branch from yet
      </h1>
      <p className="max-w-[58ch] text-muted">
        Authentication works end to end — this page is behind{" "}
        <code className="rounded bg-raised px-[5px] py-px font-mono text-[0.9em] text-ink">
          GET /auth/me
        </code>
        , and it is rendering because your session cookie resolved to{" "}
        <span className="text-ink">{user?.email}</span>. Conversations arrive in
        the next slice.
      </p>
    </div>
  );
}
