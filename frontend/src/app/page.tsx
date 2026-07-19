"use client";

import Link from "next/link";

import { CompetitionList } from "@/components/competitions/competition-list";
import { CreateCompetitionDialog } from "@/components/competitions/create-competition-dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useLogout } from "@/lib/hooks/use-users";
import { useAuthStore } from "@/stores/auth";

// The Tier 0 end-to-end surface: session state drives which view renders, and
// the authenticated view exercises the whole stack — hooks -> API client ->
// RBAC-gated endpoints -> event bus.
export default function Home() {
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const logout = useLogout();

  if (status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </main>
    );
  }

  if (status === "anonymous") {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center p-8">
        <Card>
          <CardHeader>
            <CardTitle>Flagpost</CardTitle>
            <CardDescription>
              Sign in or create an account to continue.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex gap-3">
            <Button asChild>
              <Link href="/login">Sign in</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/register">Register</Link>
            </Button>
          </CardContent>
        </Card>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Competitions</h1>
          <p className="text-sm text-muted-foreground">
            Signed in as {user?.display_name}
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
        >
          Sign out
        </Button>
      </div>

      <div className="flex justify-end">
        <CreateCompetitionDialog />
      </div>

      <CompetitionList />
    </main>
  );
}
