import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useMe } from "@/features/auth/queries";
import { Button } from "@/components/ui/button";

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh place-items-center px-6">{children}</div>
  );
}

/**
 * Shown while GET /auth/me is in flight. Deliberately quiet: on a warm cache
 * this is on screen for a few milliseconds, and a spinner that flashes is
 * worse than nothing.
 */
function Resolving() {
  return (
    <Centered>
      <p className="font-mono text-[11px] tracking-[0.12em] text-dim uppercase">
        Checking session
      </p>
    </Centered>
  );
}

/**
 * Distinguishes "not logged in" from "the API is unreachable". Collapsing the
 * two would send a user with a perfectly good session to the login page every
 * time the backend restarted, where logging in would also fail, with no
 * explanation.
 */
function Unreachable({ onRetry }: { onRetry: () => void }) {
  return (
    <Centered>
      <div className="max-w-sm text-center">
        <h1 className="mb-2 text-lg font-semibold">Can't reach Dendrite</h1>
        <p className="mb-5 text-sm text-muted">
          The API did not respond. If you are running locally, check that
          uvicorn is up on port 8000 and that Docker is running.
        </p>
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      </div>
    </Centered>
  );
}

/** Wraps routes that require a session. */
export function RequireAuth() {
  const location = useLocation();
  const { data: user, isPending, isError, refetch } = useMe();

  if (isPending) return <Resolving />;
  if (isError) return <Unreachable onRetry={() => void refetch()} />;
  if (!user) {
    // Remember where they were headed so login can send them back.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

/** Wraps the auth screens, so a logged-in user is not shown a login form. */
export function RequireGuest() {
  const { data: user, isPending, isError } = useMe();

  if (isPending) return <Resolving />;
  // If the API is down we still want the login form reachable, so an error
  // here falls through rather than blocking.
  if (!isError && user) return <Navigate to="/app" replace />;
  return <Outlet />;
}
