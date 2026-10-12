import { useEffect, useMemo, useState } from "react";
import { GitBranch, Network, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { cn } from "@/lib/utils";
import type { ConversationGraph } from "@/features/messages/api";
import { plainPreview } from "@/features/messages/preview";
import { useDeleteBranch } from "@/features/messages/queries";
import {
  autoExpanded,
  buildTurnTree,
  containsNode,
  nodeForMessage,
  parentOf,
  subtreeSize,
  type TurnNode,
} from "./turns";
import { TurnTree } from "./turn-tree";
import { TurnGraph } from "./turn-graph";

/**
 * The branch navigator: the tree and the graph over one selection.
 *
 * It lives on the right because the left sidebar holds the conversation list -
 * that is the list of what else is open, and this is the structure inside the
 * one you are reading. Two different questions, so two different panels.
 *
 * **Switching views preserves the selection and refetches nothing.** Both
 * views are drawn from the graph the page already has, so the switch is a
 * render and the selected node stays selected across it. That is the whole
 * reason the selection lives up here rather than inside either view.
 *
 * **A click goes there, and there is no second gesture.** Selecting and
 * opening were split once, with opening on a double-click - which nothing on
 * screen advertised, so clicking a turn already on the path you were reading
 * did nothing at all and half the panel read as inert. Now a click picks the
 * view *and* scrolls the thread to that message, which for a turn on the
 * current path is the whole of what it does. The footer stayed, because it is
 * where a branch is deleted from and where the span it grew out of is shown
 * in full.
 */
export function NavigatorPanel({
  conversationId,
  graph,
  pathMessageIds,
  currentFrom,
  onOpenView,
  onClose,
}: {
  conversationId: string;
  graph: ConversationGraph | undefined;
  /** Messages on the path the thread is showing, so the panel can mark it. */
  pathMessageIds: Set<string>;
  /** What `?from=` currently holds, so "already here" can be said honestly. */
  currentFrom: string | null;
  /** Re-root the thread, and land on one message inside it. */
  onOpenView: (fromMessageId: string | null, focusMessageId?: string) => void;
  onClose: () => void;
}) {
  const [view, setView] = useState<"tree" | "graph">("tree");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<TurnNode | null>(null);
  // What the reader has opened and closed by hand, kept apart from the seed
  // so both can be honoured at once. Merging the seed into one set instead -
  // which is how this was first written - meant every graph refetch put the
  // seed back, so anything collapsed sprang open again on the next message
  // sent.
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const [closed, setClosed] = useState<Set<string>>(new Set());

  const roots = useMemo(
    () => (graph === undefined ? [] : buildTurnTree(graph)),
    [graph],
  );

  // Nothing selected yet means "the node you are reading", which is a more
  // useful starting point than an empty footer - and it keeps the selection
  // honest after the reader opens a branch from somewhere else.
  const fallback = useMemo(() => {
    if (roots.length === 0) return null;
    if (currentFrom !== null) return nodeForMessage(roots, currentFrom);
    return roots[0];
  }, [roots, currentFrom]);

  const selected =
    (selectedId === null ? null : nodeForMessage(roots, selectedId)) ?? fallback;

  const expanded = useMemo(() => {
    const next = new Set([...autoExpanded(roots, currentFrom), ...opened]);
    for (const id of closed) next.delete(id);
    return next;
  }, [roots, currentFrom, opened, closed]);

  // Moving to a different view re-seeds, because a navigator that hides where
  // you are is answering the wrong question. Staying put does not: a collapse
  // has to survive the graph being read again, which happens on every message
  // sent.
  useEffect(() => {
    setClosed(new Set());
  }, [currentFrom]);

  function toggle(groupId: string) {
    const remove = (set: Set<string>) => {
      const next = new Set(set);
      next.delete(groupId);
      return next;
    };
    const add = (set: Set<string>) => new Set(set).add(groupId);

    if (expanded.has(groupId)) {
      setOpened(remove);
      setClosed(add);
    } else {
      setOpened(add);
      setClosed(remove);
    }
  }

  function open(node: TurnNode) {
    setSelectedId(node.id);
    // The node's own id is its first message, which is the question in a
    // fused turn - land on the question and its reply is right below it.
    onOpenView(node.viewFrom, node.id);
  }

  const remove = useDeleteBranch(conversationId, {
    onSuccess: () => {
      const deleted = confirming;
      setConfirming(null);
      if (deleted === null) return;
      setSelectedId(null);
      // Reading a branch that has just been deleted would leave the thread
      // walking rows that are gone. Step out to whatever contained it, which
      // is the main thread unless the branch was itself inside one.
      if (containsNode(deleted, currentFrom)) {
        onOpenView(parentOf(roots, deleted.id)?.viewFrom ?? null);
      }
    },
  });

  return (
    <div className="flex h-full min-h-0 flex-col bg-ground">
      <div className="flex items-center gap-1 border-b border-line px-2 py-2">
        <div className="flex rounded-md border border-line p-[2px]">
          <ViewTab active={view === "tree"} onClick={() => setView("tree")}>
            <GitBranch className="size-3.5" />
            Tree
          </ViewTab>
          <ViewTab active={view === "graph"} onClick={() => setView("graph")}>
            <Network className="size-3.5" />
            Graph
          </ViewTab>
        </div>

        <Button
          variant="ghost"
          size="sm"
          className="ml-auto px-2"
          onClick={onClose}
          aria-label="Hide branches"
          title="Hide branches"
        >
          <X />
        </Button>
      </div>

      {/* Both directions: the graph is as wide as the conversation forks. */}
      <div className="min-h-0 flex-1 overflow-auto">
        {graph === undefined ? (
          <p className="px-3 py-3 font-mono text-[10px] tracking-[0.12em] text-dim uppercase">
            Loading
          </p>
        ) : roots.length === 0 ? (
          <p className="px-3 py-3 text-[12.5px] leading-[1.5] text-muted">
            Nothing here yet. Send a message and the conversation will start to
            take shape.
          </p>
        ) : view === "tree" ? (
          <TurnTree
            roots={roots}
            selectedId={selected?.id ?? null}
            pathMessageIds={pathMessageIds}
            currentFrom={currentFrom}
            expanded={expanded}
            onToggle={toggle}
            onOpen={open}
          />
        ) : (
          <div className="p-1">
            <TurnGraph
              roots={roots}
              selectedId={selected?.id ?? null}
              pathMessageIds={pathMessageIds}
              currentFrom={currentFrom}
              onOpen={open}
            />
          </div>
        )}
      </div>

      {selected === null ? null : (
        <Footer
          selected={selected}
          currentFrom={currentFrom}
          onOpen={open}
          onDelete={() => setConfirming(selected)}
        />
      )}

      {confirming === null ? null : (
        <ConfirmDialog
          title="Delete this branch?"
          description={
            <>
              The branch off{" "}
              <strong className="font-medium text-ink">
                &ldquo;{plainPreview(confirming.anchoredText ?? "")}&rdquo;
              </strong>{" "}
              will be deleted, along with{" "}
              {subtreeSize(confirming) === 1
                ? "its message"
                : `all ${subtreeSize(confirming)} messages in it`}{" "}
              and any branches inside it. This cannot be undone.
            </>
          }
          confirmLabel="Delete branch"
          pendingLabel="Deleting"
          pending={remove.isPending}
          error={remove.isError ? remove.error.message : undefined}
          onConfirm={() => remove.mutate(confirming.id)}
          onCancel={() => setConfirming(null)}
        />
      )}
    </div>
  );
}

function ViewTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex items-center gap-1.5 rounded-[5px] px-2 py-[3px] text-[12px] transition-colors",
        active ? "bg-raised text-ink" : "text-muted hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

/**
 * What is selected, and the one thing to do with it.
 *
 * A branch and the main thread are the same action with different words, and
 * the button says which - "Open branch" against "Open main thread" - because
 * `?from=` being null is not something the reader should have to infer.
 */
function Footer({
  selected,
  currentFrom,
  onOpen,
  onDelete,
}: {
  selected: TurnNode;
  currentFrom: string | null;
  onOpen: (node: TurnNode) => void;
  onDelete: () => void;
}) {
  const here = selected.viewFrom === currentFrom;
  const question = selected.messages.find((message) => message.role === "user");
  const reply = selected.messages.find((message) => message.role === "assistant");

  return (
    <div className="border-t border-line px-3 py-2.5">
      {selected.anchoredText === null ? null : (
        <p
          className="mb-1 truncate font-serif text-[12px] leading-[1.45] text-accent italic"
          title={plainPreview(selected.anchoredText)}
        >
          &ldquo;{plainPreview(selected.anchoredText)}&rdquo;
        </p>
      )}

      <p className="mb-2 line-clamp-2 text-[12.5px] leading-[1.45] text-muted">
        {plainPreview((question ?? reply)?.content ?? "") || "Empty message"}
      </p>

      <div className="flex items-center gap-2">
        <span className="font-mono text-[9.5px] tracking-[0.08em] text-dim uppercase">
          {selected.viewFrom === null ? "main thread" : "branch"}
          {selected.messages.length === 2 ? " · turn" : ""}
        </span>
        {/* Only a branch can be deleted: a turn in the middle of a thread
            would take the rest of the thread with it, and the root means the
            conversation, which is deleted from the sidebar. The backend
            refuses both, so this button is absent rather than disabled. */}
        {selected.branch ? (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto px-2 hover:bg-danger-tint hover:text-danger"
            onClick={onDelete}
            aria-label="Delete this branch"
            title="Delete this branch"
          >
            <Trash2 />
          </Button>
        ) : null}
        <Button
          variant={here ? "secondary" : "primary"}
          size="sm"
          className={selected.branch ? "" : "ml-auto"}
          onClick={() => onOpen(selected)}
        >
          {here
            ? "Reading this"
            : selected.viewFrom === null
              ? "Open main thread"
              : "Open branch"}
        </Button>
      </div>
    </div>
  );
}
