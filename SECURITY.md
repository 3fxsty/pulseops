# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |
| Anything older or unreleased | No |

PulseOps is a portfolio project maintained by one person. Only the latest 0.1.x release gets security fixes.

## Reporting a vulnerability

**Do not open a public issue, pull request or discussion for a security problem.** Anyone could read it before there is a fix.

Use GitHub's private report instead:

1. Go to the [Security tab](https://github.com/3fxsty/pulseops/security) of the repository.
2. Click **Report a vulnerability**.
3. Describe what you found, how to reproduce it and what you think the impact is.

Please do not include real secrets or other people's data in the report.

## What to expect

- This is a one-person project, so the times below are goals, not guarantees.
- You should get an acknowledgement within **7 days**.
- After that, you will hear whether the report is accepted as a vulnerability, and you will be kept updated until it is fixed or closed.
- Accepted vulnerabilities are fixed in a new 0.1.x release, and credited in its release notes if you want to be named.
- Please keep the details private until the fix is released.

## Scope and known limits

PulseOps is **not yet meant to be exposed to the internet**. The API listens on `127.0.0.1` only, and the secure deployment (reverse proxy, HTTPS, rate limits) arrives in Phase 9 of the roadmap. A report that depends on exposing the API directly to the internet is useful, but it is a known limit, not a surprise.

Of special interest: bypasses of the SSRF protection, secrets or monitored URLs reaching logs, and ways around the API key.
