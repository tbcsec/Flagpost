// Side-effect CSS imports (global stylesheets, @fontsource) carry no types.
// Next.js declares these ambiently for its own build, but TypeScript 6.0
// tightened side-effect-import resolution (TS2882) and no longer accepts a
// bare `import "./x.css"` without an explicit ambient declaration.
declare module "*.css";
