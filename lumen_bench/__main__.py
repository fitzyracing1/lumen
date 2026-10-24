#!/usr/bin/env python3
"""CLI for the Lumen bug benchmark. See `python3 -m lumen_bench --help`."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lumen_bench import (RESULTS_DIR, format_markdown, make_backend,
                         preflight, run_benchmark)
from lumen_memory import Memory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m lumen_bench",
        description="Run Lumen's coding mode on the bug fixtures and report "
                    "fixed rate, wrong fixes (vs hidden held-out tests), "
                    "cheats caught, and withholds.")
    parser.add_argument("--model", default="stub",
                        help="stub (default) | amalia | openai | openai:<model-name> "
                             "(openai:<name> defaults to http://localhost:11434/v1, "
                             "i.e. a local Ollama)")
    parser.add_argument("--base-url", default=None,
                        help="override the backend base URL")
    parser.add_argument("--fixtures", default=None,
                        help="comma-separated fixture names (default: all)")
    parser.add_argument("--max-cycles", type=int, default=4)
    parser.add_argument("--test-timeout", type=float, default=60.0)
    parser.add_argument("--memory", default=None, metavar="PATH",
                        help="shared memory store across fixtures (default: off)")
    parser.add_argument("--reset-memory", action="store_true",
                        help="wipe the --memory store before running")
    parser.add_argument("--out", default=None, metavar="PREFIX",
                        help="write PREFIX.json and PREFIX.md "
                             "(default: bench/results/<model>[-mem])")
    parser.add_argument("--check-only", action="store_true",
                        help="only check backend reachability, then exit")
    args = parser.parse_args(argv)

    model = make_backend(args.model, base_url=args.base_url)
    ok, message = preflight(model)
    print(message)
    if not ok:
        return 2
    if args.check_only:
        return 0

    memory = None
    if args.memory:
        memory = Memory(args.memory)
        if args.reset_memory:
            memory.reset()
            print(f"memory reset: {args.memory}")
    elif args.reset_memory:
        parser.error("--reset-memory requires --memory PATH")

    only = [f.strip() for f in args.fixtures.split(",")] if args.fixtures else None
    report = run_benchmark(model, max_cycles=args.max_cycles,
                           test_timeout=args.test_timeout, memory=memory,
                           only=only,
                           progress=lambda msg: print(msg, flush=True))

    if args.out:
        prefix = Path(args.out)
    else:
        slug = re.sub(r"[^a-z0-9.]+", "-", report["model"].lower()).strip("-")
        prefix = RESULTS_DIR / (slug + ("-mem" if memory else ""))
    prefix.parent.mkdir(parents=True, exist_ok=True)
    markdown = format_markdown(report)
    prefix.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    prefix.with_suffix(".md").write_text(markdown)
    print()
    print(markdown)
    print(f"wrote {prefix.with_suffix('.json')} and {prefix.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
