"use client";

// One hook module per domain (ARCHITECTURE.md §8). Custom brand themes (#323).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { themesApi } from "@/lib/api";
import type { ThemePreset, ThemePresetInput, ThemePresetUpdate } from "@/lib/types";

const THEMES_KEY = ["themes"] as const;
const SITE_SETTINGS_KEY = ["site-settings"] as const;

export function useThemes(enabled = true) {
  return useQuery({
    queryKey: THEMES_KEY,
    queryFn: themesApi.list,
    enabled,
  });
}

/** Any theme mutation may change the *active* theme's tokens, so refresh both the
 *  library and the site-settings query the ThemeApplier paints from. */
function useInvalidateThemes() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: THEMES_KEY });
    queryClient.invalidateQueries({ queryKey: SITE_SETTINGS_KEY });
  };
}

export function useCreateTheme() {
  const invalidate = useInvalidateThemes();
  return useMutation({
    mutationFn: (input: ThemePresetInput) => themesApi.create(input),
    onSuccess: invalidate,
  });
}

export function useUpdateTheme() {
  const invalidate = useInvalidateThemes();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: ThemePresetUpdate }) =>
      themesApi.update(id, input),
    onSuccess: invalidate,
  });
}

export function useDeleteTheme() {
  const invalidate = useInvalidateThemes();
  return useMutation({
    mutationFn: (id: string) => themesApi.remove(id),
    onSuccess: invalidate,
  });
}

export type { ThemePreset };
