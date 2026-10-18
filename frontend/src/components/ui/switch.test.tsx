import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Switch } from "@/components/ui/switch";

describe("Switch", () => {
  it("reports its state and flips it on click", () => {
    const onChange = vi.fn();
    render(<Switch checked={false} onCheckedChange={onChange} aria-label="Feedback" />);
    const toggle = screen.getByRole("switch", { name: "Feedback" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("does nothing while disabled", () => {
    const onChange = vi.fn();
    render(<Switch checked onCheckedChange={onChange} disabled aria-label="Feedback" />);
    const toggle = screen.getByRole("switch", { name: "Feedback" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(toggle);
    expect(onChange).not.toHaveBeenCalled();
  });
});
