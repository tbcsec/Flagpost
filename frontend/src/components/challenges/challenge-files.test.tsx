import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { ChallengeFiles } from "@/components/challenges/challenge-files";
import type { Attachment } from "@/lib/types";

// Competitors' downloads of a challenge's files (#451 — they had no way to
// download them before).

let files: Attachment[] = [];
const download = vi.fn();
vi.mock("@/lib/hooks/use-attachments", () => ({
  useAttachments: () => ({ data: files }),
  useDownloadAttachment: () => ({ mutate: download, isPending: false, isError: false }),
}));

describe("ChallengeFiles", () => {
  it("lists the files and downloads one", () => {
    files = [
      { id: "a1", challenge_id: "p1", filename: "problem.en.tex", content_type: "text/plain", size_bytes: 2048, created_at: "2026-10-15T10:00:00Z" },
    ];
    renderWithIntl(<ChallengeFiles competitionId="c1" challengeId="p1" />);
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download problem.en.tex" }));
    expect(download).toHaveBeenCalledWith("a1");
  });

  it("is nothing when there are no files", () => {
    files = [];
    const { container } = renderWithIntl(<ChallengeFiles competitionId="c1" challengeId="p1" />);
    expect(container).toBeEmptyDOMElement();
  });
});
