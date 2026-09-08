import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { PanelLeft, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/brand";
import { ConversationSidebar } from "@/components/conversation-sidebar";

/**
 * The chrome every authenticated screen sits inside: the conversation list on
 * the left, one conversation on the right.
 *
 * The shell owns the viewport height and hides its own overflow, so the thread
 * scrolls inside its pane and the prompt zone stays put. A page that scrolled
 * as a whole would carry the composer off the bottom of the screen.
 *
 * There is still no tree of branches here -- that navigator needs the graph
 * view and gets its own slice. This is the list of conversations, not the
 * structure inside one.
 */
export function AppShell() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const location = useLocation();

  // Opening a conversation from the drawer has to close it, or the thread
  // renders behind a panel covering it.
  useEffect(() => setDrawerOpen(false), [location.pathname]);

  useEffect(() => {
    if (!drawerOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setDrawerOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  return (
    <div className="flex h-dvh overflow-hidden">
      <aside className="hidden w-[264px] shrink-0 border-r border-line lg:block">
        <ConversationSidebar />
      </aside>

      {/* Below lg the list is a drawer rather than a column. Stacking it above
          the thread would push the prompt zone off the screen, and the thread
          is the job on a narrow window. */}
      {drawerOpen ? (
        <>
          <div
            className="fixed inset-0 z-30 bg-scrim lg:hidden"
            onClick={() => setDrawerOpen(false)}
            aria-hidden
          />
          <aside className="fixed inset-y-0 left-0 z-40 w-[278px] border-r border-line bg-ground lg:hidden">
            <ConversationSidebar onNavigate={() => setDrawerOpen(false)} />
            <Button
              variant="ghost"
              size="sm"
              className="absolute top-4 right-2 px-2"
              onClick={() => setDrawerOpen(false)}
              aria-label="Close conversations"
            >
              <X />
            </Button>
          </aside>
        </>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-line px-3 py-2 lg:hidden">
          <Button
            variant="ghost"
            size="sm"
            className="px-2"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open conversations"
          >
            <PanelLeft />
          </Button>
          <Logo size="sm" />
        </header>

        <main className="flex min-h-0 flex-1 flex-col">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
