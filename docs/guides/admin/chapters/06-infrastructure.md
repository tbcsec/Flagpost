Two optional modules run competitor-controlled code and need a container
runtime behind them. Both ship **off**, each has its own grant, and neither
does anything — however many competitions switch the module on — until you
set it up here. Where they use Docker (the code judge always; challenge
instances on the Docker backend) they talk to it through a
**least-privilege socket proxy**, never the raw socket; the Kubernetes
backend uses a namespace-scoped service account instead. Standing the proxy
up is operator work (docs.flagpost.io), and the judge's setup shows you the
one-line command.

## Site settings → Instances

Challenge instances hand each team its own running copy of a service
(Judge guide, chapter 4). The **Provider** card holds **Status**, the
**Backend** (*Docker* or *Kubernetes*), the proxy's **Endpoint URL**, the
**Public host** competitors connect to, an optional **Registry credential**
for private images, an **HTTP base domain** for web challenges (needs
wildcard DNS and a wildcard certificate), and a per-participant **Spawn
rate limit**. **Exposure & networking** sets the host **port range** to open
in your firewall and the **Egress policy** (*Deny* by default); **Default
resource limits** sets CPUs, memory, PIDs and a **global concurrent
instances** ceiling. Kubernetes adds a namespace-scoped service-account
token, CA certificate, ingress class, pull secret and cluster CIDRs.

**Save changes**, then **Test connection**: a staged check that reports each
step OK or Failed — reachability, privilege posture, network isolation, an
image pull and a probe run. Nothing can be enabled until an endpoint and
public host are saved (for Kubernetes, a token). Deployments written for
Docker run unchanged on Kubernetes.

## Site settings → Code judge

![The code judge](assets/code-judge.png)
*Where programming challenges are judged: the connection, the languages
competitors can use, and the default limits problems inherit.*

The code judge runs competitors' programs, each submission in a short-lived
container with no network. Setup is a guided three-step flow:

1. **Connect** — the **Proxy address** (or *Detected from your deployment*
   if the compose overlay set it) and **Check connection**, which must pass
   all four: *Proxy reachable*, *Proxy locked down*, *Judge harness
   installed*, *Test judging ran*. A proxy that isn't locked down would hand
   submissions a path to your server's Docker, so setup won't continue
   until it is.
2. **Languages** — tick what competitors may submit in. Nine are built in
   (C, C++, Rust, Go, Java, C#, JavaScript, Python 3, PyPy 3), each on a
   pinned official image downloaded on first use.
3. **Review and enable.**

Once on, the tab shows a summary with **Re-run setup** and **Turn off**.
**Advanced** exposes the **Executor** (**Judgings at once** — one is the
lightest and the fairest for time limits on shared hardware), the **Default
limits** every problem inherits, and the **Languages** list: each has a
**Time multiplier** so slower languages aren't penalised by limits tuned for
C — C/C++/Rust 1.0, Go 1.5, Java/C#/JavaScript/PyPy 2.0, Python 3.0 — plus
**Add custom language** for anything else. For a strict ICPC-style event,
set every multiplier to 1.0.

!!! note "Not in backups"
    The judge and instance configuration — endpoints, credentials,
    languages — is deliberately excluded from the platform backup: it names
    host-specific infrastructure and runs code. After restoring onto a new
    host, re-run both setups.

Organisers then switch the **Code Judge** (or **Challenge Instances**)
module on per competition — it's on by default — and author away.
