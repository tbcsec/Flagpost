"use client";

// Collects a competition's custom registration fields (#350) before an
// individual join. Opened when the lobby's Join is clicked; if the competition
// has no fields it proceeds immediately (nothing shown), otherwise it presents
// the form and hands the answers back so the caller can run its join flow.

import { useEffect, useRef, useState } from "react";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useRegistrationFields } from "@/lib/hooks/use-registration-fields";
import type { RegistrationValues } from "@/lib/types";

import {
  RegistrationFieldsForm,
  missingRequired,
} from "./registration-fields-form";

export function JoinFieldsDialog({
  competitionId,
  competitionName,
  onSubmit,
  onCancel,
}: {
  competitionId: string;
  competitionName: string;
  onSubmit: (values: RegistrationValues) => void;
  onCancel: () => void;
}) {
  const t = useTranslations("registration.join");
  const { data: fields } = useRegistrationFields(competitionId);
  const [values, setValues] = useState<RegistrationValues>({});
  const proceeded = useRef(false);

  // No fields to collect → proceed straight to the join, once.
  useEffect(() => {
    if (fields && fields.length === 0 && !proceeded.current) {
      proceeded.current = true;
      onSubmit({});
    }
  }, [fields, onSubmit]);

  if (!fields || fields.length === 0) return null;

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onCancel();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("title", { name: competitionName })}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSubmit(values);
          }}
          className="grid gap-4"
        >
          <RegistrationFieldsForm
            fields={fields}
            values={values}
            onChange={setValues}
            idPrefix="join"
          />
          <DialogFooter>
            <Button type="submit" disabled={missingRequired(fields, values)}>
              {t("submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
