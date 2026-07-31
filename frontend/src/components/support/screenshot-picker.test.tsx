import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import {
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENTS_PER_TICKET,
  ScreenshotPicker,
} from "@/components/support/screenshot-picker";

function file(name: string, type: string, size = 1024): File {
  const f = new File(["x"], name, { type });
  // File size is read-only, so stub it — the picker only reads `.size`.
  Object.defineProperty(f, "size", { value: size });
  return f;
}

/** Wraps the controlled picker so selections accumulate like they do in use. */
function Harness({ existingCount = 0 }: { existingCount?: number }) {
  const [files, setFiles] = useState<File[]>([]);
  return (
    <ScreenshotPicker
      files={files}
      onChange={setFiles}
      existingCount={existingCount}
    />
  );
}

function pick(files: File[]) {
  fireEvent.change(screen.getByLabelText("Attach screenshots"), {
    target: { files },
  });
}

describe("ScreenshotPicker", () => {
  it("accepts the three allowed image types", () => {
    render(<Harness />);
    pick([
      file("a.png", "image/png"),
      file("b.jpg", "image/jpeg"),
      file("c.webp", "image/webp"),
    ]);
    expect(screen.getByText("a.png")).toBeInTheDocument();
    expect(screen.getByText("b.jpg")).toBeInTheDocument();
    expect(screen.getByText("c.webp")).toBeInTheDocument();
  });

  it("rejects a non-image and says why, rather than dropping it silently", () => {
    render(<Harness />);
    pick([file("notes.pdf", "application/pdf")]);
    expect(screen.queryByText("notes.pdf")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "notes.pdf isn't a PNG, JPEG or WebP image",
    );
  });

  it("rejects an oversized image", () => {
    render(<Harness />);
    pick([file("huge.png", "image/png", MAX_ATTACHMENT_BYTES + 1)]);
    expect(screen.queryByText("huge.png")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("is larger than");
  });

  it("caps the selection and explains the cap", () => {
    render(<Harness />);
    pick(
      Array.from({ length: MAX_ATTACHMENTS_PER_TICKET + 2 }, (_, i) =>
        file(`shot-${i}.png`, "image/png"),
      ),
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(MAX_ATTACHMENTS_PER_TICKET);
    expect(screen.getByRole("alert")).toHaveTextContent(
      `only ${MAX_ATTACHMENTS_PER_TICKET} images can be attached`,
    );
  });

  it("counts attachments already on the ticket against the cap", () => {
    // Four already posted → only one more may be staged, and the input closes
    // once the ticket is full.
    render(<Harness existingCount={MAX_ATTACHMENTS_PER_TICKET - 1} />);
    expect(screen.getByText(/1 left/)).toBeInTheDocument();

    pick([file("a.png", "image/png"), file("b.png", "image/png")]);
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("Attachment limit reached for this ticket")).toBeInTheDocument();
    expect(screen.getByLabelText("Attach screenshots")).toBeDisabled();
  });

  it("removes a staged file before posting", () => {
    render(<Harness />);
    pick([file("a.png", "image/png"), file("b.png", "image/png")]);
    fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    expect(screen.queryByText("a.png")).not.toBeInTheDocument();
    expect(screen.getByText("b.png")).toBeInTheDocument();
  });
});
