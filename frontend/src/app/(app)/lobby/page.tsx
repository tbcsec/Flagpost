"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { SectionHeader } from "@/components/app/section-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  useCompetitions,
  useJoinByCode,
  useJoinCompetition,
} from "@/lib/hooks/use-competitions";
import { toast } from "@/stores/toast";

// Lobby — where a competitor who isn't in any competition lands. Joining is now
// fully wired: self-serve for public competitions (the list below) and by
// invite code for private ones. On success the shell's nav switches out of the
// lobby (permissions are refetched) and the joined competition becomes active.
export default function LobbyPage() {
  const router = useRouter();
  const { data: competitions } = useCompetitions();
  const join = useJoinCompetition();
  const joinByCode = useJoinByCode();
  const [code, setCode] = useState("");

  // Public and not archived — an archived competition is closed to new joiners.
  const publicComps = (competitions ?? []).filter(
    (c) => c.visibility === "public" && !c.archived_at,
  );

  function onJoined(name: string) {
    toast(`Joined ${name}`, { variant: "success" });
    router.push("/");
  }

  function onJoinByCode(e: React.FormEvent) {
    e.preventDefault();
    joinByCode.mutate(code, {
      onSuccess: (comp) => {
        setCode("");
        onJoined(comp.name);
      },
      onError: (err) =>
        toast("Couldn't join", { description: (err as Error).message, variant: "destructive" }),
    });
  }

  return (
    <>
      <SectionHeader title="Lobby" subtitle="You're not currently part of any competition." />

      <Card>
        <CardHeader>
          <CardTitle>Join with an invite code</CardTitle>
          <CardDescription>For invite-only competitions</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex max-w-md gap-3" onSubmit={onJoinByCode}>
            <Input
              placeholder="Invite code"
              className="font-mono"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
            />
            <Button type="submit" disabled={joinByCode.isPending}>
              {joinByCode.isPending ? "Joining…" : "Join"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Public competitions</CardTitle>
          <CardDescription>Open to join right now</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3">
            {publicComps.map((c) => (
              <div
                key={c.id}
                className="flex items-center justify-between gap-3 rounded-md border border-border p-3.5"
              >
                <div>
                  <div className="text-sm font-medium">{c.name}</div>
                  <div className="text-xs capitalize text-muted-foreground">
                    {c.participation_mode} · {c.visibility}
                  </div>
                </div>
                <Button
                  size="sm"
                  disabled={join.isPending}
                  onClick={() =>
                    join.mutate(c.id, {
                      onSuccess: () => onJoined(c.name),
                      onError: (err) =>
                        toast("Couldn't join", {
                          description: (err as Error).message,
                          variant: "destructive",
                        }),
                    })
                  }
                >
                  Join
                </Button>
              </div>
            ))}
            {publicComps.length === 0 && (
              <p className="text-sm text-muted-foreground">No public competitions right now.</p>
            )}
          </div>
        </CardContent>
      </Card>
    </>
  );
}
