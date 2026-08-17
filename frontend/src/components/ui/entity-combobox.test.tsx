import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { EntityCombobox } from "@/components/ui/entity-combobox";

// The automation condition field picker is a *free-text* combobox: it stores the
// raw payload key (`minutes_remaining`) the engine matches on, but must read as a
// human label (`Minutes remaining`) at rest (#211) while still letting a power
// user type an arbitrary field path that isn't in the catalog.
describe("EntityCombobox — free-text field picker", () => {
  const fieldOptions = [
    { value: "minutes_remaining", label: "Minutes remaining" },
    { value: "is_first_blood", label: "First blood" },
  ];

  it("shows the resolved label at rest, the raw key when editing", () => {
    renderWithIntl(
      <EntityCombobox
        freeText
        options={fieldOptions}
        value="minutes_remaining"
        onChange={() => {}}
      />,
    );
    const input = screen.getByRole("combobox") as HTMLInputElement;
    // Closed: the human label, never the stored key.
    expect(input.value).toBe("Minutes remaining");
    // Focused: the raw key, editable as free text.
    fireEvent.focus(input);
    expect(input.value).toBe("minutes_remaining");
  });

  it("surfaces the resolved option in the list even when the value is the raw key", () => {
    renderWithIntl(
      <EntityCombobox
        freeText
        options={fieldOptions}
        value="minutes_remaining"
        onChange={() => {}}
      />,
    );
    const input = screen.getByRole("combobox");
    fireEvent.focus(input);
    // Filtering by the raw key still finds its option (matched by value, not just
    // the label — the underscore key won't substring-match "Minutes remaining").
    expect(screen.getByRole("option", { name: "Minutes remaining" })).toBeTruthy();
  });

  it("keeps an uncatalogued field path exactly as typed (escape hatch)", () => {
    renderWithIntl(
      <EntityCombobox
        freeText
        options={fieldOptions}
        value="payload.custom.path"
        onChange={() => {}}
      />,
    );
    const input = screen.getByRole("combobox") as HTMLInputElement;
    expect(input.value).toBe("payload.custom.path");
  });
});

describe("EntityCombobox — id picker (non-free-text)", () => {
  it("shows the option label for a resolved id, not the id itself", () => {
    renderWithIntl(
      <EntityCombobox
        options={[
          { value: "u-123", label: "Alice" },
          { value: "u-456", label: "Bob" },
        ]}
        value="u-123"
        onChange={() => {}}
      />,
    );
    const input = screen.getByRole("combobox") as HTMLInputElement;
    expect(input.value).toBe("Alice");
  });
});
