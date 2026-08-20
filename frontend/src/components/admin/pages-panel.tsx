"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { PAGE_ICON_NAMES, PageIcon } from "@/components/app/page-icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { Select } from "@/components/ui/select";
import { SkeletonCards } from "@/components/ui/skeleton";
import {
  useAdminPages,
  useCreatePage,
  useDeletePage,
  useReorderPages,
  useUpdatePage,
} from "@/lib/hooks/use-pages";
import type { AdminPage, PageVisibility, PageWrite, RichTextDoc } from "@/lib/types";
import { cn } from "@/lib/utils";

// Admin manager for custom pages (#198, ADR-0034).
//
// Authoring only — the reader-facing rendering lives at /p/[slug]. A page's
// *content* is operator data and never goes through the message catalog; the
// chrome around it does (this is a new surface, so it's born extracted).

const EMPTY: PageWrite = {
  slug: "",
  title: "",
  content: null,
  icon: "document",
  nav_order: 0,
  visibility: "authenticated",
  draft: true,
};

/** Derive a URL-safe slug from a title, matching the backend's pattern so the
 *  suggestion is always something the API will accept. */
function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

function IconPicker({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (name: string) => void;
  label: string;
}) {
  return (
    <div className="grid gap-2">
      <Label>{label}</Label>
      <div className="flex flex-wrap gap-1">
        {PAGE_ICON_NAMES.map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => onChange(name)}
            aria-label={name}
            aria-pressed={value === name}
            title={name}
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-md border transition-colors",
              value === name
                ? "border-primary bg-accent text-foreground"
                : "border-border text-muted-foreground hover:border-primary/50 hover:text-foreground",
            )}
          >
            <PageIcon name={name} />
          </button>
        ))}
      </div>
    </div>
  );
}

function PageForm({
  editing,
  onDone,
}: {
  editing: AdminPage | null;
  onDone: () => void;
}) {
  const t = useTranslations("pages");
  const create = useCreatePage();
  const update = useUpdatePage();
  const [form, setForm] = useState<PageWrite>(
    editing
      ? {
          slug: editing.slug,
          title: editing.title,
          content: editing.content,
          icon: editing.icon,
          nav_order: editing.nav_order,
          visibility: editing.visibility,
          draft: editing.draft,
        }
      : EMPTY,
  );
  // Only auto-fill the slug while creating, and only until the author edits it:
  // changing a live page's slug breaks every link anyone has shared to it, so
  // it must never follow a title edit silently.
  const [slugTouched, setSlugTouched] = useState(Boolean(editing));
  const pending = create.isPending || update.isPending;
  const error = (create.error ?? update.error) as Error | null;

  function set<K extends keyof PageWrite>(key: K, value: PageWrite[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const payload: PageWrite = { ...form, slug: form.slug || slugify(form.title) };
    const onSuccess = () => onDone();
    if (editing) update.mutate({ id: editing.id, ...payload }, { onSuccess });
    else create.mutate(payload, { onSuccess });
  }

  return (
    <Card>
      <CardContent className="py-4">
        <form onSubmit={onSubmit} className="grid max-w-2xl gap-4">
          <div className="grid gap-2">
            <Label htmlFor="page-title">{t("form.title")}</Label>
            <Input
              id="page-title"
              value={form.title}
              onChange={(e) => {
                set("title", e.target.value);
                if (!slugTouched) set("slug", slugify(e.target.value));
              }}
              required
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor="page-slug">{t("form.slug")}</Label>
            <Input
              id="page-slug"
              value={form.slug}
              onChange={(e) => {
                setSlugTouched(true);
                set("slug", e.target.value);
              }}
              required
            />
            <p className="text-xs text-muted-foreground">
              {t("form.slugHelp", { url: `/p/${form.slug || "…"}` })}
            </p>
          </div>

          <IconPicker
            value={form.icon}
            onChange={(name) => set("icon", name)}
            label={t("form.icon")}
          />

          <div className="grid gap-2">
            <Label>{t("form.content")}</Label>
            <RichTextEditor
              value={(form.content ?? {}) as RichTextDoc}
              onChange={(doc) => set("content", doc)}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="page-visibility">{t("form.visibility")}</Label>
              <Select
                id="page-visibility"
                value={form.visibility}
                onChange={(e) =>
                  set("visibility", e.target.value as PageVisibility)
                }
              >
                <option value="authenticated">{t("visibility.authenticated")}</option>
                <option value="public">{t("visibility.public")}</option>
              </Select>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="page-status">{t("form.status")}</Label>
              <Select
                id="page-status"
                value={form.draft ? "draft" : "published"}
                onChange={(e) => set("draft", e.target.value === "draft")}
              >
                <option value="draft">{t("status.draft")}</option>
                <option value="published">{t("status.published")}</option>
              </Select>
            </div>
          </div>

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error.message}
            </p>
          )}

          <div className="flex gap-2">
            <Button type="submit" disabled={pending}>
              {editing ? t("actions.save") : t("actions.create")}
            </Button>
            <Button type="button" variant="outline" onClick={onDone}>
              {t("actions.cancel")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

export function PagesPanel() {
  const t = useTranslations("pages");
  const { data, isLoading } = useAdminPages();
  const remove = useDeletePage();
  const reorder = useReorderPages();
  const confirm = useConfirm();
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<AdminPage | null>(null);

  const pages = data ?? [];

  /** Move a page one slot and persist the whole resulting order — a whole-list
   *  replace, so a lost request can't leave a half-applied ordering. */
  function move(index: number, delta: number) {
    const next = [...pages];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    reorder.mutate(next);
  }

  async function onDelete(page: AdminPage) {
    const ok = await confirm({
      title: t("delete.title"),
      description: t("delete.description", { title: page.title }),
      confirmLabel: t("actions.delete"),
      destructive: true,
    });
    if (ok) remove.mutate(page.id);
  }

  if (adding || editing) {
    return (
      <PageForm
        key={editing?.id ?? "new"}
        editing={editing}
        onDone={() => {
          setAdding(false);
          setEditing(null);
        }}
      />
    );
  }

  return (
    <div className="grid gap-3">
      <div>
        <Button onClick={() => setAdding(true)}>{t("actions.add")}</Button>
      </div>

      {isLoading ? (
        <SkeletonCards count={2} />
      ) : pages.length === 0 ? (
        <EmptyState title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <Card>
          <CardContent className="divide-y divide-border p-0">
            {pages.map((page, index) => (
              <div
                key={page.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3"
              >
                <PageIcon name={page.icon} className="shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{page.title}</span>
                    {page.draft && <Badge variant="outline">{t("status.draft")}</Badge>}
                    {page.visibility === "public" && (
                      <Badge variant="outline">{t("visibility.public")}</Badge>
                    )}
                  </div>
                  <p className="font-mono text-xs text-muted-foreground">
                    /p/{page.slug}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {/* Arrows rather than drag-and-drop: the list is short, and
                      arrows stay keyboard- and screen-reader-operable. */}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={t("actions.moveUp")}
                    disabled={index === 0 || reorder.isPending}
                    onClick={() => move(index, -1)}
                  >
                    ↑
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={t("actions.moveDown")}
                    disabled={index === pages.length - 1 || reorder.isPending}
                    onClick={() => move(index, 1)}
                  >
                    ↓
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setEditing(page)}
                  >
                    {t("actions.edit")}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => onDelete(page)}
                  >
                    {t("actions.delete")}
                  </Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
