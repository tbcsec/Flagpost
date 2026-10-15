// Which competition sidebar entries a viewer sees. Pure, so the rules are
// unit-tested without rendering the whole shell.

export interface NavRule {
  key: string;
  /** Only for a Judge/organiser of the active competition. */
  manage?: boolean;
  /** Tied to an optional module (§11.3): hidden when it's off here. */
  module?: string;
  /** Gated on one specific grant. */
  permission?: string;
}

export interface NavViewer {
  ready: boolean;
  inLobby: boolean;
  canManageActiveCompetition: boolean;
  has: (permission: string) => boolean;
}

/** Whether to ask if the competition has a programming problem — only for
 *  someone who could open the jury console, with the code judge on here. */
export function shouldCheckProgrammingProblems(
  viewer: NavViewer,
  enabledModules: string[] | undefined,
): boolean {
  return (
    viewer.ready &&
    !viewer.inLobby &&
    viewer.has("judging_view") &&
    Boolean(enabledModules?.includes("judge"))
  );
}

export function visibleCompNav<T extends NavRule>(
  items: T[],
  viewer: NavViewer,
  // Undefined while loading: module items stay visible until it arrives —
  // modules are on by default, so hiding-then-showing would flicker more than
  // the rare disabled case.
  enabledModules: string[] | undefined,
  // Undefined until known (or not asked).
  hasProgrammingProblems: boolean | undefined,
): T[] {
  return items.filter((item) => {
    if (item.manage && !viewer.canManageActiveCompetition) return false;
    if (item.permission && !viewer.has(item.permission)) return false;
    if (item.module && enabledModules && !enabledModules.includes(item.module)) return false;
    // Judging earns its slot only once there's a programming problem — the
    // module being on isn't enough (it's on by default everywhere). Hidden
    // until known, the opposite of the module rule: most competitions have
    // none, so showing then hiding would be the common flicker.
    if (item.key === "judging" && hasProgrammingProblems !== true) return false;
    return true;
  });
}
