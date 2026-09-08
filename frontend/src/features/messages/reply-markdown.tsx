import { useCallback, useMemo, useState } from "react";
import { Check, Copy } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import type { Element } from "hast";
import { cn } from "@/lib/utils";
import { normalizeMathDelimiters } from "./math";
import {
  EDGES_ATTRIBUTE,
  SOURCE_END_ATTRIBUTE,
  SOURCE_START_ATTRIBUTE,
  rehypeSourceSpans,
  rehypeStampMath,
} from "./source-spans";
import type { AnchorRange } from "./anchor";

/**
 * A model reply, rendered.
 *
 * The model writes markdown whether or not anyone renders it, so leaving it
 * raw was never neutral - it showed the reader asterisks and pipe characters
 * where a table was meant. What makes this more than dropping in a renderer is
 * that a reply is also the surface a branch is highlighted on: the offsets an
 * anchor is written with are offsets into the *stored* text, and the rendered
 * text is a different string. `source-spans.ts` is what keeps those two in
 * agreement, and it is the reason this component owns the plugin list rather
 * than sharing a generic markdown component with the rest of the app.
 *
 * GFM for tables, task lists and strikethrough; KaTeX for the formulae the
 * model reaches for unprompted; highlight.js for fenced code. All three run
 * before the source-span pass, which reads the tree they leave behind.
 */
export function ReplyMarkdown({
  content,
  anchors,
  renderMark,
}: {
  /** The stored message text, or the live stream while one is arriving. */
  content: string;
  /** Branch spans to mark. Empty while streaming, when there are none to draw. */
  anchors: AnchorRange[];
  /**
   * Wraps a marked run. Passed in rather than imported so the popover of
   * branches stays with the turn that knows about branches.
   *
   * The stamp comes with it and has to be put back on whatever element ends
   * up around the run: the mark replaces the element the renderer stamped, so
   * dropping it leaves a hole in the middle of the reply that no offset can be
   * measured against - and selecting anything in or across that hole silently
   * stops offering a branch.
   */
  renderMark?: (
    edgeIds: string[],
    children: React.ReactNode,
    stamp: { start: string; end: string },
  ) => React.ReactNode;
}) {
  // Length-preserving, which is what makes it safe to run before parsing: the
  // parser's positions are still positions in the stored string.
  const source = useMemo(() => normalizeMathDelimiters(content), [content]);

  const rehypePlugins = useMemo(
    () => [
      // Before KaTeX, because KaTeX replaces the element that knows where the
      // formula came from.
      rehypeStampMath,
      [rehypeKatex, { throwOnError: false, errorColor: "currentColor" }],
      [rehypeHighlight, { detect: true, ignoreMissing: true }],
      // Last on purpose: it stamps the tree the two above have finished with.
      [rehypeSourceSpans, { content, anchors }],
    ],
    [content, anchors],
  );

  const components = useMemo<Components>(
    () => ({
      pre: CodeBlock,
      a: ({ children, href }) => (
        <a href={href} target="_blank" rel="noreferrer noopener">
          {children}
        </a>
      ),
      // A wide table scrolls inside its own box rather than widening the
      // thread, which would push the composer off the screen.
      table: ({ children }) => (
        <div className="reply-table-scroll">
          <table>{children}</table>
        </div>
      ),
      mark: ({ children, node }) => {
        const edgeIds = readEdgeIds(node);
        const stamp = {
          start: String(node?.properties?.[SOURCE_START_ATTRIBUTE] ?? ""),
          end: String(node?.properties?.[SOURCE_END_ATTRIBUTE] ?? ""),
        };
        if (renderMark === undefined || edgeIds.length === 0) {
          return (
            <mark
              {...{ [SOURCE_START_ATTRIBUTE]: stamp.start, [SOURCE_END_ATTRIBUTE]: stamp.end }}
            >
              {children}
            </mark>
          );
        }
        return <>{renderMark(edgeIds, children, stamp)}</>;
      },
    }),
    [renderMark],
  );

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, [remarkMath, { singleDollarTextMath: false }]]}
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the
      // tuple form of a plugin with options is wider than the exported type.
      rehypePlugins={rehypePlugins as any}
      components={components}
    >
      {source}
    </ReactMarkdown>
  );
}

function readEdgeIds(node: Element | undefined): string[] {
  const value = node?.properties?.[EDGES_ATTRIBUTE];
  return typeof value === "string" && value !== "" ? value.split(",") : [];
}

function textOf(node: Element | undefined): string {
  if (node === undefined) return "";
  return node.children
    .map((child) => {
      if (child.type === "text") return child.value;
      if (child.type === "element") return textOf(child);
      return "";
    })
    .join("");
}

/** `language-ts` on the code element, which is what the highlighter labels it. */
function languageOf(node: Element | undefined): string | null {
  const code = node?.children.find(
    (child): child is Element => child.type === "element" && child.tagName === "code",
  );
  const className = code?.properties?.className;
  const names = Array.isArray(className) ? className.map(String) : [];
  const language = names.find((name) => name.startsWith("language-"));
  return language === undefined ? null : language.slice("language-".length);
}

/** How long the copy button stays confirmed, in milliseconds. */
const COPIED_FOR = 1400;

/**
 * A fenced block, with its language named and a button to copy it.
 *
 * The button copies from the parsed tree rather than from the DOM, so what
 * lands on the clipboard is the code as the model wrote it - not the version
 * the highlighter cut into coloured spans, and with none of the chrome around
 * it.
 */
function CodeBlock({ children, node }: { children?: React.ReactNode; node?: Element }) {
  const [copied, setCopied] = useState(false);
  const language = languageOf(node);
  const code = textOf(node);

  const copy = useCallback(() => {
    void navigator.clipboard?.writeText(code).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), COPIED_FOR);
    });
  }, [code]);

  return (
    <div className="reply-code group/code">
      <div className="reply-code-bar">
        <span className="font-mono text-[10.5px] tracking-[0.08em] text-dim uppercase">
          {language ?? "code"}
        </span>
        <button
          type="button"
          onClick={copy}
          aria-label={copied ? "Copied" : "Copy code"}
          className={cn(
            "flex items-center gap-1 rounded-sm px-1.5 py-[3px] font-mono text-[10.5px] text-dim transition-colors",
            "hover:bg-raised hover:text-ink",
            // Present for keyboard and touch, quiet until the block is
            // pointed at - the same rule the sidebar's delete follows.
            "opacity-0 group-hover/code:opacity-100 focus-visible:opacity-100 max-lg:opacity-100",
          )}
        >
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>{children}</pre>
    </div>
  );
}
