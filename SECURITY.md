# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem. Report it privately through GitHub:
**Security** tab → **Report a vulnerability** (GitHub's private vulnerability reporting). Only the
maintainer sees the report, and a fix can be prepared and published as a security advisory before the
details become public.

A useful report says:

- what is affected (endpoint, module, file) and the version or commit;
- how to reproduce it, step by step, or a minimal proof of concept;
- what an attacker gains;
- any suggestion for a fix.

## What to expect

NeoTV is maintained by one person, so these are commitments, not service levels:

- an acknowledgement within **7 days**;
- an assessment, and a plan or a fix for confirmed issues, within **30 days**;
- credit in the advisory if you would like it.

There is no bug bounty.

## Scope

In scope: this repository's code — the backend, the web client, the Docker images and compose files,
and the CI workflows.

Out of scope:

- the third-party public test streams the demo plays (Apple, Akamai, Unified Streaming, Blender);
- denial of service by volume, and missing rate limits on endpoints that already have one;
- findings that need a compromised device, browser or administrator account;
- reports produced by automated scanners without a demonstrated impact.

## Supported versions

Only the latest commit on `main` receives fixes.

## Good faith

Research that respects people's privacy and data, avoids degrading the service, and gives reasonable
time for a fix before disclosure will not be pursued.

## How security is built in

For the design behind the reports you may send: security headers and CSP ([ADR-0006](docs/adr/0006-security-headers-csp-hsts.md)),
browser tests under the production CSP ([ADR-0007](docs/adr/0007-browser-tests-under-production-csp.md)),
observability and alerting ([ADR-0008](docs/adr/0008-observability.md)), and the audit the platform was
rebuilt from ([ADR-0010](docs/adr/0010-from-audit-to-rewrite.md)). CI scans the whole git history for
secrets on every push, and dependency updates arrive weekly through Dependabot.
