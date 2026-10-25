import copy
import json
import os
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from release_slotcheck.core import (
    Asset,
    InputError,
    compile_contract,
    evaluate,
    filename,
    github_assets,
    is_link_or_reparse,
    local_assets,
    read_json,
)


def contract():
    return {
        "schema_version": 1,
        "artifacts": [
            {
                "id": "binary",
                "name": "tool-{version}-{os}-{arch}.zip",
                "matrix": {"os": ["linux", "windows"], "arch": ["x64", "arm64"]},
                "exclude": [{"os": "windows", "arch": "arm64"}],
                "min_bytes": 4,
                "max_bytes": 100,
                "companions": [".sha256"],
            }
        ],
    }


def inventory(slots):
    return [Asset(slot.name, 10, "uploaded") for slot in slots]


def codes(result):
    return set(result["finding_counts"])


class ContractTests(unittest.TestCase):
    def test_matrix_expansion_exclusion_and_companions(self):
        slots, allow = compile_contract(contract(), "v1.2.3")
        self.assertEqual(len(slots), 6)
        self.assertFalse(allow)
        self.assertEqual(
            {s.name for s in slots},
            {
                "tool-v1.2.3-linux-x64.zip",
                "tool-v1.2.3-linux-x64.zip.sha256",
                "tool-v1.2.3-linux-arm64.zip",
                "tool-v1.2.3-linux-arm64.zip.sha256",
                "tool-v1.2.3-windows-x64.zip",
                "tool-v1.2.3-windows-x64.zip.sha256",
            },
        )
        self.assertTrue(evaluate(slots, inventory(slots), "v1.2.3")["ok"])

    def test_partial_exclusion(self):
        data = contract()
        data["artifacts"][0]["exclude"] = [{"os": "windows"}]
        slots, _ = compile_contract(data, "v1")
        self.assertEqual(len(slots), 4)
        self.assertTrue(all(slot.axes["os"] == "linux" for slot in slots))

    def test_no_matrix_single_slot(self):
        slots, _ = compile_contract(
            {"schema_version": 1, "artifacts": [{"id": "checksums", "name": "SHA256SUMS"}]}, "v1"
        )
        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].axes, {})

    def test_missing_and_companion_witness(self):
        slots, _ = compile_contract(contract(), "v1")
        actual = inventory(slots)
        missing = next(asset for asset in actual if asset.name.endswith(".sha256"))
        actual.remove(missing)
        result = evaluate(slots, actual, "v1")
        self.assertEqual(result["finding_counts"], {"missing-asset": 1})
        witness = result["findings"][0]
        self.assertEqual(witness["name"], missing.name)
        self.assertIn("companion_of", witness)
        self.assertIn("arch", witness["axes"])

    def test_duplicate_asset_cannot_fill_multiple_slots(self):
        slots, _ = compile_contract(contract(), "v1")
        actual = inventory(slots)
        actual.append(actual[0])
        result = evaluate(slots, actual, "v1")
        self.assertIn("duplicate-asset", codes(result))
        self.assertEqual(result["summary"]["uniquely_matched_slots"], len(slots) - 1)

    def test_bounds_and_nonempty_companions(self):
        slots, _ = compile_contract(contract(), "v1")
        for size, expected in (
            (0, "asset-too-small"),
            (3, "asset-too-small"),
            (101, "asset-too-large"),
        ):
            actual = [
                Asset(s.name, size if s.companion_of is None else 1, "uploaded") for s in slots
            ]
            with self.subTest(size=size):
                self.assertIn(expected, codes(evaluate(slots, actual, "v1")))
        actual = [Asset(s.name, 4 if s.companion_of is None else 0, "uploaded") for s in slots]
        self.assertEqual(evaluate(slots, actual, "v1")["finding_counts"]["asset-too-small"], 3)

    def test_exact_bounds_pass(self):
        slots, _ = compile_contract(contract(), "v1")
        for size in (4, 100):
            actual = [Asset(s.name, size, "uploaded") for s in slots]
            self.assertTrue(evaluate(slots, actual, "v1")["ok"])

    def test_unexpected_policy(self):
        slots, _ = compile_contract(contract(), "v1")
        actual = inventory(slots) + [Asset("stale-v0.zip", 20, "uploaded")]
        self.assertIn("unexpected-asset", codes(evaluate(slots, actual, "v1")))
        result = evaluate(slots, actual, "v1", allow_unexpected=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["unexpected_assets"], 1)

    def test_github_tag_and_upload_state(self):
        slots, _ = compile_contract(contract(), "v1")
        actual = inventory(slots)
        actual[0] = Asset(actual[0].name, 10, "starter")
        result = evaluate(slots, actual, "v1", github_tag="v0")
        self.assertIn("release-tag-mismatch", codes(result))
        self.assertIn("asset-not-uploaded", codes(result))

    def test_actual_alias_even_when_extras_allowed(self):
        slots, _ = compile_contract(contract(), "v1")
        actual = inventory(slots) + [
            Asset("README", 10, "uploaded"),
            Asset("readme", 10, "uploaded"),
        ]
        self.assertIn(
            "asset-name-alias", codes(evaluate(slots, actual, "v1", allow_unexpected=True))
        )

    def test_sample_limit_counts_all(self):
        slots, _ = compile_contract(contract(), "v1")
        result = evaluate(slots, [], "v1", max_findings=2)
        self.assertEqual(result["finding_counts"]["missing-asset"], 6)
        self.assertEqual(result["omitted_findings"], 4)
        self.assertFalse(result["ok"])

    def test_contract_name_collision(self):
        for change in (
            lambda group: group.update(name="tool.zip"),
            lambda group: group.update(companions=[".sha256", ".sha256"]),
            lambda group: group.update(
                matrix={"os": ["linux", "LINUX"]}, name="tool-{os}", exclude=[]
            ),
        ):
            data = contract()
            change(data["artifacts"][0])
            with self.assertRaises(InputError):
                compile_contract(data, "v1")

    def test_collision_between_groups(self):
        data = contract()
        data["artifacts"].append({"id": "extra", "name": "tool-v1-linux-x64.zip"})
        with self.assertRaises(InputError):
            compile_contract(data, "v1")

    def test_format_language_is_not_python_evaluation(self):
        for name in (
            "x-{version.__class__}",
            "x-{version[0]}",
            "{version!r}",
            "{version:10}",
            "{}",
            "{missing}",
            "{",
        ):
            data = contract()
            data["artifacts"][0]["name"] = name
            with self.subTest(name=name), self.assertRaises(InputError):
                compile_contract(data, "v1")

    def test_schema_errors(self):
        for modify in (
            lambda d: d.update(schema_version=True),
            lambda d: d.update(artifacts=[]),
            lambda d: d.update(allow_unexpected="false"),
            lambda d: d.update(allow_unexpcted=True),
            lambda d: d["artifacts"][0].update(unknown="field"),
            lambda d: d["artifacts"][0].update(id="Bad ID"),
            lambda d: d["artifacts"][0].update(min_bytes=True),
            lambda d: d["artifacts"][0].update(min_bytes=0),
            lambda d: d["artifacts"][0].update(max_bytes=1),
            lambda d: d["artifacts"][0].update(companions=["/bad"]),
            lambda d: d["artifacts"][0].update(matrix={"version": ["x"]}, exclude=[]),
            lambda d: d["artifacts"][0].update(matrix={"os": []}, exclude=[]),
            lambda d: d["artifacts"][0].update(matrix={"os": ["x", "x"]}, exclude=[]),
            lambda d: d["artifacts"][0].update(exclude=[{}]),
            lambda d: d["artifacts"][0].update(exclude=[{"unknown": "x"}]),
            lambda d: d["artifacts"][0].update(exclude=[{"os": "mac"}]),
            lambda d: d["artifacts"][0].update(exclude=[{"os": "linux"}, {"os": "windows"}]),
            lambda d: d["artifacts"][0].update(exclude=[{"os": "linux"}, {"os": "linux"}]),
        ):
            data = contract()
            modify(data)
            with self.assertRaises(InputError):
                compile_contract(data, "v1")

    def test_duplicate_group_id(self):
        data = contract()
        data["artifacts"].append(copy.deepcopy(data["artifacts"][0]))
        with self.assertRaises(InputError):
            compile_contract(data, "v1")

    def test_matrix_budget_before_expansion(self):
        data = contract()
        data["artifacts"][0]["matrix"] = {
            "os": [f"a{x}" for x in range(101)],
            "arch": [f"b{x}" for x in range(100)],
        }
        data["artifacts"][0]["exclude"] = []
        with self.assertRaisesRegex(InputError, "product exceeds"):
            compile_contract(data, "v1")

    def test_total_budget_includes_companions(self):
        with (
            patch("release_slotcheck.core.MAX_ASSETS", 5),
            self.assertRaisesRegex(InputError, "expanded contract"),
        ):
            compile_contract(contract(), "v1")

    def test_release_and_asset_name_validation(self):
        for release in ("", "../v1", "a/b", "v 1", "x" * 101, True):
            with self.subTest(release=release), self.assertRaises(InputError):
                compile_contract(contract(), release)
        for name in ("", ".", "..", "/x", "a\\b", "x:y", "a\0b", "x\u202e", "x" * 256):
            with self.subTest(name=name), self.assertRaises(InputError):
                filename(name)

    def test_deterministic_and_no_mutation(self):
        data = contract()
        before = copy.deepcopy(data)
        a, _ = compile_contract(data, "v1")
        b, _ = compile_contract(data, "v1")
        self.assertEqual(a, b)
        self.assertEqual(data, before)


class InputAndCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_local_stage_and_github_equivalent_coverage(self):
        slots, _ = compile_contract(contract(), "v1")
        stage = self.root / "stage"
        stage.mkdir()
        for slot in slots:
            (stage / slot.name).write_bytes(b"0123456789")
        local = local_assets(stage)
        remote, tag = github_assets(
            {
                "tag_name": "v1",
                "unrelated_server_field": True,
                "assets": [
                    {"name": s.name, "size": 10, "state": "uploaded", "id": i}
                    for i, s in enumerate(slots)
                ],
            }
        )
        a = evaluate(slots, local, "v1")
        b = evaluate(slots, remote, "v1", github_tag=tag)
        self.assertTrue(a["ok"] and b["ok"])
        self.assertEqual(a["summary"], b["summary"])
        self.assertEqual(a["findings"], b["findings"])

    def test_payload_is_not_read(self):
        (self.root / "file").write_bytes(b"content")
        with patch.object(Path, "open", side_effect=AssertionError("payload accessed")):
            result = local_assets(self.root)
        self.assertEqual(result, [Asset("file", 7, "local")])

    def test_directory_entry_rejected(self):
        (self.root / "subdir").mkdir()
        with self.assertRaises(InputError):
            local_assets(self.root)

    def test_link_attributes(self):
        self.assertTrue(
            is_link_or_reparse(types.SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0))
        )
        self.assertTrue(
            is_link_or_reparse(types.SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=1024))
        )
        self.assertFalse(is_link_or_reparse(types.SimpleNamespace(st_mode=stat.S_IFREG)))

    def test_actual_symlink_refused_when_supported(self):
        target = self.root / "target"
        target.write_bytes(b"data")
        link = self.root / "link"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable for current user")
        with self.assertRaises(InputError):
            local_assets(self.root)

    def test_stage_budget(self):
        for i in range(3):
            (self.root / str(i)).write_text("x")
        with patch("release_slotcheck.core.MAX_ASSETS", 2), self.assertRaises(InputError):
            local_assets(self.root)

    def test_github_schema_errors(self):
        for data in (
            [],
            {"message": "Not Found"},
            {"tag_name": "v1", "assets": {}},
            {"tag_name": "v1", "assets": [{"name": "x", "size": True, "state": "uploaded"}]},
            {"tag_name": "v1", "assets": [{"name": "x", "size": -1, "state": "uploaded"}]},
            {"tag_name": "v1", "assets": [{"name": "x", "size": 1}]},
            {"tag_name": "v1", "assets": [{"name": "x", "size": 1, "state": None}]},
        ):
            with self.subTest(data=data), self.assertRaises(InputError):
                github_assets(data)

    def test_json_duplicate_size_and_encoding(self):
        path = self.root / "input.json"
        for content in (b'{"x":1,"x":2}', b"\xff", b"null trailing", b" " * (8 * 1024 * 1024 + 1)):
            path.write_bytes(content)
            with self.assertRaises(InputError):
                read_json(path)

    def test_cli_local_full_flow(self):
        conf = self.root / "contract.json"
        conf.write_text(json.dumps(contract()), encoding="utf-8")
        stage = self.root / "stage"
        stage.mkdir()
        slots, _ = compile_contract(contract(), "v1")
        for slot in slots:
            (stage / slot.name).write_bytes(b"0123456789")
        command = [
            sys.executable,
            "-m",
            "release_slotcheck",
            str(conf),
            "--release",
            "v1",
            "--directory",
            str(stage),
            "--json",
        ]

        def run():
            return subprocess.run(command, capture_output=True, text=True, timeout=20)

        result = run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        (stage / slots[0].name).unlink()
        result = run()
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing-asset", json.loads(result.stdout)["finding_counts"])
        conf.write_text("[]", encoding="utf-8")
        self.assertEqual(run().returncode, 2)

    def test_cli_saved_github_metadata(self):
        data = {"schema_version": 1, "artifacts": [{"id": "app", "name": "tool-{version}"}]}
        conf, metadata = self.root / "contract.json", self.root / "release.json"
        conf.write_text(json.dumps(data))
        metadata.write_text(
            json.dumps(
                {"tag_name": "v1", "assets": [{"name": "tool-v1", "size": 12, "state": "uploaded"}]}
            )
        )
        command = [
            sys.executable,
            "-m",
            "release_slotcheck",
            str(conf),
            "--release",
            "v1",
            "--github-json",
            str(metadata),
            "--json",
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["source"], "github-json")
        metadata.write_text('{"message":"API error"}')
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stderr)["complete"])

    def test_invalid_sample_limit(self):
        slots, _ = compile_contract(contract(), "v1")
        for limit in (True, 0, -1, 100001):
            with self.assertRaises(InputError):
                evaluate(slots, [], "v1", max_findings=limit)
