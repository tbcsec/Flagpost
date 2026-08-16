// Type-side wiring for next-intl: `t("...")` keys are checked against the
// English source messages, and `useLocale()` returns our Locale union. This
// file is never imported — the module augmentation applies project-wide.
import type messages from "../../messages/en.json";

import type { Locale } from "./config";

declare module "next-intl" {
  interface AppConfig {
    Locale: Locale;
    Messages: typeof messages;
  }
}
