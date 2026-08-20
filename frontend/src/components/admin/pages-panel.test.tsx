import { screen } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

// Chrome strings for the pages admin surface (#198). The catalog-parity test
// (src/i18n/messages.test.ts) checks keys exist across locales, but it can't
// see how a string is *called*: a message containing `<tag>` compiles fine yet
// fails at render time under plain t() (no tag handlers), and next-intl falls
// back to printing the raw key path. That's exactly how "pages.subtitle"
// shipped rendering as "pages.subtitle" — its text said `/p/<slug>`, and
// `<slug>` parsed as an unhandled rich-text tag. So this renders every static
// chrome string through the real provider the way the components call it, and
// fails if any resolves to its own key path.

const STATIC_KEYS = [
  "heading",
  "subtitle",
  "empty.title",
  "empty.description",
  "noAccess.title",
  "noAccess.description",
  "form.title",
  "form.slug",
  "form.icon",
  "form.content",
  "form.visibility",
  "form.status",
  "visibility.public",
  "visibility.authenticated",
  "status.draft",
  "status.published",
  "actions.add",
  "actions.create",
  "actions.save",
  "actions.cancel",
  "actions.edit",
  "actions.delete",
  "actions.moveUp",
  "actions.moveDown",
  "delete.title",
] as const;

function AllPagesStrings() {
  const t = useTranslations("pages");
  return (
    <ul>
      {STATIC_KEYS.map((key) => (
        // Plain t(), exactly as the components use these keys.
        <li key={key} data-key={key}>
          {t(key)}
        </li>
      ))}
    </ul>
  );
}

describe("pages admin chrome strings", () => {
  it("every static string renders as text, not as its own key path", () => {
    renderWithIntl(<AllPagesStrings />);
    for (const key of STATIC_KEYS) {
      const text = screen.getByText(
        (_, el) => el?.getAttribute("data-key") === key,
      ).textContent;
      expect(text, key).toBeTruthy();
      // next-intl's failure mode is echoing the exact dotted key path. (Only
      // an exact match: English prose can legitimately contain "pages." — the
      // subtitle's own "…Contact pages. They…" does.)
      expect(text, key).not.toBe(`pages.${key}`);
    }
  });
});
