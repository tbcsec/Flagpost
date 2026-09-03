import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DemoCredentialsEditor } from "@/components/admin/demo-credentials-editor";
import { renderWithIntl } from "@/test/intl";
import type { DemoCredential } from "@/lib/types";

const ONE: DemoCredential = {
  label: "Owner",
  description: "full control",
  identifier: "acme-owner",
  password: "pw-1234",
};

describe("DemoCredentialsEditor", () => {
  it("shows the empty state and adds a blank row", () => {
    const onChange = vi.fn();
    renderWithIntl(<DemoCredentialsEditor value={[]} onChange={onChange} />);
    expect(screen.getByText("No demo accounts yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add account" }));
    expect(onChange).toHaveBeenCalledWith([
      { label: "", description: "", identifier: "", password: "" },
    ]);
  });

  it("edits a field through onChange", () => {
    const onChange = vi.fn();
    renderWithIntl(<DemoCredentialsEditor value={[ONE]} onChange={onChange} />);
    const identifier = screen.getByDisplayValue("acme-owner");
    fireEvent.change(identifier, { target: { value: "acme-admin" } });
    expect(onChange).toHaveBeenCalledWith([{ ...ONE, identifier: "acme-admin" }]);
  });

  it("removes a row", () => {
    const onChange = vi.fn();
    renderWithIntl(<DemoCredentialsEditor value={[ONE]} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("hides the add button once the maximum is reached", () => {
    const onChange = vi.fn();
    const twelve = Array.from({ length: 12 }, (_, i) => ({
      ...ONE,
      identifier: `u${i}`,
    }));
    renderWithIntl(
      <DemoCredentialsEditor value={twelve} onChange={onChange} />,
    );
    expect(
      screen.queryByRole("button", { name: "Add account" }),
    ).not.toBeInTheDocument();
  });
});
