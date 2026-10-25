import argparse
import json
import sys

from . import __version__
from .core import InputError, compile_contract, evaluate, github_assets, local_assets, read_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate exact release-asset slots offline.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("contract", help="Version 1 JSON contract")
    parser.add_argument(
        "--release", required=True, help="Exact release tag/token substituted as {version}"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--directory", help="Flat staging directory containing regular files only")
    source.add_argument("--github-json", help="Saved complete GitHub release API object")
    parser.add_argument("--max-findings", type=int, default=1000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        slots, allow = compile_contract(read_json(args.contract), args.release)
        tag = None
        if args.directory:
            assets = local_assets(args.directory)
        else:
            assets, tag = github_assets(read_json(args.github_json))
        result = evaluate(
            slots,
            assets,
            args.release,
            allow_unexpected=allow,
            github_tag=tag,
            max_findings=args.max_findings,
        )
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=True))
        else:
            print("PASS" if result["ok"] else "REVIEW")
            print(json.dumps(result["summary"], ensure_ascii=True))
            for item in result["findings"]:
                print(json.dumps(item, ensure_ascii=True))
            if result["omitted_findings"]:
                print(f"Additional findings omitted: {result['omitted_findings']}")
        return 0 if result["ok"] else 1
    except (InputError, OSError, ValueError, RecursionError, OverflowError) as exc:
        print(
            json.dumps({"error": str(exc), "complete": False}, ensure_ascii=True), file=sys.stderr
        )
        return 2
