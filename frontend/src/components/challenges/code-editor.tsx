"use client";

// The code editor for programming challenges (#449): CodeMirror 6 with a
// deliberately small setup — line numbers, undo history, bracket matching,
// auto-indent and syntax highlighting — rather than the full basicSetup (no
// autocomplete or lint: contest editors stay out of the way). Import it with
// next/dynamic and ssr: false, as the collaborative editor is, so CodeMirror
// only ever loads on the problem page.
//
// Colours come from the design tokens (`hsl(var(--…))`), so the editor follows
// the site palette, custom brand themes and light/dark mode with no raw hex.

import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { cpp } from "@codemirror/lang-cpp";
import { go } from "@codemirror/lang-go";
import { java } from "@codemirror/lang-java";
import { javascript } from "@codemirror/lang-javascript";
import { python } from "@codemirror/lang-python";
import { rust } from "@codemirror/lang-rust";
import {
  bracketMatching,
  HighlightStyle,
  indentOnInput,
  indentUnit,
  syntaxHighlighting,
} from "@codemirror/language";
import { Compartment, EditorState, type Extension } from "@codemirror/state";
import {
  EditorView,
  drawSelection,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  placeholder as placeholderExt,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { useEffect, useRef } from "react";

/** The grammar for a judge language key; plain text for anything unknown (an
 *  admin-defined custom language still edits fine, just without colours). */
export function languageExtension(key: string): Extension {
  if (key.startsWith("python") || key.startsWith("pypy")) return python();
  if (key === "c" || key.startsWith("cpp") || key.startsWith("c++")) return cpp();
  if (key.startsWith("java") && !key.startsWith("javascript")) return java();
  if (key.startsWith("javascript") || key === "node" || key.startsWith("typescript")) return javascript();
  if (key.startsWith("go")) return go();
  if (key.startsWith("rust")) return rust();
  return [];
}

const token = (name: string, alpha?: number) =>
  alpha === undefined ? `hsl(var(--${name}))` : `hsl(var(--${name}) / ${alpha})`;

const theme = EditorView.theme({
  "&": {
    color: token("foreground"),
    backgroundColor: token("background"),
    fontSize: "13px",
    height: "100%",
  },
  ".cm-scroller": { fontFamily: "var(--font-mono, ui-monospace, monospace)", lineHeight: "1.55" },
  ".cm-content": { caretColor: token("foreground"), padding: "8px 0" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: token("foreground") },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
    backgroundColor: token("primary", 0.25),
  },
  ".cm-activeLine": { backgroundColor: token("muted", 0.5) },
  ".cm-gutters": {
    backgroundColor: token("background"),
    color: token("muted-foreground"),
    borderRight: `1px solid ${token("border")}`,
  },
  ".cm-activeLineGutter": { backgroundColor: token("muted", 0.5), color: token("foreground") },
  "&.cm-focused .cm-matchingBracket": { backgroundColor: token("primary", 0.2), outline: "none" },
  ".cm-placeholder": { color: token("muted-foreground") },
});

const highlight = HighlightStyle.define([
  { tag: [tags.keyword, tags.controlKeyword, tags.operatorKeyword, tags.modifier], color: token("primary"), fontWeight: "600" },
  { tag: [tags.string, tags.special(tags.string), tags.character], color: token("success") },
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: token("warning") },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: token("muted-foreground"), fontStyle: "italic" },
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName), tags.definition(tags.function(tags.variableName))], color: token("accent-foreground"), fontWeight: "500" },
  { tag: [tags.typeName, tags.className, tags.namespace], color: token("primary") },
  { tag: [tags.processingInstruction, tags.meta], color: token("destructive") },
  { tag: tags.invalid, color: token("destructive") },
]);

export function CodeEditor({
  value,
  onChange,
  languageKey,
  ariaLabel,
  placeholder,
  readOnly = false,
}: {
  value: string;
  onChange?: (value: string) => void;
  languageKey: string;
  ariaLabel: string;
  placeholder?: string;
  /** View-only (staff reading a submission). */
  readOnly?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const language = useRef(new Compartment());
  // The latest onChange, without rebuilding the editor when the prop changes.
  const changed = useRef(onChange);
  useEffect(() => {
    changed.current = onChange;
  }, [onChange]);

  // Build once. The initial value seeds the document; later external changes
  // (loading a past submission) arrive through the effect below.
  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          highlightActiveLineGutter(),
          history(),
          drawSelection(),
          indentOnInput(),
          bracketMatching(),
          highlightActiveLine(),
          indentUnit.of("    "),
          keymap.of([indentWithTab, ...defaultKeymap, ...historyKeymap]),
          syntaxHighlighting(highlight),
          theme,
          language.current.of(languageExtension(languageKey)),
          placeholder ? placeholderExt(placeholder) : [],
          readOnly ? [EditorState.readOnly.of(true), EditorView.editable.of(false)] : [],
          EditorView.contentAttributes.of({ "aria-label": ariaLabel }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) changed.current?.(update.state.doc.toString());
          }),
        ],
      }),
    });
    view.current = editor;
    return () => {
      editor.destroy();
      view.current = null;
    };
    // Built once per mount by design; see the effects below for updates.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    view.current?.dispatch({
      effects: language.current.reconfigure(languageExtension(languageKey)),
    });
  }, [languageKey]);

  useEffect(() => {
    const editor = view.current;
    if (editor && editor.state.doc.toString() !== value) {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: value } });
    }
  }, [value]);

  return <div ref={host} className="h-full min-h-[18rem] overflow-hidden" />;
}
