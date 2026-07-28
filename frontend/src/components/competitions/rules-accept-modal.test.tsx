import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RulesAcceptModal } from "@/components/competitions/rules-accept-modal";
import type { RichTextDoc } from "@/lib/types";

const DOC: RichTextDoc = {
  type: "doc",
  content: [
    { type: "paragraph", content: [{ type: "text", text: "No flag sharing." }] },
  ],
};

describe("RulesAcceptModal", () => {
  it("renders the rules text", () => {
    render(
      <RulesAcceptModal open mode="accept" rules={DOC} onConfirm={() => {}} />,
    );
    expect(screen.getByText("No flag sharing.")).toBeInTheDocument();
  });

  it("blocks Accept until the checkbox is ticked", () => {
    const onConfirm = vi.fn();
    render(
      <RulesAcceptModal open mode="accept" rules={DOC} onConfirm={onConfirm} />,
    );
    const accept = screen.getByRole("button", { name: "Accept" });
    expect(accept).toBeDisabled();
    fireEvent.click(accept);
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("checkbox"));
    expect(accept).toBeEnabled();
    fireEvent.click(accept);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("display mode has no checkbox and Continue works immediately", () => {
    const onConfirm = vi.fn();
    render(
      <RulesAcceptModal open mode="display" rules={DOC} onConfirm={onConfirm} />,
    );
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    const cont = screen.getByRole("button", { name: "Continue" });
    expect(cont).toBeEnabled();
    fireEvent.click(cont);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("disables the confirm button while the accept is pending", () => {
    render(
      <RulesAcceptModal
        open
        mode="accept"
        rules={DOC}
        pending
        onConfirm={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByRole("button", { name: "Accepting…" })).toBeDisabled();
  });

  it("hides Cancel when not dismissable (the in-app gate)", () => {
    render(
      <RulesAcceptModal
        open
        mode="accept"
        rules={DOC}
        dismissable={false}
        onConfirm={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("offers Cancel when dismissable and reports it", () => {
    const onCancel = vi.fn();
    render(
      <RulesAcceptModal
        open
        mode="accept"
        rules={DOC}
        onConfirm={() => {}}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
