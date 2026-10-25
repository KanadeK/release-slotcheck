# release-slotcheck

Check that every promised **release asset slot** exists exactly once, with the
expected filename and size bounds, before announcing a release.

For projects assembling artifacts from several OS/architecture builders. Expand
an explicit matrix, require per-artifact companions, and apply the same contract
to a local staging directory or a saved GitHub Release API response.

Python 3.11+, no runtime dependencies, no network access or payload execution.
[中文说明](README.zh-CN.md) · [Contract reference](docs/CONTRACT.md)

## Install and try

~~~sh
git clone https://github.com/KanadeK/release-slotcheck.git
cd release-slotcheck
python -m venv .venv
# Linux/macOS:
.venv/bin/python -m pip install .
.venv/bin/release-slotcheck --version
# Windows PowerShell:
.venv/Scripts/python.exe -m pip install .
.venv/Scripts/release-slotcheck.exe --version

python examples/demo.py
~~~

The demo creates six real synthetic files, verifies the full stage, removes one
arm64 artifact and verifies failure, then checks a clearly synthetic saved release
response. Temporary files are cleaned up. The release wheel is also installable
with pip; no PyPI publication is claimed. From a checkout, use
python -m release_slotcheck without installing.

## Define the promised assets

The included examples/contract.json describes three supported platform
combinations and a .sha256 companion for each:

~~~json
{
  "schema_version": 1,
  "allow_unexpected": false,
  "artifacts": [{
    "id": "binary",
    "name": "tool-{version}-{os}-{arch}.zip",
    "matrix": {
      "os": ["linux", "windows"],
      "arch": ["x64", "arm64"]
    },
    "exclude": [{"os": "windows", "arch": "arm64"}],
    "min_bytes": 4,
    "max_bytes": 100,
    "companions": [".sha256"]
  }]
}
~~~

The size bounds above suit tiny demo files. Set meaningful bounds for your real
builds; the default minimum is one byte and there is no default maximum.
Companions use an independent minimum of one byte. A companion's **presence**
is checked; checksum/signature content is not verified.

The exact --release token replaces {version}, including any v prefix. There is
no automatic semantic-version parsing. Matrix axes are explicit; exclusions
remove only intentionally unsupported combinations. Use an artifact group without
a matrix for aggregate checksums or other single files.

## Check a stage or release snapshot

~~~sh
release-slotcheck release-contract.json --release v1.2.3 --directory stage --json
release-slotcheck release-contract.json --release v1.2.3 --github-json release.json --json
~~~

A stage is a flat directory of regular files only. Unexpected files fail by
default. Subdirectories, symlinks and Windows reparse points are refused so the
tool cannot silently audit only a subset.

For a real GitHub release, save the complete API response yourself, then audit
it offline. For example with an independently authenticated gh installation:

~~~sh
gh api repos/OWNER/REPOSITORY/releases/tags/v1.2.3 > release.json
release-slotcheck release-contract.json --release v1.2.3 --github-json release.json --json
~~~

In Windows PowerShell 5.1, redirect using UTF-8 instead of its default UTF-16:
pipe the gh output to Set-Content -Encoding UTF8 release.json.
The checker accepts a UTF-8 BOM. It never invokes gh or reads credentials.
API error objects are input errors, not reported as missing release assets.
Draft and prerelease responses may be checked; their publication state is not a gate.

## Findings and automation

| Code | Meaning |
|---|---|
| missing-asset | An expanded artifact or companion slot is absent |
| duplicate-asset | More than one observed asset uses the same exact name |
| asset-too-small / asset-too-large | A required file violates its byte-size bounds |
| unexpected-asset | An observed file is outside the contract |
| asset-not-uploaded | GitHub state is not uploaded, including incomplete starter assets |
| asset-name-alias | Observed names collide under conservative NFC + casefold |
| release-tag-mismatch | Saved metadata belongs to a different exact tag |

Expected names that collide, malformed templates, unknown contract fields, empty
groups or exclusions that remove an entire group are configuration errors.
A broad filename cannot satisfy several architecture slots.

Exit **0**: complete scan with no findings. Exit **1**: complete scan with findings.
Exit **2**: invalid/unreadable/unsupported/over-budget input, with complete=false
on stderr. JSON report schema version is 1. All names are escaped in text output.
--max-findings limits samples (default 1,000), while totals and failure remain
complete. uniquely_matched_slots counts exact unique name matches, not successful
size/state checks.

## Limits and alternatives

This checks a declared inventory contract. It does **not** determine actual binary
architecture, test executables, verify signatures or checksums, compare local and
remote bytes, authenticate GitHub metadata, or prove that a saved response is
fresh and complete. A mislabeled binary can pass. Keep platform runtime tests
and byte verification in the release pipeline.

No payload contents are read, no files are changed, and nothing is downloaded.
Snapshot-based results describe only the supplied inputs. Local files must be
stable while sizes are inspected. Symlinks in ancestor directories of an explicitly
supplied stage are not independently resolved or audited.

Budgets: 8 MiB per JSON file, 10,000 observed assets, 10,000 expanded slots,
8 matrix axes, 100 exclusions per group, 16 companion suffixes, 255 UTF-8 bytes per
filename. The full matrix must fit before exclusions. See [the contract reference](docs/CONTRACT.md)
for precise token and template rules.

[GoReleaser](https://goreleaser.com/) provides a full build and publication workflow.
This tool is useful when builders and upload steps are independent or when a
saved release snapshot needs an offline check. It is a contract gate, not a
replacement for that build system.

## Development and cleanup

~~~sh
python -m unittest discover -s tests -v
python -m pip install ruff==0.14.2 build==1.3.0
python -m ruff check .
python -m ruff format --check .
python -m build
~~~

Tests cover matrix expansion, companion identity, duplicate assets, bad inputs,
actual filesystem staging, CLI workflows, and matching local/GitHub inventories.
CI tests Windows, Linux and macOS. Actual symlink tests skip only when the current
user cannot create them; reparse/link attribute recognition is tested separately.

Uninstall with the virtual environment's python -m pip uninstall release-slotcheck.
The checker has no cache, configuration directory or background process. Remove
saved API JSON files and the virtual environment when no longer needed. Reports
contain asset names and tags; review them before sharing. MIT licensed.

