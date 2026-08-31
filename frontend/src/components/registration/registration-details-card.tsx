"use client";

// An individual competitor's own custom registration answers (#350) — review
// and edit them after joining. Renders nothing when the competition has no
// fields. Team-mode answers belong to the team and are edited in the team panel.

import { useState } from "react";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  useMyRegistrationValues,
  usePutMyRegistrationValues,
  useRegistrationFields,
} from "@/lib/hooks/use-registration-fields";
import type { RegistrationValues } from "@/lib/types";
import { toast } from "@/stores/toast";

import {
  RegistrationFieldsForm,
  missingRequired,
} from "./registration-fields-form";

export function RegistrationDetailsCard({
  competitionId,
}: {
  competitionId: string;
}) {
  const t = useTranslations("registration.details");
  const { data: fields } = useRegistrationFields(competitionId);
  const { data: mine } = useMyRegistrationValues(competitionId);
  const save = usePutMyRegistrationValues(competitionId);
  const [values, setValues] = useState<RegistrationValues>({});
  // Seed the editable copy from the server once, the adjust-during-render
  // pattern (a setState in an effect trips react-hooks/set-state-in-effect).
  const [seeded, setSeeded] = useState(false);
  if (mine && !seeded) {
    setSeeded(true);
    setValues(mine.values);
  }

  if (!fields || fields.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <RegistrationFieldsForm
          fields={fields}
          values={values}
          onChange={setValues}
          idPrefix="details"
        />
        <Button
          className="w-fit"
          onClick={() =>
            save.mutate(values, {
              onSuccess: () => toast(t("saved"), { variant: "success" }),
              onError: (e) =>
                toast(t("error"), {
                  description: (e as Error).message,
                  variant: "destructive",
                }),
            })
          }
          disabled={save.isPending || missingRequired(fields, values)}
        >
          {save.isPending ? t("saving") : t("save")}
        </Button>
      </CardContent>
    </Card>
  );
}
