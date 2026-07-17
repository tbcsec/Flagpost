"use client";

import { useEffect, useState } from "react";
import { getHello } from "@/lib/api";

// Skeleton hello-world screen. It calls the backend directly through a thin
// fetch helper purely to prove the two containers talk. This is NOT the real
// data-access pattern: per ARCHITECTURE.md §8, feature components will go
// through one TanStack Query hook module per domain, which is a Tier 0 item
// (ROADMAP.md Tier 0 #5), not built yet.
export default function Home() {
  const [message, setMessage] = useState<string>("Contacting backend…");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHello()
      .then((data) => setMessage(data.message))
      .catch((err) => setError(String(err)));
  }, []);

  return (
    <main style={{ textAlign: "center", maxWidth: 480, padding: "2rem" }}>
      <h1 style={{ fontSize: "1.75rem", marginBottom: "0.5rem" }}>
        CTF Platform
      </h1>
      <p style={{ opacity: 0.6, marginTop: 0 }}>Tier 0 skeleton</p>
      <p
        style={{
          marginTop: "2rem",
          padding: "1rem 1.25rem",
          borderRadius: 8,
          background: "#161b22",
          border: "1px solid #30363d",
        }}
      >
        {error ? `Backend unreachable: ${error}` : message}
      </p>
    </main>
  );
}
