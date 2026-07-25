import { FlagpostMark } from "@/components/brand/flagpost-mark";

// The Flagpost project's public home. This footer is a **mandatory** attribution:
// an org may fully rebrand the platform (custom logo, name, palette), but Flagpost
// stays visible as the underlying project. It is intentionally not configurable.
const FLAGPOST_URL = "https://flagpost.io";

/** A subtle, always-present "Powered by Flagpost" footer. Rendered on every page
 *  (the app shell and the public auth screens) so attribution can't be removed by
 *  branding. Uses the built-in Flagpost mark, never the org's custom logo. */
export function PoweredByFooter({ className }: { className?: string }) {
  return (
    <footer
      className={
        "flex items-center justify-center gap-1.5 py-6 text-xs text-muted-foreground" +
        (className ? ` ${className}` : "")
      }
    >
      <span>Powered by</span>
      <a
        href={FLAGPOST_URL}
        target="_blank"
        rel="noreferrer noopener"
        className="inline-flex items-center gap-1 font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        {/* Decorative — the link text already names Flagpost. */}
        <span aria-hidden="true" className="inline-flex">
          <FlagpostMark size={14} theme="dark" title="Flagpost" />
        </span>
        Flagpost
      </a>
    </footer>
  );
}
