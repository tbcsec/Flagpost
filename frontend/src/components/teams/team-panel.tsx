"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useCreateTeam,
  useJoinTeam,
  useLeaveTeam,
  useMyTeam,
  useTeams,
} from "@/lib/hooks/use-teams";

// Feature component (§14 components/<domain>). All server state via the
// use-teams hooks; membership rules (one team per competition, invite-code
// validity, mode gating) are enforced server-side and surfaced inline.
export function TeamPanel({ competitionId }: { competitionId: string }) {
  const myTeam = useMyTeam(competitionId);
  const teams = useTeams(competitionId);

  return (
    <div className="space-y-6">
      {myTeam.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading team…</p>
      ) : myTeam.data ? (
        <MyTeamCard competitionId={competitionId} team={myTeam.data} />
      ) : (
        <JoinOrCreate competitionId={competitionId} />
      )}

      <Card>
        <CardHeader>
          <CardTitle>Teams</CardTitle>
          <CardDescription>
            {teams.data?.length
              ? `${teams.data.length} team(s) registered`
              : "No teams yet."}
          </CardDescription>
        </CardHeader>
        {teams.data && teams.data.length > 0 && (
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Members</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {teams.data.map((team) => (
                  <TableRow key={team.id}>
                    <TableCell className="font-medium">{team.name}</TableCell>
                    <TableCell>{team.member_count}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        )}
      </Card>
    </div>
  );
}

function MyTeamCard({
  competitionId,
  team,
}: {
  competitionId: string;
  team: NonNullable<ReturnType<typeof useMyTeam>["data"]>;
}) {
  const leave = useLeaveTeam(competitionId);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{team.name}</CardTitle>
        <CardDescription>Your team</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <Label>Invite code</Label>
          <p className="mt-1 w-fit rounded-md bg-muted px-3 py-1.5 font-mono text-sm">
            {team.invite_code}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Share this code with teammates so they can join.
          </p>
        </div>
        <ul className="space-y-1 text-sm">
          {team.members.map((member) => (
            <li key={member.user_id}>
              {member.display_name}
              {member.is_captain && (
                <span className="ml-2 text-xs text-muted-foreground">
                  captain
                </span>
              )}
            </li>
          ))}
        </ul>
        <div className="flex items-center gap-3">
          <Button
            variant="destructive"
            onClick={() => leave.mutate()}
            disabled={leave.isPending}
          >
            {leave.isPending ? "Leaving…" : "Leave team"}
          </Button>
          {leave.isError && (
            <span className="text-sm text-destructive">
              {(leave.error as Error).message}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function JoinOrCreate({ competitionId }: { competitionId: string }) {
  const create = useCreateTeam(competitionId);
  const join = useJoinTeam(competitionId);
  const [name, setName] = useState("");
  const [inviteCode, setInviteCode] = useState("");

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Create a team</CardTitle>
          <CardDescription>You&apos;ll be the captain.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate({ name });
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="team-name">Team name</Label>
              <Input
                id="team-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>
            {create.isError && (
              <p className="text-sm text-destructive">
                {(create.error as Error).message}
              </p>
            )}
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create team"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Join a team</CardTitle>
          <CardDescription>Use an invite code from a teammate.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              join.mutate({ invite_code: inviteCode });
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="invite-code">Invite code</Label>
              <Input
                id="invite-code"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                required
              />
            </div>
            {join.isError && (
              <p className="text-sm text-destructive">
                {(join.error as Error).message}
              </p>
            )}
            <Button type="submit" disabled={join.isPending}>
              {join.isPending ? "Joining…" : "Join team"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
