"use client";

// The Add-section catalog modal (#330). Replaces the old eye-toggle customize
// UX: instead of every section always rendering and being hidden/shown, a
// manager opens this modal from the customize toolbar and *adds* a section from
// a card list (name + short description) of the sections not already on their
// dashboard. Adding one drops it onto the grid (still in edit mode) to drag and
// resize; the card then leaves the list. The catalog is audience-scoped so
// competitor-personal sections never surface on the manager dashboard (§10.4).

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { catalogFor } from "@/lib/dashboard/layout";
import {
  type DashboardAudience,
  type LayoutEntry,
  WIDGETS,
} from "@/lib/dashboard/registry";

interface AddSectionModalProps {
  audience: DashboardAudience;
  /** The sections currently on the draft dashboard — anything here is excluded
   *  from the catalog (a section is present iff it has an entry). */
  present: LayoutEntry[];
  onAdd: (widgetId: string) => void;
}

export function AddSectionModal({ audience, present, onAdd }: AddSectionModalProps) {
  const t = useTranslations("dashboard");
  // Recomputed each render, so an added section leaves the list immediately
  // (the modal stays open for multiple adds).
  const catalog = catalogFor(audience, present, WIDGETS);

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          {t("grid.addSection")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-[42rem]">
        <DialogHeader>
          <DialogTitle>{t("addSection.title")}</DialogTitle>
          <DialogDescription>{t("addSection.description")}</DialogDescription>
        </DialogHeader>

        {catalog.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {t("addSection.empty")}
          </p>
        ) : (
          <ul className="grid max-h-[60vh] gap-2 overflow-y-auto sm:grid-cols-2">
            {catalog.map((w) => {
              const label = t(`widgetLabels.${w.labelKey}`);
              return (
                <li key={w.id}>
                  <div className="flex h-full flex-col gap-2 rounded-lg border border-border p-3">
                    <div className="grid gap-1">
                      <span className="text-sm font-semibold">{label}</span>
                      <span className="text-xs leading-snug text-muted-foreground">
                        {t(`widgetDescriptions.${w.labelKey}`)}
                      </span>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-auto w-full"
                      aria-label={t("addSection.addNamed", { label })}
                      onClick={() => onAdd(w.id)}
                    >
                      {t("addSection.add")}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="ghost" size="sm">
              {t("addSection.done")}
            </Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
