import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { judgeProblemApi } from "@/lib/api";

// File downloads (#451 problem packages): the saved name can come from the
// server's Content-Disposition, and a failure carries the server's message.

let saved: string[] = [];

beforeEach(() => {
  saved = [];
  vi.stubGlobal("URL", { ...URL, createObjectURL: () => "blob:x", revokeObjectURL: () => {} });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    saved.push(this.download);
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function respond(body: BodyInit, init: ResponseInit) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, init)));
}

describe("problem package downloads", () => {
  it("saves under the name the server gives", async () => {
    respond("zip", { status: 200, headers: { "Content-Disposition": 'attachment; filename="sumoftwo.zip"' } });
    await judgeProblemApi.exportPackage("c", "p");
    expect(saved).toEqual(["sumoftwo.zip"]);
  });

  it("prefers the encoded name, and falls back when there is none", async () => {
    respond("zip", {
      status: 200,
      headers: { "Content-Disposition": "attachment; filename=\"x.zip\"; filename*=UTF-8''caf%C3%A9.zip" },
    });
    await judgeProblemApi.exportPackage("c", "p");
    respond("zip", { status: 200 });
    await judgeProblemApi.exportPackage("c", "p");
    expect(saved).toEqual(["café.zip", "problem-package.zip"]);
  });

  it("fails with the server's reason", async () => {
    respond(JSON.stringify({ detail: "The test data for “Sum” couldn't be read from storage" }), {
      status: 409,
      headers: { "Content-Type": "application/json" },
    });
    await expect(judgeProblemApi.exportPackage("c", "p")).rejects.toThrow(
      "The test data for “Sum” couldn't be read from storage",
    );
    respond("<html>bad gateway</html>", { status: 502 });
    await expect(judgeProblemApi.exportPackages("c")).rejects.toThrow("Export failed");
    expect(saved).toEqual([]);
  });
});
