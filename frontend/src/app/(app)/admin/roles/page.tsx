"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PERMISSION_CATEGORIES } from "@/lib/placeholder-data";

// Admin → Roles. The three built-in roles and permissions-as-data model are
// real on the backend (Tier 0), but there's no endpoint to read/edit role
// permissions, and the custom-role editor UI is Tier 2 (#21). Placeholder.
const ROLE_CARDS = [
  { name: "Administrator", tag: "System role — full access" },
  { name: "Judge", tag: "System role — per-competition operator" },
  { name: "Participant", tag: "System role — competitor" },
];

export default function AdminRolesPage() {
  return (
    <>
      <SectionHeader title="Admin — Roles" subtitle="Global — platform-wide, not scoped to a competition" />
      <NotWiredNote>
        The role/permission model is real on the backend, but there&apos;s no
        read/edit endpoint and the custom-role editor is Tier&nbsp;2. Toggles here
        are inert.
      </NotWiredNote>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {ROLE_CARDS.map((rc) => (
          <Card key={rc.name}>
            <CardHeader>
              <CardTitle>{rc.name}</CardTitle>
              <CardDescription>{rc.tag}</CardDescription>
            </CardHeader>
            <CardContent>
              <Button variant="outline" size="sm" disabled>Clone</Button>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Permissions — Judge</CardTitle>
          <Button variant="outline" size="sm" disabled>New custom role</Button>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            {PERMISSION_CATEGORIES.map((cat) => (
              <div key={cat}>
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {cat}
                </div>
                <div className="grid gap-1.5">
                  {["View", "Create", "Edit", "Delete"].map((action) => (
                    <label key={action} className="flex items-center gap-2 text-[13px]">
                      <input type="checkbox" defaultChecked={action !== "Delete"} disabled />
                      {action}
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </>
  );
}
