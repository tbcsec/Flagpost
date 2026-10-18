"use client";

import { useEffect } from "react";

import { CertificateReleasedModal } from "@/components/certificates/certificate-released-modal";
import { useMyCertificateAvailability } from "@/lib/hooks/use-certificates";
import { useActiveCompetition } from "@/lib/hooks/use-competitions";
import { useEnabledModules } from "@/lib/hooks/use-modules";
import { useAccess } from "@/lib/hooks/use-permissions";
import { useCertificateModal } from "@/stores/certificate-ui";

/** Mounted once in the app shell. When the active competition has just released a
 *  certificate this user can download, it fires the one-time celebratory modal.
 *  Quiet when the module is off or nothing is available. */
export function CertificateReleaseWatcher() {
  const { competitionId } = useActiveCompetition();
  const access = useAccess();
  const cid = competitionId ?? "";
  // Nothing to ask about a competition you haven't joined (#478).
  const member = Boolean(cid) && access.memberOfActive;
  const enabled = useEnabledModules(cid, member);
  const moduleOn = !enabled.data || enabled.data.includes("certificates");
  const availability = useMyCertificateAvailability(cid, member && moduleOn);
  const { active, maybeShow, dismiss } = useCertificateModal();

  useEffect(() => {
    const a = availability.data;
    if (cid && a?.available && a.released_at && a.competition_name) {
      maybeShow(cid, a.competition_name, a.released_at);
    }
    // `active` is a dep so dismissing one competition's modal re-checks whether
    // another (now the active one) has a release to show.
  }, [cid, availability.data, maybeShow, active]);

  if (!active) return null;
  return (
    <CertificateReleasedModal
      open
      competitionId={active.competitionId}
      competitionName={active.competitionName}
      onClose={dismiss}
    />
  );
}
