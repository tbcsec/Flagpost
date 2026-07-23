import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";
import { EmptyState, FlagEmptyIcon } from "@/components/ui/empty-state";

describe("EmptyState", () => {
  it("renders the title, description, and an action", () => {
    render(
      <EmptyState
        icon={<FlagEmptyIcon />}
        title="No challenges yet"
        description="Publish your first challenge to open the competition."
        action={<Button>Create challenge</Button>}
      />,
    );
    expect(screen.getByRole("heading", { name: "No challenges yet" })).toBeInTheDocument();
    expect(
      screen.getByText("Publish your first challenge to open the competition."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create challenge" })).toBeInTheDocument();
  });

  it("renders without an action or description", () => {
    render(<EmptyState title="Nothing here" />);
    expect(screen.getByRole("heading", { name: "Nothing here" })).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
