"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

// Safe markdown renderer for AI assistant output (#98, ADR-0023). The model's
// answers arrive as markdown; we render them without ever executing raw HTML.
// react-markdown builds a React element tree (no innerHTML) and, with no
// rehype-raw plugin, treats any HTML in the model output as literal text — so a
// model that emits <script> or an onerror handler renders it inert. Links open
// in a new tab with noopener/noreferrer/nofollow, and react-markdown's default
// urlTransform strips dangerous URL schemes (javascript:, vbscript:, …). GFM
// adds tables, task lists, and strikethrough. Colours and spacing come from
// design tokens only (§9) — no raw values.
//
// `node` is destructured out of every component so react-markdown's internal AST
// node isn't spread onto a DOM element (which React would warn about). Inline vs
// block code isn't distinguished via a prop (react-markdown dropped `inline` in
// v9); instead block code is styled through its `pre` wrapper, which neutralises
// the inline `code` styling for its child.
const COMPONENTS: Components = {
  p: ({ node: _node, ...props }) => (
    <p className="my-2 leading-relaxed first:mt-0 last:mb-0" {...props} />
  ),
  a: ({ node: _node, ...props }) => (
    <a
      className="font-medium underline underline-offset-2"
      target="_blank"
      rel="noopener noreferrer nofollow"
      {...props}
    />
  ),
  ul: ({ node: _node, ...props }) => (
    <ul className="my-2 list-disc space-y-1 pl-5 first:mt-0 last:mb-0" {...props} />
  ),
  ol: ({ node: _node, ...props }) => (
    <ol className="my-2 list-decimal space-y-1 pl-5 first:mt-0 last:mb-0" {...props} />
  ),
  li: ({ node: _node, ...props }) => <li className="leading-relaxed" {...props} />,
  strong: ({ node: _node, ...props }) => <strong className="font-semibold" {...props} />,
  em: ({ node: _node, ...props }) => <em className="italic" {...props} />,
  h1: ({ node: _node, ...props }) => (
    <h3 className="mb-1 mt-3 text-base font-semibold first:mt-0" {...props} />
  ),
  h2: ({ node: _node, ...props }) => (
    <h3 className="mb-1 mt-3 text-base font-semibold first:mt-0" {...props} />
  ),
  h3: ({ node: _node, ...props }) => (
    <h4 className="mb-1 mt-3 text-sm font-semibold first:mt-0" {...props} />
  ),
  h4: ({ node: _node, ...props }) => (
    <h4 className="mb-1 mt-3 text-sm font-semibold first:mt-0" {...props} />
  ),
  blockquote: ({ node: _node, ...props }) => (
    <blockquote
      className="my-2 border-l-2 border-border pl-3 text-muted-foreground"
      {...props}
    />
  ),
  hr: () => <hr className="my-3 border-border" />,
  code: ({ node: _node, className, ...props }) => (
    <code
      className={cn(
        "rounded bg-background/70 px-1 py-0.5 font-mono text-[0.85em]",
        className,
      )}
      {...props}
    />
  ),
  pre: ({ node: _node, ...props }) => (
    <pre
      className="my-2 overflow-x-auto rounded-md bg-background/70 p-3 text-[0.85em] [&>code]:rounded-none [&>code]:bg-transparent [&>code]:p-0"
      {...props}
    />
  ),
  table: ({ node: _node, ...props }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs" {...props} />
    </div>
  ),
  th: ({ node: _node, ...props }) => (
    <th className="border border-border px-2 py-1 font-semibold" {...props} />
  ),
  td: ({ node: _node, ...props }) => (
    <td className="border border-border px-2 py-1" {...props} />
  ),
};

/** Render assistant markdown safely. Empty content renders nothing. */
export function Markdown({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <div className={cn("break-words text-sm", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
