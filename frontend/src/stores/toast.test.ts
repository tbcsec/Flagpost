import { afterEach, describe, expect, it, vi } from "vitest";

import { toast, useToastStore } from "@/stores/toast";

afterEach(() => {
  useToastStore.setState({ toasts: [] });
  vi.useRealTimers();
});

describe("toast store", () => {
  it("pushes a toast with the given variant", () => {
    toast("Saved", { variant: "success", description: "All good" });
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toMatchObject({
      title: "Saved",
      description: "All good",
      variant: "success",
    });
  });

  it("defaults to the default variant", () => {
    toast("Hi");
    expect(useToastStore.getState().toasts[0].variant).toBe("default");
  });

  it("dismisses by id", () => {
    toast("One");
    const id = useToastStore.getState().toasts[0].id;
    useToastStore.getState().dismiss(id);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("auto-dismisses after the timeout", () => {
    vi.useFakeTimers();
    toast("Temporary");
    expect(useToastStore.getState().toasts).toHaveLength(1);
    vi.advanceTimersByTime(4000);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});
