#!/usr/bin/env python3
"""
Runs one step of a make target with semantic context, a log file and a history entry.

    python3 scripts/make_step.py --target test-unit [--step "1/4 unit tier"] [--context KEY=VALUE ...]
                                 [--outputs PATH ...] [--no-log] -- COMMAND [ARGS...]
    python3 scripts/make_step.py history [--limit 20]
    python3 scripts/make_step.py last

Before the command: the target, its section and purpose (read from the Makefile's own
`## description`, so nothing is written twice), the step, the exact command and the context
(run id, git revision, interpreter, the make variables passed with --context).
While it runs: its output, unchanged, also written to build/logs/<time>-<target>.log.
After it: a digest of what happened (tests passed, coverage, quality gate, links proposed,
files written...), the duration, and on failure the last relevant lines plus a hint.
Every step appends one JSON line to build/logs/history.jsonl (`make logs` shows them).

Standard library only and ASCII output (the project's terminal convention), so it runs before
the virtualenv exists. All steps of one `make` invocation share SEO_MAGUS_RUN_ID, which the
project's Python logs also print, so a run can be followed across steps and log files.
"""

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LOG_DIR = Path("build/logs")
HISTORY = LOG_DIR / "history.jsonl"
RUN_ID_ENV = "SEO_MAGUS_RUN_ID"
TAIL_ON_FAILURE = 15

# Digesters: (label, regex, formatter) - the last match of each label summarizes the step.
DIGESTS: List[Tuple[str, "re.Pattern[str]", str]] = [
    ("tests", re.compile(r"^=+ (.*?(?:passed|failed|error|no tests ran).*?) in ([\d.]+s)"), "{0} in {1}"),
    ("coverage", re.compile(r"^TOTAL\s.*?(\d+(?:\.\d+)?%)\s*$"), "{0} of src/ covered"),
    ("coverage gate", re.compile(r"Coverage failure: (.*)"), "{0}"),
    ("quality gate", re.compile(r"Quality gate (passed|failed)(.*)"), "{0}{1}"),
    ("site health", re.compile(r"Site health: (.*)"), "{0}"),
    ("crawl", re.compile(r"\[\+\] Crawled (\d+ pages in [\d.]+s)"), "{0}"),
    ("links proposed", re.compile(r"Links proposed\s*:\s*(\d+)"), "{0}"),
    ("classifier calls", re.compile(r"Classifier calls\s*:\s*(\d+)"), "{0}"),
    ("growth", re.compile(r"(time ~ n\^[\d.]+, classifier calls ~ n\^[\d.]+)"), "{0}"),
    ("comparison", re.compile(r"^(\S+ -> \S+: (?:direct|indirect).*)$"), "{0}"),
    ("corpus", re.compile(r"^(\S+): (\d+ documents), layers (\[.*?\])"), "{0}: {1}, {2}"),
]
# Counting digests: how many lines fall in each category (e.g. benchmark verdicts per site).
COUNTERS = [
    ("benchmark sites", re.compile(r"\[(OK|X)\] Expected links found"),
     lambda c: f"{c.get('OK', 0)} found every expected link, {c.get('X', 0)} with missing or unexpected links"),
    ("evaluation runs", re.compile(r"^  \S+: (links|classification|ranking)\b(?!.*skipped)"),
     lambda c: f"{sum(c.values())} (" + ", ".join(f"{task} {n}" for task, n in sorted(c.items())) + ")"),
    ("crawl fidelity", re.compile(r'"task": "crawl".*?"coverage": ([\d.]+)'),
     lambda c: ", ".join(f"{n} site(s) at coverage {value}" for value, n in sorted(c.items()))),
    ("failed tests", re.compile(r"^FAILED (\S+)"), lambda c: f"{sum(c.values())}: " + ", ".join(sorted(c)[:3])
     + (" ..." if len(c) > 3 else "")),
]
OUTPUT_PATTERNS = [
    re.compile(r"^(?:report|comparison|export): (\S+)$"),
    re.compile(r"HTML report: (\S+)"),
    re.compile(r"-> (build/\S+|tests/\S+)$"),
    re.compile(r"^(tests/fixtures/\S+\.json)$"),
    re.compile(r"Wrote XML report to (\S+)"),
    re.compile(r"\[\+\] (?:JSON|CSV) export: (\S+)"),
]
HINTS = [
    (re.compile(r"NetworkAccessInUnitTest"), "a unit test opened a socket: mark it @pytest.mark.integration "
                                             "(CONTRIBUTING.md#test-tiers)"),
    (re.compile(r"Coverage failure"), "coverage dropped below COVERAGE_MIN: `make coverage` and open "
                                      "build/coverage/index.html to see the untested lines"),
    (re.compile(r"is stale|run `make fixtures`"), "a saved crawl no longer matches the mock site: `make fixtures`"),
    (re.compile(r"Set CONTACT="), "live sources need CONTACT=you@example.com (Wikimedia User-Agent policy)"),
    (re.compile(r"OfflineCacheMiss|not in the cache"), "the record/replay cache does not hold this request: "
                                                        "run once with network access"),
    (re.compile(r"Name or service not known|Temporary failure in name resolution|URLError"),
     "no network access: live sources cannot be fetched here; replay a cache with OFFLINE=1"),
    (re.compile(r"Address already in use"), "the port is taken: choose another one with PORT=..."),
    (re.compile(r"No such file or directory: '[^']*report\.json'"),
     "no evaluation report there yet: run `make eval-run` (or `make eval`) first"),
    (re.compile(r"No such file or directory: '[^']*\*\.jsonl\.gz'"),
     "no corpus yet: run `make eval-corpora` (offline) or an eval-wikipedia / eval-archive fetch first"),
    (re.compile(r"(?:FAILED|ERROR) tests/"), "rerun only the failures: make {target} ARGS=\"--lf\""),
]


# --------------------------------------------------------------- context


def makefile_target(target: str, makefile: Path) -> Tuple[str, str]:
    """(section, description) of a target, from its `##@ Section` and `target: ... ## description` lines."""
    section, found = "", ("", "")
    if not makefile.is_file():
        return found
    for line in makefile.read_text(encoding="utf-8").splitlines():
        if line.startswith("##@"):
            section = line[3:].strip()
        match = re.match(rf"^{re.escape(target)}:.*?## (.*)$", line)
        if match:
            return section, match.group(1).strip()
    return found


def git_state() -> str:
    try:
        revision = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                  timeout=5).stdout.strip()
        changed = subprocess.run(["git", "status", "--porcelain", "--", "."], capture_output=True, text=True,
                                 timeout=5).stdout.strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return "not a git checkout"
    if not revision:
        return "not a git checkout"
    return revision + (f" + {len(changed)} changed files" if changed else " (clean)")


def interpreter(command: List[str]) -> str:
    """Version of the Python that runs the command (when it is a Python command)."""
    if not command or "python" not in Path(command[0]).name:
        return ""
    try:
        result = subprocess.run([command[0], "-c", "import platform, sys; print(platform.python_version(), sys.prefix)"],
                                capture_output=True, text=True, timeout=10)
        version, _, prefix = result.stdout.strip().partition(" ")
        return f"python {version} ({prefix})" if version else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def run_id() -> str:
    existing = os.environ.get(RUN_ID_ENV)
    if existing:
        return existing
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid() % 10000:04d}"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


# ------------------------------------------------------------------ output


class Console:
    def __init__(self):
        self.color = sys.stdout.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"

    def paint(self, text: str, code: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.color else text


def _size(path: Path) -> str:
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        return f"{len(files)} files"
    size = path.stat().st_size
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def digest(lines: List[str]) -> Tuple[Dict[str, str], List[str]]:
    found: Dict[str, str] = {}
    matches: Dict[str, int] = {}
    counts: Dict[str, Dict[str, int]] = {}
    outputs: List[str] = []
    for line in lines:
        text = line.rstrip()
        for label, pattern, template in DIGESTS:
            match = pattern.search(text)
            if match:
                found[label] = template.format(*[g or "" for g in match.groups()]).strip()
                matches[label] = matches.get(label, 0) + 1
        for label, pattern, _ in COUNTERS:
            match = pattern.search(text)
            if match:
                bucket = counts.setdefault(label, {})
                bucket[match.group(1)] = bucket.get(match.group(1), 0) + 1
        for pattern in OUTPUT_PATTERNS:
            match = pattern.search(text)
            if match and match.group(1) not in outputs:
                outputs.append(match.group(1))
    # A value seen several times (e.g. the site health of several sites) is the last one: say so.
    found = {(f"{label} (last of {matches[label]})" if matches.get(label, 1) > 1 else label): value
             for label, value in found.items()}
    for label, _, formatter in COUNTERS:
        if label in counts:
            found[label] = formatter(counts[label])
    return found, outputs


def relevant_tail(lines: List[str], count: int = TAIL_ON_FAILURE) -> List[str]:
    """The end of the output, preferring the lines that explain a failure."""
    important = [l for l in lines if re.search(r"Error|FAILED|ERROR|Traceback|failed|AssertionError|^E ", l)]
    chosen = important[-count:] if important else lines[-count:]
    return [l.rstrip()[:200] for l in chosen]


# --------------------------------------------------------------------- run


def run_step(args: argparse.Namespace) -> int:
    console = Console()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print("make_step: no command given", file=sys.stderr)
        return 2
    section, purpose = makefile_target(args.target, Path(args.makefile))
    rid = run_id()
    started_at = datetime.now(timezone.utc)
    log_path: Optional[Path] = None
    if not args.no_log:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{args.target}" + (f"-{_slug(args.step)}" if args.step else "")
        log_path = LOG_DIR / f"{name}.log"
    shown = shlex.join(command)
    header = [
        f"==> make {args.target}" + (f"  [{args.step}]" if args.step else "") + f"  (run {rid})",
        f"    purpose : {purpose or '-'}",
        f"    section : {section or '-'}",
        f"    command : {shown}",
        f"    context : git {git_state()}" + (f" | {interpreter(command)}" if interpreter(command) else ""),
    ]
    if args.context:
        header.append("    settings: " + " ".join(args.context))
    if log_path:
        header.append(f"    log     : {log_path}")
    print(console.paint(header[0], "1;36"))
    for line in header[1:]:
        print(line)
    sys.stdout.flush()

    env = dict(os.environ, **{RUN_ID_ENV: rid, "PYTHONUNBUFFERED": "1"})
    lines: List[str] = []
    started = time.monotonic()
    log = log_path.open("w", encoding="utf-8") if log_path else None
    if log:
        log.write("\n".join(header) + f"\n    started : {started_at.isoformat(timespec='seconds')}\n\n")
    interrupted = False
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
                                   encoding="utf-8", errors="replace", bufsize=1)
    except OSError as exc:
        print(console.paint(f"<== make {args.target}: could not start {command[0]}: {exc}", "1;31"))
        return 127
    try:
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            lines.append(line)
            if log:
                log.write(line)
        code = process.wait()
    except KeyboardInterrupt:
        # Ctrl+C reaches the whole process group: give the command a moment to stop on its own,
        # forward the signal only if it is still running, then keep its last words.
        interrupted = True
        try:
            code = process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.send_signal(signal.SIGINT)
            try:
                code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait()
        for line in process.stdout:
            sys.stdout.write(line)
            lines.append(line)
            if log:
                log.write(line)
        code = code or 130
    seconds = time.monotonic() - started

    found, outputs = digest(lines)
    existing: List[Tuple[str, Path]] = []
    seen = set()
    for name in outputs + list(args.outputs):              # one entry per file, however it was written
        path = Path(name)
        if path.exists() and path.resolve() not in seen:
            seen.add(path.resolve())
            shown_name = os.path.relpath(path.resolve()) if path.is_absolute() else name
            existing.append((shown_name, path))
    status = "interrupted" if interrupted else ("OK" if code == 0 else f"FAILED (exit {code})")
    footer = [f"<== make {args.target}" + (f" [{args.step}]" if args.step else "") + f": {status} in {seconds:.1f}s"]
    width = max([16] + [len(label) for label in found])
    footer += [f"    {label:<{width}}: {value}" for label, value in found.items()]
    footer += [f"    {'output':<{width}}: {name} ({_size(path)})" for name, path in existing]
    hints: List[str] = []
    if code != 0 and not interrupted:
        text = "".join(lines)
        hints = [hint.format(target=args.target) for pattern, hint in HINTS if pattern.search(text)]
        tail = relevant_tail(lines)
        if tail:
            footer.append("    last relevant output:")
            footer += [f"      | {line}" for line in tail]
        footer += [f"    {'hint':<{width}}: {hint}" for hint in hints]
    if log_path:
        footer.append(f"    {'full log':<{width}}: {log_path}")
    print(console.paint(footer[0], "1;32" if code == 0 else "1;31"))
    for line in footer[1:]:
        print(line)
    if log:
        log.write("\n" + "\n".join(footer) + "\n")
        log.close()
        with HISTORY.open("a", encoding="utf-8") as history:
            history.write(json.dumps({
                "run": rid, "target": args.target, "step": args.step or "", "started": started_at.isoformat(timespec="seconds"),
                "seconds": round(seconds, 2), "exit": code, "status": status, "digest": found,
                "outputs": [name for name, _ in existing], "log": str(log_path), "command": shown,
            }) + "\n")
    return code


def show_history(limit: int) -> int:
    if not HISTORY.is_file():
        print("No make run recorded yet (build/logs/history.jsonl is created by the first wrapped target).")
        return 0
    records = [json.loads(line) for line in HISTORY.read_text(encoding="utf-8").splitlines() if line.strip()][-limit:]
    print(f"{'started (UTC)':<20} {'run':<24} {'target / step':<40} {'time':>8}  status / digest")
    for r in records:
        name = r["target"] + (f" [{r['step']}]" if r["step"] else "")
        summary = "; ".join(f"{k}: {v}" for k, v in list(r.get("digest", {}).items())[:2])
        print(f"{r['started'][:19]:<20} {r['run'][:24]:<24} {name[:40]:<40} {r['seconds']:>7.1f}s  {r['status']}"
              + (f" | {summary}" if summary else ""))
    print(f"\nLogs: {LOG_DIR}/ (full output of each step); history: {HISTORY}")
    return 0


def show_last() -> int:
    if not HISTORY.is_file():
        print("No make run recorded yet.")
        return 0
    last = json.loads(HISTORY.read_text(encoding="utf-8").splitlines()[-1])
    path = Path(last["log"])
    print(f"Last step: make {last['target']} {('[' + last['step'] + ']') if last['step'] else ''} -> {last['status']}")
    if path.is_file():
        print(path.read_text(encoding="utf-8")[-6000:])
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["history"]:
        parser = argparse.ArgumentParser(prog="make_step.py history")
        parser.add_argument("--limit", type=int, default=20)
        return show_history(parser.parse_args(argv[1:]).limit)
    if argv[:1] == ["last"]:
        return show_last()
    parser = argparse.ArgumentParser(prog="make_step.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", required=True)
    parser.add_argument("--step", default="")
    parser.add_argument("--context", nargs="*", default=[], metavar="KEY=VALUE", help="make variables worth showing")
    parser.add_argument("--outputs", nargs="*", default=[], help="files the step produces")
    parser.add_argument("--makefile", default="Makefile")
    parser.add_argument("--no-log", action="store_true", help="no log file or history entry (e.g. for clean)")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return run_step(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
