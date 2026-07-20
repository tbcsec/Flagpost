"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DIRECTORY_USERS } from "@/lib/placeholder-data";

const ROLE_LABEL = { admin: "Administrator", judge: "Judge", participant: "Participant" };
const ROLE_VARIANT = { admin: "success", judge: "secondary", participant: "outline" } as const;

// Admin → Users. There's no user-directory / create / ban endpoint yet
// (registration and the seeded admin exist, but no admin user-management API),
// so this is placeholder.
export default function AdminUsersPage() {
  return (
    <>
      <SectionHeader title="Admin — Users" subtitle="Global — platform-wide, not scoped to a competition" />
      <NotWiredNote>User management (directory, create, ban) has no backend yet — rows are placeholder.</NotWiredNote>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Users</CardTitle>
            <CardDescription>{DIRECTORY_USERS.length} accounts across the platform</CardDescription>
          </div>
          <Button disabled>Create account</Button>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {DIRECTORY_USERS.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">{u.name}</TableCell>
                  <TableCell className="text-muted-foreground">{u.email}</TableCell>
                  <TableCell>
                    <Badge variant={ROLE_VARIANT[u.role]}>{ROLE_LABEL[u.role]}</Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={u.status === "Banned" ? "destructive" : "muted"}>{u.status}</Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right">
                    <Button variant="ghost" size="sm" className="text-destructive" disabled>
                      {u.status === "Banned" ? "Unban" : "Ban"}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}
