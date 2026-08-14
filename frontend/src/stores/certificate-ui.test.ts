import { beforeEach, describe, expect, it } from "vitest";

import { useCertificateModal } from "@/stores/certificate-ui";

// The release celebration must fire exactly once per (competition, release), so a
// participant who closes it isn't nagged, but a genuine re-release shows again.
describe("certificate release modal (one-time)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useCertificateModal.setState({ active: null });
  });

  it("shows once per release, then not again after dismiss", () => {
    useCertificateModal.getState().maybeShow("c1", "CTF", "2026-08-13T00:00:00Z");
    expect(useCertificateModal.getState().active?.competitionId).toBe("c1");

    useCertificateModal.getState().dismiss();
    expect(useCertificateModal.getState().active).toBeNull();

    useCertificateModal.getState().maybeShow("c1", "CTF", "2026-08-13T00:00:00Z");
    expect(useCertificateModal.getState().active).toBeNull();
  });

  it("shows again for a new release token", () => {
    useCertificateModal.getState().maybeShow("c1", "CTF", "t1");
    useCertificateModal.getState().dismiss();
    useCertificateModal.getState().maybeShow("c1", "CTF", "t2");
    expect(useCertificateModal.getState().active?.competitionId).toBe("c1");
  });

  it("does not stack a second modal while one is active", () => {
    useCertificateModal.getState().maybeShow("c1", "One", "t1");
    useCertificateModal.getState().maybeShow("c2", "Two", "t1");
    expect(useCertificateModal.getState().active?.competitionName).toBe("One");
  });
});
