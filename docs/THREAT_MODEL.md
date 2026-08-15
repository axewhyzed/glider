# Threat Model

Glider is a local or service-side crawler that makes outbound HTTP and browser
requests from configuration-controlled URLs. Its main security boundary is
between configured/trusted origins and untrusted content returned by those
origins.

## Assets

- OAuth client credentials, bearer tokens, cookies, and proxy credentials;
- run manifests, failure records, debug snapshots, checkpoints, and exports;
- the host's local and private network services;
- integrity and completeness of streamed records and resumable state.

## Threats

- SSRF through start URLs, redirects, nested links, sitemaps, or browser
  subresources;
- DNS resolution changes or redirects that move a request to a private host;
- cross-origin leakage of authorization headers, cookies, or proxy secrets;
- malicious response content attempting to exploit browser navigation or
  service-worker behavior;
- path traversal through run identifiers or configuration file paths;
- cancellation, process failure, or writer failure causing silent data loss;
- unbounded origin, sitemap, cache, or failure state causing resource
  exhaustion.

## Controls

Glider validates schemes, ports, origins, redirects, and private-address
resolution; strips sensitive headers across origins; scopes configured cookies;
uses browser request guards and blocks service workers when browser policy is
active; bounds retry, sitemap, robots, proxy, limiter, failure, and snapshot
state; and persists typed checkpoints and flushed JSONL output.

These controls do not replace deployment isolation. Run Glider with least
privilege, restrict egress at the network layer, protect artifact directories,
and do not use production credentials in tests or examples.

## Residual risk

DNS and browser networking involve external resolvers and browser internals;
network-level egress controls remain necessary. Debug snapshots can contain
response data when explicitly enabled. Operators must review `allowed_domains`,
authentication, proxy, cookie, and browser settings for each deployment.
