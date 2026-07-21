import { create } from "zustand";

// Client/UI state (§2): transient toast notifications. A tiny store rather than
// React context so any hook (mutation onSuccess/onError) can raise a toast
// without prop-drilling a dispatcher.

export type ToastVariant = "default" | "success" | "destructive";

export interface Toast {
  id: number;
  title: string;
  description?: string;
  variant: ToastVariant;
}

interface ToastState {
  toasts: Toast[];
  push: (t: Omit<Toast, "id">) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (t) => {
    const id = nextId++;
    set((s) => ({ toasts: [...s.toasts, { ...t, id }] }));
    // Auto-dismiss after a few seconds.
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) }));
    }, 4000);
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
}));

/** Raise a toast from anywhere. */
export function toast(
  title: string,
  opts: { description?: string; variant?: ToastVariant } = {},
) {
  useToastStore.getState().push({
    title,
    description: opts.description,
    variant: opts.variant ?? "default",
  });
}
