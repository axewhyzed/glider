# Release status

## Recommended release

Use **v3.3.1** for new deployments. It is the latest verified release and
includes the current browser validation, deterministic usage benchmarks,
stable benchmark naming, and `workload_size` terminology.

- Tag: `v3.3.1`
- Release implementation commit: `f24cd1e0b2c1ce0cf396dfd36092f252466aca47`
- `main` may be ahead of the tag with release-documentation-only commits; the
  tag intentionally identifies the reviewed implementation.

## Historical tags

All published tags are retained for reproducibility. They are not deleted or
rewritten merely because later releases fixed issues in them.

| Release | Status | Guidance |
| --- | --- | --- |
| `v3.3.1` | Recommended | Use for new deployments. |
| `v3.3.0` | Superseded | Upgrade to v3.3.1 for benchmark naming and terminology cleanup. |
| `v3.2.1` | Superseded | Upgrade to v3.3.1 for later usage and browser improvements. |
| `v3.2.0` | Superseded | Historical usage-validation release; use v3.3.1. |
| `v3.1.0` and earlier | Historical/unsupported | Retained for auditability; do not use for new deployments. |

Historical release notes describe the behavior and verification state of each
version at the time it was published. They are not recommendations for new
deployments.

## Deprecation policy

When a release is superseded, update its GitHub release description with a
clear **Deprecated — use v3.3.1** notice while keeping the Git tag immutable.
Delete or retarget a tag only for a security emergency such as leaked
credentials or malicious code. Normal bugs are handled by publishing a new
release and documenting the upgrade path.

Before upgrading, read [`UPGRADE_GUIDE.md`](../UPGRADE_GUIDE.md) and review
the relevant entries in [`CHANGELOG.md`](../CHANGELOG.md).
