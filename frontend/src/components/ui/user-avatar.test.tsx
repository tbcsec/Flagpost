import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UserAvatar, avatarUrl } from "@/components/ui/user-avatar";

// The avatar must degrade to the pre-feature rendering (an initials circle)
// whenever no picture is set — and when one is, the URL must carry the
// cache-buster, because the serve path is immutable-cached.

describe("UserAvatar", () => {
  it("renders initials when no avatar is set", () => {
    render(
      <UserAvatar userId="u1" name="Ada Lovelace" avatarUpdatedAt={null} />,
    );
    expect(screen.getByText("AL")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("renders the image with a version-busted URL when set", () => {
    const ts = "2026-08-23T12:00:00Z";
    render(
      <UserAvatar userId="u1" name="Ada Lovelace" avatarUpdatedAt={ts} />,
    );
    const img = document.querySelector("img");
    expect(img).not.toBeNull();
    expect(img!.getAttribute("src")).toBe(
      `/api/users/u1/avatar?v=${Date.parse(ts)}`,
    );
  });

  it("single-word names get a single initial", () => {
    render(<UserAvatar userId="u2" name="participant" avatarUpdatedAt={null} />);
    expect(screen.getByText("P")).toBeInTheDocument();
  });

  it("avatarUrl is null without a timestamp", () => {
    expect(avatarUrl("u1", null)).toBeNull();
  });
});
