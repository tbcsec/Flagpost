"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

// Admin → Site settings. AI config, SMTP, registration policy and site-wide
// notices. None of these have backends yet (AI and SSO are explicitly deferred;
// SMTP/registration policy aren't built), so the whole surface is placeholder.
export default function AdminSettingsPage() {
  return (
    <>
      <SectionHeader title="Admin — Site settings" subtitle="Global — platform-wide, not scoped to a competition" />
      <div className="grid max-w-xl gap-5">
        <NotWiredNote>
          AI, SMTP, registration policy and site-wide notices aren&apos;t built
          (AI is explicitly deferred). Nothing here persists.
        </NotWiredNote>

        <Card>
          <CardHeader>
            <CardTitle>AI configuration</CardTitle>
            <CardDescription>Deferred past MVP</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2">
              <Label htmlFor="aik">API key</Label>
              <Input id="aik" type="password" placeholder="sk-…" disabled />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>SMTP configuration</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="sh">Host</Label>
                <Input id="sh" placeholder="smtp.flagpost.dev" disabled />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="sp">Port</Label>
                <Input id="sp" placeholder="587" disabled />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Registration</CardTitle>
          </CardHeader>
          <CardContent>
            <Select defaultValue="open" disabled>
              <option value="open">Open registration</option>
              <option value="invite">Invite-only</option>
            </Select>
          </CardContent>
        </Card>

        <Button className="w-fit" disabled>Save changes</Button>
      </div>
    </>
  );
}
