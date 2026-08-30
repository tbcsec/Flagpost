import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";
import type { InstanceSettings } from "@/lib/types";

// Kubernetes site-config surface (#320 slice 6). The k8s fields are conditional
// on the selected backend, and the write-only token mirrors the registry
// credential (a set-indicator, never read back).

const mockUpdate = vi.fn();
const mockTest = vi.fn();
let settings: InstanceSettings;

vi.mock("@/lib/hooks/use-instances", () => ({
  useInstanceSettings: () => ({ data: settings, isLoading: false }),
  useUpdateInstanceSettings: () => ({ mutate: mockUpdate, isPending: false }),
  useTestInstanceConnection: () => ({ mutate: mockTest, isPending: false }),
}));
vi.mock("@/stores/toast", () => ({ toast: vi.fn() }));

import { InstancesSettingsPanel } from "./instances-settings-panel";

function baseSettings(over: Partial<InstanceSettings> = {}): InstanceSettings {
  return {
    enabled: false,
    backend: "docker",
    endpoint_url: "https://k8s:6443",
    public_host: "chal.example.org",
    registry_credentials_set: false,
    tcp_port_min: 30000,
    tcp_port_max: 32767,
    default_cpu: 1,
    default_memory_mb: 256,
    default_pids: 256,
    max_concurrent: 100,
    egress_policy: "deny",
    chal_base_domain: null,
    spawn_rate_limit: 0,
    spawn_rate_window_seconds: 60,
    k8s_namespace: "flagpost-instances",
    k8s_bearer_token_set: false,
    k8s_ca_cert: null,
    k8s_ingress_class: null,
    k8s_image_pull_secret: null,
    k8s_cluster_cidr: null,
    ...over,
  };
}

describe("InstancesSettingsPanel — kubernetes", () => {
  beforeEach(() => {
    mockUpdate.mockClear();
    mockTest.mockClear();
  });

  it("hides the kubernetes fields for the docker backend", () => {
    settings = baseSettings({ backend: "docker" });
    renderWithIntl(<InstancesSettingsPanel />);
    expect(screen.queryByLabelText("Namespace")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Service-account token")).not.toBeInTheDocument();
  });

  it("shows the kubernetes fields when the backend is kubernetes", () => {
    settings = baseSettings({ backend: "kubernetes" });
    renderWithIntl(<InstancesSettingsPanel />);
    expect(screen.getByLabelText("Namespace")).toBeInTheDocument();
    expect(screen.getByLabelText("Service-account token")).toBeInTheDocument();
    expect(screen.getByLabelText("API server CA certificate")).toBeInTheDocument();
    expect(screen.getByLabelText("Cluster CIDRs")).toBeInTheDocument();
  });

  it("reveals the fields when kubernetes is selected", () => {
    settings = baseSettings({ backend: "docker" });
    renderWithIntl(<InstancesSettingsPanel />);
    fireEvent.change(screen.getByLabelText("Backend"), {
      target: { value: "kubernetes" },
    });
    expect(screen.getByLabelText("Namespace")).toBeInTheDocument();
  });

  it("sends the kubernetes fields (token only when typed) on save", () => {
    settings = baseSettings({ backend: "kubernetes" });
    renderWithIntl(<InstancesSettingsPanel />);
    fireEvent.change(screen.getByLabelText("Service-account token"), {
      target: { value: "sa-token-123" },
    });
    fireEvent.change(screen.getByLabelText("Cluster CIDRs"), {
      target: { value: "10.42.0.0/16" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(mockUpdate).toHaveBeenCalledTimes(1);
    const payload = mockUpdate.mock.calls[0][0];
    expect(payload.backend).toBe("kubernetes");
    expect(payload.k8s_namespace).toBe("flagpost-instances");
    expect(payload.k8s_cluster_cidr).toBe("10.42.0.0/16");
    expect(payload.k8s_bearer_token).toBe("sa-token-123");
  });

  it("omits the kubernetes fields from a docker save", () => {
    // A value typed into the k8s card then hidden by switching to docker must
    // not travel in a docker payload and fail on an invisible field.
    settings = baseSettings({ backend: "docker" });
    renderWithIntl(<InstancesSettingsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(mockUpdate).toHaveBeenCalledTimes(1);
    const payload = mockUpdate.mock.calls[0][0];
    expect(payload.backend).toBe("docker");
    for (const key of [
      "k8s_namespace",
      "k8s_ca_cert",
      "k8s_ingress_class",
      "k8s_image_pull_secret",
      "k8s_cluster_cidr",
      "k8s_bearer_token",
    ]) {
      expect(payload).not.toHaveProperty(key);
    }
  });

  it("does not send the token when left blank (keeps the stored one)", () => {
    settings = baseSettings({ backend: "kubernetes", k8s_bearer_token_set: true });
    renderWithIntl(<InstancesSettingsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(mockUpdate).toHaveBeenCalledTimes(1);
    expect(mockUpdate.mock.calls[0][0]).not.toHaveProperty("k8s_bearer_token");
  });

  it("blocks enabling kubernetes with no token", async () => {
    const { toast } = await import("@/stores/toast");
    settings = baseSettings({ backend: "kubernetes", enabled: true, k8s_bearer_token_set: false });
    renderWithIntl(<InstancesSettingsPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    // The client-side invariant refuses the save and toasts instead.
    expect(mockUpdate).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalled();
  });
});
