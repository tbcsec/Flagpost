import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";

describe("Button", () => {
  it("renders its children and applies the token-based default variant", () => {
    render(<Button>Create</Button>);
    const button = screen.getByRole("button", { name: "Create" });
    // Consumes the design token, not a raw colour (§9).
    expect(button).toHaveClass("bg-primary");
  });

  it("renders as a child element when asChild is set", () => {
    render(
      <Button asChild>
        <a href="/login">Sign in</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "Sign in" });
    expect(link).toHaveClass("bg-primary");
  });
});
