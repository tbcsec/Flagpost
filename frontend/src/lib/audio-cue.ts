// The one sanctioned in-app sound (§4.4): a short two-note cue, scoped
// exclusively to support tickets — a new ticket for staff, a reply for whoever
// didn't post. Synthesized via the Web Audio API so there's no asset to ship,
// and entirely best-effort: if audio is unavailable or blocked, it's a no-op.

let ctx: AudioContext | null = null;

export function playTicketCue() {
  try {
    const Ctor =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctor) return;
    ctx = ctx ?? new Ctor();
    // Browsers suspend audio until a user gesture; by the time a ticket arrives
    // the user has interacted, so a resume normally succeeds.
    if (ctx.state === "suspended") void ctx.resume();

    const now = ctx.currentTime;
    [880, 1174.66].forEach((freq, i) => {
      const osc = ctx!.createOscillator();
      const gain = ctx!.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const t = now + i * 0.12;
      gain.gain.setValueAtTime(0.0001, t);
      gain.gain.exponentialRampToValueAtTime(0.14, t + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.11);
      osc.connect(gain).connect(ctx!.destination);
      osc.start(t);
      osc.stop(t + 0.12);
    });
  } catch {
    /* audio unavailable — non-fatal */
  }
}
