"""Strict expected asset contracts and offline release-inventory evaluation."""

import collections
import itertools
import json
import os
import re
import stat
import string
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MAX_JSON = 8 * 1024 * 1024
MAX_ASSETS = 10_000
MAX_INT = 2**63 - 1
IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,63}")
VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,99}")


class InputError(ValueError):
    """Invalid, ambiguous or unsupported input; no complete audit."""


@dataclass(frozen=True)
class Slot:
    group: str
    axes: dict
    name: str
    min_bytes: int
    max_bytes: int | None
    companion_of: str | None = None


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    state: str


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
        raise InputError("JSON input exceeds 8 MiB")
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise InputError(f"invalid JSON: {exc}") from exc


def filename(value):
    if not isinstance(value, str) or not value or value in (".", ".."):
        raise InputError("asset name must be a nonempty basename")
    if any(char in value for char in "/\\:") or any(
        unicodedata.category(c).startswith("C") for c in value
    ):
        raise InputError(f"asset name is not a plain basename: {value!r}")
    if len(value.encode("utf-8")) > 255:
        raise InputError("asset name exceeds 255 UTF-8 bytes")
    return value


def number(value, label, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_INT:
        raise InputError(f"{label} must be an integer from {minimum} through {MAX_INT}")
    return value


def render(template, variables):
    if not isinstance(template, str) or len(template) > 1024:
        raise InputError("name template must be a string of at most 1024 characters")
    output = []
    try:
        for literal, field, spec, conversion in string.Formatter().parse(template):
            output.append(literal)
            if field is not None:
                if field not in variables or spec or conversion:
                    raise InputError(
                        "templates allow only plain {version} and declared matrix fields"
                    )
                output.append(variables[field])
    except ValueError as exc:
        raise InputError(f"invalid name template: {exc}") from exc
    return filename("".join(output))


def compile_contract(data, release):
    if not isinstance(release, str) or not VALUE.fullmatch(release):
        raise InputError(
            "release must use 1-100 ASCII letters/digits/dots/underscores/plus/minus, starting alphanumeric"
        )
    if (
        not isinstance(data, dict)
        or not {"schema_version", "artifacts"} <= data.keys()
        or not data.keys() <= {"schema_version", "artifacts", "allow_unexpected"}
    ):
        raise InputError("contract requires schema_version, artifacts; optional allow_unexpected")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise InputError("unsupported contract schema_version")
    if type(data.get("allow_unexpected", False)) is not bool:
        raise InputError("allow_unexpected must be boolean")
    artifacts = data["artifacts"]
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= MAX_ASSETS:
        raise InputError("artifacts must be a nonempty array of at most 10000 groups")
    slots = []
    names = {}
    groups = set()

    def add(slot):
        if len(slots) >= MAX_ASSETS:
            raise InputError("expanded contract exceeds 10000 asset slots")
        key = unicodedata.normalize("NFC", slot.name).casefold()
        if key in names:
            raise InputError(f"contract asset names collide: {names[key]!r}, {slot.name!r}")
        names[key] = slot.name
        slots.append(slot)

    for group in artifacts:
        if (
            not isinstance(group, dict)
            or not {"id", "name"} <= group.keys()
            or not group.keys()
            <= {"id", "name", "matrix", "exclude", "min_bytes", "max_bytes", "companions"}
        ):
            raise InputError("artifact group has missing or unknown fields")
        identity = group["id"]
        if (
            not isinstance(identity, str)
            or not IDENTIFIER.fullmatch(identity)
            or identity in groups
        ):
            raise InputError("artifact id must be a unique lowercase identifier")
        groups.add(identity)
        minimum = number(group.get("min_bytes", 1), "min_bytes", 1)
        maximum = group.get("max_bytes")
        if maximum is not None:
            number(maximum, "max_bytes", minimum)
        matrix = group.get("matrix", {})
        if not isinstance(matrix, dict) or len(matrix) > 8:
            raise InputError("matrix must be an object with at most 8 axes")
        product = 1
        for axis, values in matrix.items():
            if not isinstance(axis, str) or not IDENTIFIER.fullmatch(axis) or axis == "version":
                raise InputError("matrix axes must be lowercase identifiers other than version")
            if not isinstance(values, list) or not values or len(values) > MAX_ASSETS:
                raise InputError("each matrix axis needs a nonempty value array")
            if any(not isinstance(value, str) or not VALUE.fullmatch(value) for value in values):
                raise InputError("axis values must be safe ASCII name tokens")
            if len(set(values)) != len(values):
                raise InputError("duplicate matrix value")
            product *= len(values)
            if product > MAX_ASSETS:
                raise InputError("matrix product exceeds 10000 combinations before exclusions")
        excludes = group.get("exclude", [])
        if not isinstance(excludes, list) or len(excludes) > 100:
            raise InputError("exclude must contain at most 100 partial matrix assignments")
        seen_excludes = set()
        for exclusion in excludes:
            if (
                not isinstance(exclusion, dict)
                or not exclusion
                or not exclusion.keys() <= matrix.keys()
            ):
                raise InputError("each exclusion must contain known matrix axes")
            if any(value not in matrix[axis] for axis, value in exclusion.items()):
                raise InputError("exclusion contains an unknown matrix value")
            key = tuple(sorted(exclusion.items()))
            if key in seen_excludes:
                raise InputError("duplicate exclusion")
            seen_excludes.add(key)
        companions = group.get("companions", [])
        if not isinstance(companions, list) or len(companions) > 16:
            raise InputError("companions must be an array of at most 16 literal suffixes")
        for suffix in companions:
            if not isinstance(suffix, str) or not re.fullmatch(
                r"\.[A-Za-z0-9][A-Za-z0-9._-]{0,63}", suffix
            ):
                raise InputError(
                    "companion suffixes must begin with a dot and use safe ASCII characters"
                )
        axes = sorted(matrix)
        combinations = itertools.product(*(matrix[axis] for axis in axes))
        active = 0
        for values in combinations:
            coordinates = dict(zip(axes, values, strict=True))
            if any(
                all(coordinates[axis] == value for axis, value in excluded.items())
                for excluded in excludes
            ):
                continue
            active += 1
            name = render(group["name"], {"version": release, **coordinates})
            add(Slot(identity, coordinates, name, minimum, maximum))
            for suffix in companions:
                # Companion files have independent default nonempty bounds.
                add(Slot(identity, coordinates, filename(name + suffix), 1, None, name))
        if not active:
            raise InputError("a group may not exclude all its combinations")
    return sorted(slots, key=lambda slot: slot.name), data.get("allow_unexpected", False)


def is_link_or_reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 1024)


def local_assets(directory):
    path = Path(directory)
    info = path.lstat()
    if is_link_or_reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise InputError("stage root must be a real directory, not a link/reparse point")
    result = []
    with os.scandir(path) as entries:
        for entry in entries:
            if len(result) >= MAX_ASSETS:
                raise InputError("stage contains more than 10000 assets")
            info = entry.stat(follow_symlinks=False)
            if is_link_or_reparse(info) or not stat.S_ISREG(info.st_mode):
                raise InputError(f"stage entry must be a regular file: {entry.name!r}")
            result.append(Asset(filename(entry.name), number(info.st_size, "file size"), "local"))
    return result


def github_assets(data):
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("tag_name"), str)
        or not isinstance(data.get("assets"), list)
    ):
        raise InputError("expected one GitHub release object with tag_name and assets")
    if len(data["tag_name"]) > 1024 or len(data["assets"]) > MAX_ASSETS:
        raise InputError("GitHub release metadata exceeds limits")
    assets = []
    for item in data["assets"]:
        if not isinstance(item, dict) or not {"name", "size", "state"} <= item.keys():
            raise InputError("each GitHub asset requires name, size and state")
        if not isinstance(item["state"], str) or len(item["state"]) > 64:
            raise InputError("asset state must be a short string")
        assets.append(
            Asset(filename(item["name"]), number(item["size"], "asset size"), item["state"])
        )
    return assets, data["tag_name"]


def evaluate(slots, assets, release, *, allow_unexpected=False, github_tag=None, max_findings=1000):
    number(max_findings, "max_findings", 1)
    if max_findings > 100_000:
        raise InputError("max_findings exceeds 100000")
    findings = []
    counts = collections.Counter()

    def add(code, **details):
        counts[code] += 1
        if len(findings) < max_findings:
            findings.append({"code": code, **details})

    if github_tag is not None and github_tag != release:
        add("release-tag-mismatch", expected=release, actual=github_tag)
    by_name = collections.defaultdict(list)
    aliases = collections.defaultdict(set)
    for asset in assets:
        by_name[asset.name].append(asset)
        aliases[unicodedata.normalize("NFC", asset.name).casefold()].add(asset.name)
    for key in sorted(aliases):
        if len(aliases[key]) > 1:
            add("asset-name-alias", names=sorted(aliases[key]))
    for name in sorted(by_name):
        if len(by_name[name]) != 1:
            add("duplicate-asset", name=name, count=len(by_name[name]))
        if github_tag is not None:
            for asset in by_name[name]:
                if asset.state != "uploaded":
                    add("asset-not-uploaded", name=name, state=asset.state)

    expected_names = {slot.name for slot in slots}
    matched = 0
    for slot in slots:
        actual = by_name.get(slot.name, [])
        details = {"name": slot.name, "group": slot.group, "axes": slot.axes}
        if slot.companion_of is not None:
            details["companion_of"] = slot.companion_of
        if not actual:
            add("missing-asset", **details)
        elif len(actual) == 1:
            matched += 1
            size = actual[0].size
            if size < slot.min_bytes:
                add("asset-too-small", **details, size=size, min_bytes=slot.min_bytes)
            if slot.max_bytes is not None and size > slot.max_bytes:
                add("asset-too-large", **details, size=size, max_bytes=slot.max_bytes)
    unexpected = sorted(by_name.keys() - expected_names)
    if not allow_unexpected:
        for name in unexpected:
            add("unexpected-asset", name=name)
    total = sum(counts.values())
    return {
        "schema_version": 1,
        "complete": True,
        "ok": total == 0,
        "release": release,
        "source": "github-json" if github_tag is not None else "local",
        "summary": {
            "expected_slots": len(slots),
            "observed_assets": len(assets),
            "uniquely_matched_slots": matched,
            "unexpected_assets": len(unexpected),
        },
        "finding_counts": dict(sorted(counts.items())),
        "findings": findings,
        "omitted_findings": total - len(findings),
    }
