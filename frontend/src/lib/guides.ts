// The bundled user-guide PDFs (docs/guides/, deployed by `build.py --deploy`).
// Shipping them in the image keeps airgapped installs documented and pins each
// install's guides to its own version; docs.flagpost.io carries latest.
export const GUIDE_PDFS = {
  competitor: "/guides/flagpost-competitor-guide.pdf",
  judge: "/guides/flagpost-judge-guide.pdf",
  admin: "/guides/flagpost-admin-guide.pdf",
} as const;
