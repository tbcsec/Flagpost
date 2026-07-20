"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useCompetitions } from "@/lib/hooks/use-competitions";

// Lobby — where a participant who isn't in any competition lands. The public
// competitions list is real (filtered from the competitions endpoint). There's
// no "join a competition" endpoint yet (joining currently happens per-team via
// an invite code inside a competition), so the join actions are flagged.
export default function LobbyPage() {
  const { data: competitions } = useCompetitions();
  const publicComps = (competitions ?? []).filter((c) => c.visibility === "public");

  return (
    <>
      <SectionHeader title="Lobby" subtitle="You're not currently part of any competition." />

      <NotWiredNote>
        A dedicated join-a-competition flow (invite codes at the competition level,
        self-serve public join) isn&apos;t built — joining currently happens
        per-team from inside a competition.
      </NotWiredNote>

      <Card>
        <CardHeader>
          <CardTitle>Join with an invite code</CardTitle>
          <CardDescription>For invite-only competitions</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex max-w-md gap-3" onSubmit={(e) => e.preventDefault()}>
            <Input placeholder="Invite code" className="font-mono" disabled />
            <Button type="submit" disabled>Join</Button>
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
                <Button size="sm" disabled>Join</Button>
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
