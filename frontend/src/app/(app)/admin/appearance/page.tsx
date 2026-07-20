"use client";

import { NotWiredNote, SectionHeader } from "@/components/app/section-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

// Admin → Appearance. Site-wide branding. No settings endpoint exists yet, so
// the form is present but doesn't persist. (Per-competition theming is Tier 2.)
export default function AdminAppearancePage() {
  return (
    <>
      <SectionHeader title="Admin — Appearance" subtitle="Global — platform-wide, not scoped to a competition" />
      <div className="grid max-w-xl gap-5">
        <NotWiredNote>Site settings have no persistence endpoint yet — this form doesn&apos;t save.</NotWiredNote>
        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
            <CardDescription>Site-wide — competitions do not have individual branding</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="pn">Platform name</Label>
                <Input id="pn" defaultValue="Flagpost" disabled />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="dt">Default palette</Label>
                <Select id="dt" defaultValue="dark" disabled>
                  <option value="dark">Dark</option>
                  <option value="light">Light</option>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>
        <Button className="w-fit" disabled>Save changes</Button>
      </div>
    </>
  );
}
