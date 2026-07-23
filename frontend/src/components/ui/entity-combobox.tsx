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
}: {
  options: ComboOption[];
  value: string;
  onChange: (value: string) => void;
  id?: string;
  placeholder?: string;
  disabled?: boolean;
  emptyText?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [activeIndex, setActiveIndex] = React.useState(0);
  const ref = React.useRef<HTMLDivElement>(null);
  const reactId = React.useId();
  const listId = `${id ?? reactId}-listbox`;
  const optionId = (i: number) => `${listId}-opt-${i}`;

  const selected = options.find((o) => o.value === value);
  // Closed: show the selected label (or the raw id if unresolved). Open: show
  // what's being typed to filter.
  const displayValue = open ? query : selected?.label ?? value;

  const filtered = React.useMemo(() => {
    const q = query.trim().toLowerCase();
    const match = q
      ? options.filter(
          (o) =>
            o.label.toLowerCase().includes(q) || o.hint?.toLowerCase().includes(q),
        )
      : options;
    return match.slice(0, 50); // cap the rendered list
  }, [options, query]);

  // Keep the highlighted option in range as the filtered list shrinks/grows.
  React.useEffect(() => {
    setActiveIndex((i) => Math.min(i, Math.max(0, filtered.length - 1)));
  }, [filtered.length]);

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
    setQuery("");
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
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
      return;
    }
    if (e.key === "Enter") {
      if (open && filtered[activeIndex]) {
        e.preventDefault();
        choose(filtered[activeIndex].value);
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
          open && filtered[activeIndex] ? optionId(activeIndex) : undefined
        }
        value={displayValue}
        disabled={disabled}
        placeholder={placeholder}
        autoComplete="off"
        onFocus={() => {
          setOpen(true);
          setQuery("");
          setActiveIndex(0);
        }}
        onChange={(e) => {
          setOpen(true);
          setQuery(e.target.value);
          setActiveIndex(0);
        }}
        onKeyDown={onKeyDown}
        className={value && !open ? "pr-8" : undefined}
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
          className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-md border border-border bg-popover text-popover-foreground shadow-lg"
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
                  i === activeIndex ? "bg-accent" : "hover:bg-accent",
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
