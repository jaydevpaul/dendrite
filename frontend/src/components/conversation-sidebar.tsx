import { Link, NavLink, useNavigate } from "react-router-dom";
import { LogOut, PanelLeftClose, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/brand";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/format";
import { useLogout, useMe } from "@/features/auth/queries";
import { useConversations } from "@/features/conversations/queries";

/**
 * The persistent conversation list.
 *
 * It moved out of its own page and into the shell so linear chat can be the
 * main surface: the familiar shape is a thread you are reading with everything
 * else you have open beside it. The tree of branches inside one conversation is
 * a different navigator and gets its own slice.
 */
export function ConversationSidebar({
  onNavigate,
  onCollapse,
}: {
  /** Closes the drawer after a navigation. Only the drawer passes this. */
  onNavigate?: () => void;
  /** Hides the column. Only the column passes this; the drawer has its X. */
  onCollapse?: () => void;
}) {
  const navigate = useNavigate();
  const { data: user } = useMe();
  const { data: conversations, isPending, isError, refetch } = useConversations();
  const logout = useLogout({ onSuccess: () => navigate("/login", { replace: true }) });

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 px-3 pt-4 pb-3">
        <Link to="/" className="ml-1 rounded-sm" onClick={onNavigate}>
          <Logo size="sm" />
        </Link>
        {onCollapse ? (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto px-2"
            onClick={onCollapse}
            aria-label="Hide conversations"
            title="Hide conversations"
          >
            <PanelLeftClose />
          </Button>
        ) : null}
      </div>

      <div className="px-3 pb-3">
        <Button
          variant="secondary"
          size="sm"
          className="w-full justify-start"
          onClick={() => {
            onNavigate?.();
            navigate("/app");
          }}
        >
          <Plus />
          New conversation
        </Button>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {isPending ? <Quiet>Loading</Quiet> : null}

        {isError ? (
          <div className="px-2 py-1">
            <p className="mb-2 text-[12px] leading-[1.5] text-muted">
              The list could not be loaded.
            </p>
            <Button variant="ghost" size="sm" onClick={() => void refetch()}>
              Try again
            </Button>
          </div>
        ) : null}

        {conversations?.length === 0 ? (
          <Quiet>No conversations yet</Quiet>
        ) : null}

        <ul>
          {conversations?.map((conversation) => (
            <li key={conversation.id}>
              <NavLink
                to={`/app/c/${conversation.id}`}
                onClick={onNavigate}
                title={`${conversation.title}\n${formatRelativeTime(
                  conversation.updated_at,
                )} · ${formatAbsoluteTime(conversation.updated_at)}`}
                className={({ isActive }) =>
                  cn(
                    "block truncate rounded-md border-l-2 px-[10px] py-[6px] text-[13px] leading-[1.4] transition-colors",
                    // The accent marks the thing you are in, which is the same
                    // job it does for a branch edge and the current node.
                    isActive
                      ? "border-accent bg-accent-tint font-medium text-ink"
                      : "border-transparent text-muted hover:bg-raised hover:text-ink",
                  )
                }
              >
                {conversation.title}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="border-t border-line px-3 py-2">
        <div className="flex items-center gap-1">
          {user ? (
            <span className="min-w-0 flex-1 truncate font-mono text-[10.5px] text-dim">
              {user.email}
            </span>
          ) : (
            <span className="flex-1" />
          )}
          <ThemeToggle />
          <Button
            variant="ghost"
            size="sm"
            className="px-2"
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut />
          </Button>
        </div>
      </div>
    </div>
  );
}

function Quiet({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-3 py-2 font-mono text-[10px] tracking-[0.12em] text-dim uppercase">
      {children}
    </p>
  );
}
