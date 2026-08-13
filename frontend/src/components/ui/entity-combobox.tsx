"use client";

// A name-autocomplete that stores an id (ARCHITECTURE §9 tokens). Admins/judges
// pick a team or user by name from a filter-as-you-type dropdown instead of
// pasting a long id. The committed value is always the option's id; the input
// shows the matching label (or the raw id as a fallback if the option list
// hasn't loaded a match). Dependency-free — no combobox library in the stack.
//
// Follows the WAI-ARIA combobox (listbox popup) pattern: focus stays on the
// input, arrow keys move a highlighted option via aria-activedescendant, and
// Enter commits it — so the control is fully keyboard-operable, not mouse-only.

import * as React from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface ComboOption {
  value: string;
  label: string;
  hint?: string; // secondary line, e.g. an email
}

export function EntityCombobox({
  options,
  value,
  onChange,
  id,
  placeholder,
  disabled,
  emptyText = "No matches",
  freeText = false,
  className,
}: {
  options: ComboOption[];
  value: string;
  onChange: (value: string) => void;
  id?: string;
  placeholder?: string;
  disabled?: boolean;
  emptyText?: string;
  // Free-text mode: the value is whatever's typed (not required to match an
  // option) — options are shown as suggestions only. Used for the automation
  // condition field picker, where the catalog's fields are suggestions but
  // arbitrary field paths are still valid input.
  freeText?: boolean;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [activeIndex, setActiveIndex] = React.useState(0);
  const ref = React.useRef<HTMLDivElement>(null);
  const reactId = React.useId();
  const listId = `${id ?? reactId}-listbox`;
  const optionId = (i: number) => `${listId}-opt-${i}`;

  const selected = options.find((o) => o.value === value);
  // Closed: show the selected option's label — so a condition field reads
  // "Minutes remaining", not the raw `minutes_remaining` key it stores — falling
  // back to the raw value when it resolves to no option (a free-text field path,
  // or an id whose option list hasn't loaded yet). Open: show what's being typed
  // — in free-text mode the raw value itself (the field key is edited directly),
  // otherwise the filter query.
  const displayValue = open
    ? freeText
      ? value
      : query
    : (selected?.label ?? value);

  const filterQuery = freeText ? value : query;
  const filtered = React.useMemo(() => {
    const q = filterQuery.trim().toLowerCase();
    const match = q
      ? options.filter(
          (o) =>
            o.label.toLowerCase().includes(q) ||
            o.value.toLowerCase().includes(q) ||
            o.hint?.toLowerCase().includes(q),
        )
      : options;
    return match.slice(0, 50); // cap the rendered list
  }, [options, filterQuery]);

  // Keep the highlighted option in range as the filtered list shrinks/grows —
  // derived by clamping at read time, so there's no state to re-sync.
  const active = Math.min(activeIndex, Math.max(0, filtered.length - 1));

  React.useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  function choose(v: string) {
    onChange(v);
    setOpen(false);
    if (!freeText) setQuery("");
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      setActiveIndex(Math.min(active + 1, filtered.length - 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex(Math.max(active - 1, 0));
      return;
    }
    if (e.key === "Enter") {
      if (open && filtered[active]) {
        e.preventDefault();
        choose(filtered[active].value);
      } else if (open && freeText) {
        // Free-text with no matching suggestion — the typed value is already
        // committed via onChange, so Enter just dismisses the suggestion list.
        setOpen(false);
      }
    }
  }

  return (
    <div ref={ref} className="relative">
      <Input
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          open && filtered[active] ? optionId(active) : undefined
        }
        value={displayValue}
        disabled={disabled}
        placeholder={placeholder}
        autoComplete="off"
        onFocus={() => {
          setOpen(true);
          if (!freeText) setQuery("");
          setActiveIndex(0);
        }}
        onChange={(e) => {
          setOpen(true);
          if (freeText) {
            onChange(e.target.value);
          } else {
            setQuery(e.target.value);
          }
          setActiveIndex(0);
        }}
        onKeyDown={onKeyDown}
        className={cn(value && !open ? "pr-8" : undefined, className)}
      />
      {value && !open && !disabled && (
        <button
          type="button"
          aria-label="Clear"
          onMouseDown={(e) => {
            e.preventDefault();
            onChange("");
            setQuery("");
          }}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        >
          ×
        </button>
      )}
      {open && (
        <ul
          id={listId}
          role="listbox"
          className="anim-drop absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-md border border-border bg-popover text-popover-foreground shadow-lg"
        >
          {filtered.length === 0 ? (
            <li className="px-3 py-2 text-sm text-muted-foreground">{emptyText}</li>
          ) : (
            filtered.map((o, i) => (
              <li
                key={o.value}
                id={optionId(i)}
                role="option"
                aria-selected={o.value === value}
                // mousedown (not click) so it fires before the input blur.
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(o.value);
                }}
                onMouseEnter={() => setActiveIndex(i)}
                className={cn(
                  "flex cursor-pointer flex-col items-start px-3 py-1.5 text-left text-sm",
                  i === active ? "bg-accent" : "hover:bg-accent",
                  o.value === value && "bg-accent/60",
                )}
              >
                <span>{o.label}</span>
                {o.hint && <span className="text-xs text-muted-foreground">{o.hint}</span>}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
