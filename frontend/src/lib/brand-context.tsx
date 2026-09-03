"use client";

// The server-resolved branding snapshot (#362), threaded from the root layout
// into the client tree. Lives in lib/ (not components/) because the hook layer
// consumes it — keeping the components→hooks dependency direction intact.

import { createContext, useContext } from "react";

import { DEFAULT_BRAND, type BrandSnapshot } from "@/lib/brand";

const BrandContext = createContext<BrandSnapshot>(DEFAULT_BRAND);

export const BrandProvider = BrandContext.Provider;

/** The branding known at server-render time (cookie or cold-start fetch). */
export function useInitialBrand(): BrandSnapshot {
  return useContext(BrandContext);
}
