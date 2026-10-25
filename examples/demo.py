"""Exercise real staging files and a clearly synthetic GitHub release object."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    names = [
        f"tool-v1.2.3-{system}-{arch}.zip"
        for system, arch in (("linux", "x64"), ("linux", "arm64"), ("windows", "x64"))
    ]
    names += [name + ".sha256" for name in list(names)]
    with tempfile.TemporaryDirectory(prefix="slotcheck-demo-") as directory:
        root = Path(directory)
        stage = root / "stage"
        stage.mkdir()
        for name in names:
            (stage / name).write_bytes(b"synthetic fixture bytes\n")
        base = [
            sys.executable,
            "-m",
            "release_slotcheck",
            str(HERE / "contract.json"),
            "--release",
            "v1.2.3",
            "--json",
        ]

        def run(extra, expected):
            result = subprocess.run(base + extra, capture_output=True, text=True, check=False)
            if result.returncode != expected:
                raise RuntimeError(result.stdout + result.stderr)
            return json.loads(result.stdout)

        run(["--directory", str(stage)], 0)
        (stage / "tool-v1.2.3-linux-arm64.zip").unlink()
        missing = run(["--directory", str(stage)], 1)
        if missing["finding_counts"] != {"missing-asset": 1}:
            raise RuntimeError("Expected exactly the missing architecture asset")
        metadata = root / "release.json"
        metadata.write_text(
            json.dumps(
                {
                    "tag_name": "v1.2.3",
                    "assets": [{"name": name, "size": 23, "state": "uploaded"} for name in names],
                }
            ),
            encoding="utf-8",
        )
        run(["--github-json", str(metadata)], 0)
        print("PASS: full stage accepted, missing arm64 rejected, saved release metadata accepted.")
    print("Synthetic files removed.")


if __name__ == "__main__":
    main()
