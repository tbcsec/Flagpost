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
  /** Earns its slot only once the module is of real use here (#511): the key
   *  into the in-use map — `judge` (a programming problem exists), `ai`,
   *  `instances` (switched on site-wide, or data already here). */
  inUse?: string;
}

/** Whether each in-use key currently applies; undefined until known. */
export type InUseMap = Partial<Record<string, boolean | undefined>>;

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

/** Whether to ask which inert modules are of use — only for someone who could
 *  open one of their pages, with that module on here. */
export function shouldCheckModulesInUse(
  viewer: NavViewer,
  enabledModules: string[] | undefined,
): boolean {
  if (!viewer.ready || viewer.inLobby || !enabledModules) return false;
  return (
    (viewer.has("ai_view_transcripts") && enabledModules.includes("ai")) ||
    (viewer.has("instance_view") && enabledModules.includes("instances"))
  );
}

export function visibleCompNav<T extends NavRule>(
  items: T[],
  viewer: NavViewer,
  // Undefined while loading: module items stay visible until it arrives —
  // modules are on by default, so hiding-then-showing would flicker more than
  // the rare disabled case.
  enabledModules: string[] | undefined,
  // Per in-use key, undefined until known (or not asked).
  inUse: InUseMap,
): T[] {
  return items.filter((item) => {
    if (item.manage && !viewer.canManageActiveCompetition) return false;
    if (item.permission && !viewer.has(item.permission)) return false;
    if (item.module && enabledModules && !enabledModules.includes(item.module)) return false;
    // An inert module's entry earns its slot only once the module is of real
    // use here — being on isn't enough (every optional module is on by
    // default). Hidden until known, the opposite of the module rule: "not in
    // use" is the common answer, so showing then hiding would be the usual
    // flicker. Judging: a programming problem exists; AI transcripts and
    // Instances: switched on site-wide, or data already here (#511).
    if (item.inUse && inUse[item.inUse] !== true) return false;
    return true;
  });
}

/** Whether a lobby-state viewer on `pathname` should be sent to /lobby. They
 *  keep the lobby itself and their profile — and, for a narrow global delegate
 *  (#477), the Admin pages their grant opens: being in the lobby is about
 *  competition access, not about the global section. */
export function shouldRedirectToLobby(viewer: {
  showLobby: boolean;
  pathname: string;
  isAdmin: boolean;
}): boolean {
  if (!viewer.showLobby) return false;
  if (viewer.pathname === "/lobby" || viewer.pathname === "/profile") return false;
  if (viewer.isAdmin && viewer.pathname.startsWith("/admin")) return false;
  return true;
}

/** Whether `pathname` is a page about the active competition — everything in
 *  the app shell except the global Admin section, the lobby and your profile.
 *  On a competition the viewer hasn't joined, these show a join panel (#478). */
export function isCompetitionScopedPath(pathname: string): boolean {
  if (pathname === "/admin" || pathname.startsWith("/admin/")) return false;
  if (pathname === "/lobby" || pathname === "/profile") return false;
  return true;
}

/** Whether to show the join panel in place of the page: the viewer has some
 *  competition access (not the lobby), but not to the active competition. */
export function shouldShowJoinPanel(viewer: {
  ready: boolean;
  inLobby: boolean;
  memberOfActive: boolean;
  hasActiveCompetition: boolean;
  pathname: string;
}): boolean {
  return (
    viewer.ready &&
    !viewer.inLobby &&
    viewer.hasActiveCompetition &&
    !viewer.memberOfActive &&
    isCompetitionScopedPath(viewer.pathname)
  );
}

/** The switcher's entries: split into joined and open-to-join groups for a
 *  viewer who isn't in every competition, once there's one of each (#478). */
export function switcherGroups<T extends { id: string }>(
  competitions: T[],
  viewer: { ready: boolean; seesEveryCompetition: boolean; isMemberOf: (id: string) => boolean },
): { joined: T[]; joinable: T[] } | null {
  if (!viewer.ready || viewer.seesEveryCompetition) return null;
  const joined = competitions.filter((c) => viewer.isMemberOf(c.id));
  const joinable = competitions.filter((c) => !viewer.isMemberOf(c.id));
  return joined.length > 0 && joinable.length > 0 ? { joined, joinable } : null;
}
