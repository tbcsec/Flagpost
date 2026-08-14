"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useDownloadMyCertificate } from "@/lib/hooks/use-certificates";

/** The one-time celebratory moment when certificates are released (#219). Closing
 *  it is fine — the certificate is re-findable via the profile, the scoreboard
 *  card, and the persistent notification. */
export function CertificateReleasedModal({
  open,
  competitionId,
  competitionName,
  onClose,
}: {
  open: boolean;
  competitionId: string;
  competitionName: string;
  onClose: () => void;
}) {
  const download = useDownloadMyCertificate(competitionId);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader className="items-center text-center">
          <div className="text-5xl" aria-hidden>
            🎓
          </div>
          <DialogTitle>Your certificate is ready!</DialogTitle>
          <DialogDescription>
            Congratulations on taking part in {competitionName}. Download your
            certificate to share it — you can always find it again under your profile.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="sm:justify-center">
          <Button variant="outline" asChild onClick={onClose}>
            <Link href="/profile?tab=certificates">View in profile</Link>
          </Button>
          <Button
            disabled={download.isPending}
            onClick={() => download.mutate(`certificate-${competitionName}.png`)}
          >
            {download.isPending ? "Preparing…" : "Download"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
