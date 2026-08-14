"use client";

// One-time celebratory modal state (#219). A certificate release shows the modal
// exactly once per (competition, release) — closing it is fine, the participant
// re-finds the certificate via Profile → Certificates, the scoreboard card, or
// the persistent notification. "Seen" is persisted in localStorage keyed by the
// release timestamp, so a *re-release* (rare) shows it again.

import { create } from "zustand";

const SEEN_KEY = "fp:cert-modal-seen";

function loadSeen(): Set<string> {
  try {
    return new Set(JSON.parse(window.localStorage.getItem(SEEN_KEY) ?? "[]"));
  } catch {
    return new Set();
  }
}

function persist(seen: Set<string>) {
  try {
    window.localStorage.setItem(SEEN_KEY, JSON.stringify([...seen]));
  } catch {
    /* private mode / SSR — the modal just shows again next load, harmless */
  }
}

interface CertificateModalState {
  active: { competitionId: string; competitionName: string } | null;
  /** Show the modal once for this release; a no-op if already seen. */
  maybeShow: (competitionId: string, competitionName: string, releaseToken: string) => void;
  dismiss: () => void;
}

export const useCertificateModal = create<CertificateModalState>((set, get) => ({
  active: null,
  maybeShow: (competitionId, competitionName, releaseToken) => {
    if (get().active) return; // one at a time
    const key = `${competitionId}:${releaseToken}`;
    const seen = loadSeen();
    if (seen.has(key)) return;
    seen.add(key);
    persist(seen);
    set({ active: { competitionId, competitionName } });
  },
  dismiss: () => set({ active: null }),
}));
