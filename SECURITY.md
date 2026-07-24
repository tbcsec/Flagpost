# Security Policy

Flagpost is a security-focused platform, and we take vulnerabilities in it
seriously. Thank you for helping keep it and its users safe.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
pull requests, or discussions.**

Instead, report them privately through GitHub's **[Private Vulnerability
Reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)**:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Fill in as much detail as you can (see below).

This opens a private advisory visible only to you and the maintainers.

A good report includes:

- The type of issue (e.g. auth bypass, IDOR, SSRF, XSS, injection, privilege
  escalation).
- The affected component and, where possible, file/endpoint.
- Step-by-step reproduction, including any required roles or setup.
- The impact — what an attacker can achieve.
- A proof of concept, if you have one.

## What to expect

- We aim to acknowledge a report within a few days.
- We'll work with you to confirm the issue, assess severity, and prepare a fix.
- We'll credit you in the advisory once a fix ships, unless you'd prefer to
  remain anonymous.

Please give us a reasonable window to release a fix before any public
disclosure.

## Scope

In scope: the Flagpost application code in this repository (backend, frontend,
and the deployment configuration we ship).

Out of scope: vulnerabilities in third-party dependencies (report those
upstream), and issues that require a misconfiguration we explicitly warn against
(for example, running with a public/default `JWT_SECRET` — the app already
refuses to and derives a per-install secret instead).

## Hardening notes for operators

If you self-host Flagpost, a few deployment choices matter for security — see
the "Deploying to production" section of the [README](README.md): set a strong
`JWT_SECRET` for multi-host, serve behind TLS, and use real credentials for
Postgres/Redis/object storage rather than the local defaults.
