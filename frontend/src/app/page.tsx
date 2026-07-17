"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { getHello } from "@/lib/api";

// Interim home: a design-system showcase that also confirms the backend is
// reachable. Phase E replaces this with the real auth-aware home (login prompt
// / competitions list). Kept token-only — no raw colours (§9).
export default function Home() {
  const [message, setMessage] = useState<string>("Contacting backend…");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHello()
      .then((data) => setMessage(data.message))
      .catch((err) => setError(String(err)));
  }, []);

  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col items-center justify-center gap-6 p-8">
      <Card className="w-full">
        <CardHeader>
          <CardTitle>CTF Platform</CardTitle>
          <CardDescription>Tier 0 foundation</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="rounded-md bg-muted px-4 py-3 text-sm text-muted-foreground">
            {error ? `Backend unreachable: ${error}` : message}
          </p>
          <div className="flex gap-2">
            <Button>Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="outline">Outline</Button>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
