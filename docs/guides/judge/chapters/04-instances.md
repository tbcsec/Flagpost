An **instanced challenge** hands each team (or player) its own running copy
of a service, so nobody can trample another team's target or guess a shared
one. It needs the **Challenge Instances** module on for the competition and
an administrator to have connected a container runtime (Admin → Site
settings → Instances); until then nothing launches.

## The Deployment section

Open an existing challenge and fill in **Deployment**:

- **Container image** — the image to run (from a registry the
  administrator's credential can reach).
- **Exposure** — *TCP* (competitors connect to a port), *HTTP (subdomain +
  TLS)* (each instance gets its own https address; needs the administrator
  to have set a base domain), or *None*.
- **Ports**, **Environment variables**, **Instances per team**, and
  resource overrides — **CPUs**, **Memory**, **PIDs**, **Lifetime** — which
  default to the site or competition values when blank (memory and PIDs
  take whole numbers).
- **Flag mode** — *Shared flag* (the challenge's own flag, same for
  everyone) or *Unique per instance*: a **Flag template** containing the
  random-token placeholder the field names. Each instance gets its own flag,
  injected into the container as the `FLAG` environment variable, and a
  submission is graded against the submitter's **own running instance**.

**Set deployment** saves it; **Remove** stops the challenge offering
instances and reaps any running ones. A unique-flag challenge needs no static
flag and can be published as usual.

!!! tip "Unique flags catch sharing"
    With *Unique per instance*, submitting another team's flag is wrong —
    and quietly recorded as **flag sharing**. There's no automatic penalty
    and competitors aren't told; route the flag-sharing trigger into an
    automation (chapter 7) so staff hear about it, then decide.

## Running instances

**Instances** in the sidebar lists every live instance in the competition —
challenge, team or user, status, and when it expires — updating live.
**Kill** destroys one immediately; the subject can launch again. The
dashboard's **Instance health** section summarises instances by status with
recent failures.

Competitors launch only while the competition is running (and, in team mode,
once on a team); staff who can manage instances may test-launch at any time.
A launch can take a while for a large image — pre-pull images on the
instance host, and ask your administrator about the per-competition caps if
you expect a rush at kickoff.
