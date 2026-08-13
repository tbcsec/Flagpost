import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Stub the domain hooks so the picker renders without a QueryClient/network.
vi.mock("@/lib/hooks/use-competitions", () => ({
  useCompetitions: () => ({
    data: [
      { id: "c1", name: "Spring CTF" },
      { id: "c2", name: "Fall CTF" },
    ],
  }),
}));
vi.mock("@/lib/hooks/use-challenges", () => ({
  useChallenges: () => ({ data: [{ id: "ch1", title: "Reverse Me" }] }),
}));
vi.mock("@/lib/hooks/use-feedback", () => ({
  useSurveys: () => ({ data: [{ id: "s1", title: "Exit Survey" }] }),
}));
vi.mock("@/lib/hooks/use-hints", () => ({
  useHints: () => ({ data: [{ id: "h1", body: "Look at the header", cost: 50 }] }),
}));
vi.mock("@/lib/hooks/use-teams", () => ({
  useTeams: () => ({ data: [{ id: "t1", name: "Red Team" }] }),
}));
vi.mock("@/lib/hooks/use-participants", () => ({
  useParticipants: () => ({ data: [{ user_id: "u1", display_name: "Alice" }] }),
}));

import { EntityReferencePicker } from "@/components/automations/entity-reference-picker";

const noop = () => {};

describe("EntityReferencePicker", () => {
  it("scoped rule: one dropdown, shows the entity name for a stored id", () => {
    render(
      <EntityReferencePicker entityType="challenge" competitionId="c1" value="ch1" onChange={noop} />,
    );
    const inputs = screen.getAllByRole("combobox") as HTMLInputElement[];
    expect(inputs).toHaveLength(1); // no scope selector when the rule is scoped
    expect(inputs[0].value).toBe("Reverse Me"); // name, not the id "ch1"
  });

  it("global rule: prepends a competition scope selector", () => {
    render(<EntityReferencePicker entityType="challenge" value="" onChange={noop} />);
    const inputs = screen.getAllByRole("combobox") as HTMLInputElement[];
    expect(inputs).toHaveLength(2); // competition scope + challenge
    expect(inputs[0].placeholder).toBe("Pick a competition");
  });

  it("hint: cascades through a challenge selector before the hint dropdown", () => {
    render(<EntityReferencePicker entityType="hint" competitionId="c1" value="" onChange={noop} />);
    const inputs = screen.getAllByRole("combobox") as HTMLInputElement[];
    expect(inputs).toHaveLength(2); // challenge selector + hint picker
    expect(inputs[0].placeholder).toBe("Pick a challenge");
  });

  it("competition: a single dropdown storing the id, showing the name", () => {
    render(
      <EntityReferencePicker entityType="competition" competitionId="c1" value="c2" onChange={noop} />,
    );
    const inputs = screen.getAllByRole("combobox") as HTMLInputElement[];
    expect(inputs).toHaveLength(1);
    expect(inputs[0].value).toBe("Fall CTF");
  });
});
