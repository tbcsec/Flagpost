"use client";

// The server-resolved branding snapshot (#362), threaded from the root layout
// into the client tree so the very first client render matches the
// server-painted HTML: useSiteSettings uses it as placeholder data, meaning the
// lockup/name/title never render the Flagpost defaults on a branded instance.

import { createContext, useContext } from "react";

import { DEFAULT_BRAND, type BrandSnapshot } from "@/lib/brand";

const BrandContext = createContext<BrandSnapshot>(DEFAULT_BRAND);

export const BrandProvider = BrandContext.Provider;

/** The branding known at server-render time (cookie or cold-start fetch). */
export function useInitialBrand(): BrandSnapshot {
  return useContext(BrandContext);
}
