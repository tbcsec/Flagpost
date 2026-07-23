"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
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
  useJoinRequests,
  useJoinTeam,
  useLeaveTeam,
  useMyTeam,
  useReviewJoinRequest,
  useTeams,
  useUpdateMyTeam,
} from "@/lib/hooks/use-teams";
import { useAuthStore } from "@/stores/auth";
import { toast } from "@/stores/toast";

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
  const confirm = useConfirm();

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

        <JoinRequests competitionId={competitionId} team={team} />

        <TeamProfile competitionId={competitionId} team={team} />

        <div className="flex items-center gap-3">
          <Button
            variant="destructive"
            onClick={async () => {
              if (
                !(await confirm({
                  title: "Leave this team?",
                  description: "You'll lose access to the team's shared progress. You can join or create another team while registration is open.",
                  confirmLabel: "Leave team",
                }))
              ) {
                return;
              }
              leave.mutate(undefined, {
                onSuccess: () => toast("Left team", { variant: "success" }),
              });
            }}
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

// Team profile (affiliation/country/website) — editable by the captain, shown
// read-only to everyone else.
function TeamProfile({
  competitionId,
  team,
}: {
  competitionId: string;
  team: NonNullable<ReturnType<typeof useMyTeam>["data"]>;
}) {
  const userId = useAuthStore((s) => s.user?.id);
  const amCaptain = team.members.some((m) => m.user_id === userId && m.is_captain);
  const update = useUpdateMyTeam(competitionId);
  const [affiliation, setAffiliation] = useState(team.affiliation ?? "");
  const [country, setCountry] = useState(team.country ?? "");
  const [website, setWebsite] = useState(team.website ?? "");
  const [approval, setApproval] = useState(team.approval_required);

  if (!amCaptain) {
    if (!team.affiliation && !team.country && !team.website) return null;
    return (
      <div className="grid gap-0.5 text-sm text-muted-foreground">
        {team.affiliation && <div>Affiliation: {team.affiliation}</div>}
        {team.country && <div>Country: {team.country}</div>}
        {team.website && <div>Website: {team.website}</div>}
      </div>
    );
  }

  const dirty =
    affiliation !== (team.affiliation ?? "") ||
    country !== (team.country ?? "") ||
    website !== (team.website ?? "") ||
    approval !== team.approval_required;

  function onSave() {
    update.mutate(
      {
        affiliation: affiliation.trim() || null,
        country: country.trim() || null,
        website: website.trim() || null,
        approval_required: approval,
      },
      { onSuccess: () => toast("Team profile saved", { variant: "success" }) },
    );
  }

  return (
    <div className="grid gap-2">
      <Label className="text-xs uppercase tracking-wide text-muted-foreground">
        Team profile
      </Label>
      <div className="grid gap-2 sm:grid-cols-3">
        <Input
          placeholder="Affiliation"
          value={affiliation}
          onChange={(e) => setAffiliation(e.target.value)}
        />
        <Input
          placeholder="Country"
          value={country}
          onChange={(e) => setCountry(e.target.value)}
        />
        <Input
          placeholder="Website"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
        />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          className="h-4 w-4 rounded border-border"
          style={{ accentColor: "hsl(var(--primary))" }}
          checked={approval}
          onChange={(e) => setApproval(e.target.checked)}
        />
        Require captain approval to join
      </label>
      <Button
        variant="outline"
        size="sm"
        className="w-fit"
        onClick={onSave}
        disabled={!dirty || update.isPending}
      >
        {update.isPending ? "Saving…" : "Save profile"}
      </Button>
    </div>
  );
}

// Pending join requests — only rendered for the captain of an approval-required
// team; approve adds the member, reject discards the request.
function JoinRequests({
  competitionId,
  team,
}: {
  competitionId: string;
  team: NonNullable<ReturnType<typeof useMyTeam>["data"]>;
}) {
  const userId = useAuthStore((s) => s.user?.id);
  const amCaptain = team.members.some((m) => m.user_id === userId && m.is_captain);
  const { data: requests } = useJoinRequests(competitionId, amCaptain);
  const review = useReviewJoinRequest(competitionId);

  if (!amCaptain || !requests || requests.length === 0) return null;

  return (
    <div className="grid gap-2">
      <Label className="text-xs uppercase tracking-wide text-muted-foreground">
        Join requests ({requests.length})
      </Label>
      <ul className="grid gap-1.5">
        {requests.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-2 text-sm">
            <span>{r.display_name}</span>
            <span className="flex gap-1.5">
              <Button
                size="sm"
                variant="outline"
                onClick={() => review.mutate({ id: r.id, approve: true })}
                disabled={review.isPending}
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => review.mutate({ id: r.id, approve: false })}
                disabled={review.isPending}
              >
                Reject
              </Button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function JoinOrCreate({ competitionId }: { competitionId: string }) {
  const create = useCreateTeam(competitionId);
  const join = useJoinTeam(competitionId);
  const [name, setName] = useState("");
  const [approvalRequired, setApprovalRequired] = useState(false);
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
              create.mutate(
                { name, approval_required: approvalRequired },
                { onSuccess: () => toast(`Created ${name}`, { variant: "success" }) },
              );
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
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-border"
                style={{ accentColor: "hsl(var(--primary))" }}
                checked={approvalRequired}
                onChange={(e) => setApprovalRequired(e.target.checked)}
              />
              Require captain approval to join
            </label>
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
              join.mutate(
                { invite_code: inviteCode },
                {
                  onSuccess: (res) =>
                    toast(
                      res.pending
                        ? "Request sent — awaiting captain approval"
                        : "Joined team",
                      { variant: "success" },
                    ),
                },
              );
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
