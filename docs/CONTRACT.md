# Contract version 1

Root fields: schema_version must be integer 1; artifacts is a nonempty array;
allow_unexpected is optional boolean, default false. Unknown fields are errors.
JSON object keys may not repeat.

Artifact fields:

| Field | Rule |
|---|---|
| id | Unique lowercase identifier, 1–64 characters, begins a-z; remaining a-z, 0-9, underscore or hyphen |
| name | Required filename template, at most 1,024 characters |
| matrix | Optional object of at most eight axes, each a nonempty array of unique ASCII token strings |
| exclude | Optional list of up to 100 nonempty partial assignments to declared axes; no unknown values or duplicate assignments |
| min_bytes | Optional integer >=1, default 1 |
| max_bytes | Optional null or integer >= min_bytes; default no upper bound |
| companions | Optional list of at most 16 literal suffixes, e.g. .sha256 or .sig |

Axis names follow id rules but may not be version. Axis values and the release
token are 1–100 ASCII letters/digits/dots/underscores/plus/minus, starting with a
letter or digit. Tags containing slashes/spaces are deliberately unsupported.

Only plain named template fields are accepted: {version} and declared axes.
No indexing, attribute access, conversion, format specifications, positional
arguments, shell expansion or executable interpolation. Literal braces may use
the usual doubled-brace escaping. Every expanded basename must be nonempty and
not dot/dot-dot, with no slash, backslash, colon or Unicode control/format/surrogate
characters, and at most 255 UTF-8 bytes.

Expanded expected filenames must be globally unique even under NFC+casefold.
A template that omits an axis and repeats the same name is rejected. This is
conservative and does not emulate actual Windows/macOS path equivalence.

A companion appends its suffix to the whole rendered artifact filename. Suffixes
begin with a dot, then an ASCII letter/digit, then letters/digits/dot/underscore/
hyphen; maximum length 65. Companion files have min_bytes=1 and no maximum.
To express a different size policy, model the companion as an independent group.

The raw Cartesian product is limited to 10,000 combinations before exclusions.
Every group must retain at least one combination. All final artifacts plus
companions must fit the global 10,000-slot limit. Numeric sizes are bounded by
2^63-1 and booleans are not accepted as numbers.

## Sources

Local stages enumerate only immediate entries and stat regular files without
opening their payload. Direct symlinks and Windows reparse points are refused,
including at the selected root. Parent path traversal is the caller's explicit
filesystem selection and is not a sandbox boundary.

Saved GitHub input must be one release object with string tag_name and array
assets. Each asset needs a basename name, nonnegative integer size and short
string state; other API fields are ignored. Exact state uploaded is required
for all observed GitHub assets, including optional extras. The exact tag must
equal --release. Draft/prerelease flags do not change inventory evaluation.

GitHub's automatic source-code links are not uploaded assets in the assets array.
Do not add those links as required asset slots unless you upload your own archives.
No pagination, fetching, signature, freshness or content checks occur here.

## Acceptance and architecture

The primary scenario has three expected platform binaries and three companions.
A full local stage passes; deleting a binary fails with its group and axis witness.
The equivalent saved release inventory must produce identical coverage findings.
Duplicate filenames cannot stand in for several platforms.

core.py separates strict contract compilation, filesystem/API inventory adapters
and deterministic evaluation. cli.py handles bounded UTF-8 JSON input, source
selection, escaped reporting and exit codes. Output caps truncate sample details
only; all total counts and status stay complete.

Security review: no eval or shell interpolation, no network, no artifact payload
reads, no writes, strict duplicate-key/schema checks, bounded matrix expansion,
regular-file-only local inventory, escaped output. Reports may reveal private
asset names or tags; users control publication of reports.

All source and fixture files are original. No third-party code or sample artifacts
are vendored. Python standard library only at runtime. Build and lint tools are
development dependencies and are not part of shipped program code.

