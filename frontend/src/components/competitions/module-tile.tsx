"use client";

import { useTranslations } from "next-intl";

import { ModuleIcon } from "@/components/app/module-icons";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

// One module as a tile (#502): its glyph, a plain-language name and description,
// and an on/off switch — or "Always on" for a required-core module. Used by
// Settings → Modules and the New competition dialog, so a module reads the same
// in both. The copy comes from messages (moduleCatalog.<id>), falling back to
// the manifest's for a module the UI doesn't know yet.

export interface TileModule {
  id: string;
  name: string;
  description?: string;
  needs_setup?: boolean;
  version?: string;
}

export function ModuleTile({
  module,
  enabled,
  alwaysOn = false,
  pending = false,
  onToggle,
  compact = false,
}: {
  module: TileModule;
  enabled: boolean;
  alwaysOn?: boolean;
  pending?: boolean;
  onToggle?: (next: boolean) => void;
  /** A smaller tile without the description, for the always-on group. */
  compact?: boolean;
}) {
  const t = useTranslations("settings.modules");
  const catalog = useTranslations("moduleCatalog");
  // Dynamic keys: a module id the catalog doesn't carry falls back to the
  // manifest's own text.
  const key = module.id as "ai";
  const name = catalog.has(`${key}.name`) ? catalog(`${key}.name`) : module.name;
  const description = catalog.has(`${key}.description`)
    ? catalog(`${key}.description`)
    : module.description;
  const titleId = `module-tile-${module.id}`;
  const on = alwaysOn || enabled;

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg border p-4 transition-colors",
        on ? "border-border bg-card" : "border-dashed border-border bg-muted/30",
        compact && "p-3",
      )}
      title={module.version ? `${module.id} · v${module.version}` : module.id}
    >
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "flex shrink-0 items-center justify-center rounded-md",
            compact ? "h-7 w-7" : "h-9 w-9",
            on ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
          )}
        >
          <ModuleIcon name={module.id} size={compact ? 14 : 18} />
        </span>
        <div className="min-w-0 flex-1">
          <h3 id={titleId} className="text-sm font-medium leading-snug">
            {name}
          </h3>
          {!compact && description && (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{description}</p>
          )}
        </div>
        {alwaysOn ? (
          <span className="shrink-0 text-xs text-muted-foreground">{t("alwaysOn")}</span>
        ) : (
          <Switch
            checked={enabled}
            disabled={pending || !onToggle}
            onCheckedChange={(next) => onToggle?.(next)}
            aria-labelledby={titleId}
          />
        )}
      </div>
      {module.needs_setup && (
        <p className="rounded-md bg-warning/10 px-2.5 py-1.5 text-xs text-foreground">
          {t("needsSetup")}
        </p>
      )}
    </div>
  );
}
