# Release Provenance Status - syndicateclaw

This file inventories the GPG signing status of historical release tags and documents release policy for this repository.

## 1. Policy Status

- **Release Provenance Policy**: Active (governed by [docs/release/RELEASE_PROVENANCE_SPECIFICATION.md](file:///home/mike/Projects/ai-syndicate/syndicateclaw/docs/release/RELEASE_PROVENANCE_SPECIFICATION.md)).
- **Tagging Requirement**: New tags must be annotated and GPG-signed (`git tag -s`). Lightweight tags are prohibited.
- **Manifest Requirement**: All release candidates must build a signed `release_manifest.json` before building production artifacts.

## 2. Inventory of Historical Tags

- **Latest Trusted Signed Release Point**: `None`
- **Historical Unsigned Tags**: 14 tags listed below.

| Tag Name | Tag Type | Status / Classification | Replacement Required |
| --- | --- | --- | --- |
| `v2.2.8` | annotated_unsigned | Accepted legacy risk | No |
| `v2.2.7` | lightweight | Accepted legacy risk | No |
| `v2.2.6` | annotated_unsigned | Accepted legacy risk | No |
| `v2.2.5` | lightweight | Accepted legacy risk | No |
| `v2.2.4` | lightweight | Accepted legacy risk | No |
| `v2.2.3` | lightweight | Accepted legacy risk | No |
| `v2.2.2` | lightweight | Accepted legacy risk | No |
| `v2.2.1` | lightweight | Accepted legacy risk | No |
| `v2.2.0` | lightweight | Accepted legacy risk | No |
| `v2.1.2` | lightweight | Accepted legacy risk | No |
| `v2.1.1` | lightweight | Accepted legacy risk | No |
| `v2.1.0` | lightweight | Accepted legacy risk | No |
| `v2.0.0` | annotated_unsigned | Accepted legacy risk | No |
| `v1.0.0` | annotated_unsigned | Accepted legacy risk | No |

## 3. Risk and Mitigation Strategy

1. **Accepted Legacy Risk**: Older releases (`v1.x`, `v0.x`, etc.) were published prior to the GPG signing key requirement. Rewriting history to replace these with signed tags is rejected to protect repository history.
2. **Replacement Signed Tags**: No signed replacement tags are planned for historical releases.
3. **Manual Action Required**:
   - Ensure the GPG key `FAC522F6588C64266ABC7742140FD4DD53964C08` or equivalent is used to sign all future release tags.
   - Do not push lightweight tags.
