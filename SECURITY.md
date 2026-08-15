# Security Policy

Glider handles URLs, credentials, cookies, proxy endpoints, and downloaded
content. Treat its configuration and run-artifact directories as sensitive.

## Reporting a vulnerability

Please do not open a public issue for an exploitable security problem. Report
it privately to the repository maintainer through the GitHub Security Advisories
workflow, including:

- affected version or commit;
- a minimal reproduction or proof of concept;
- impact and required configuration;
- any suggested mitigation.

Allow reasonable time for triage and a coordinated fix before public
disclosure. Do not include live credentials or private customer data in a
report.

## Security expectations

- Keep `url_policy.block_private_networks` and DNS resolution checks enabled
  unless the deployment has an equivalent network boundary.
- Use explicit `allowed_domains` and avoid permitting external URLs unless
  required by the crawl.
- Treat cookie files, OAuth secrets, bearer tokens, proxy URLs, manifests,
  debug snapshots, and failure artifacts as confidential.
- Enable debug snapshots only for controlled, short-lived investigations.
- Review redirects, proxy health, and browser policy before scraping
  authenticated or multi-origin targets.
- Keep runtime dependencies and Playwright browsers current.

Security controls are defense-in-depth; Glider should run inside a restricted
service account, container, or network policy when processing untrusted input.
