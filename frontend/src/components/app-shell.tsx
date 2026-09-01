import { Link, Outlet, useNavigate } from "react-router-dom";
import { LogOut } from "lucide-react";
import { useLogout, useMe } from "@/features/auth/queries";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/brand";
import { ThemeToggle } from "@/components/theme-toggle";

/**
 * The chrome every authenticated screen sits inside.
 *
 * There is no navigator here yet: the sidebar tree is slice 5, once the
 * ancestor walk exists to feed it. What exists now is the header, the
 * identity, and the way out.
 */
export function AppShell() {
  const navigate = useNavigate();
  const { data: user } = useMe();
  const logout = useLogout({ onSuccess: () => navigate("/login", { replace: true }) });

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="flex items-center gap-3 border-b border-line px-5 py-3">
        <Link to="/" className="rounded-sm">
          <Logo size="sm" />
        </Link>

        <div className="ml-auto flex items-center gap-2">
          {user ? (
            <span className="hidden font-mono text-[11px] text-dim sm:inline">
              {user.email}
            </span>
          ) : null}
          <ThemeToggle />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
          >
            <LogOut />
            {logout.isPending ? "Signing out…" : "Sign out"}
          </Button>
        </div>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  );
}
