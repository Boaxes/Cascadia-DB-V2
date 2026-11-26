"""Phase gate for the Cascadia DB V2 agent.

The work runs in five phases (see CLAUDE.md). Each phase may only write its own
files, and only Brandon approves a phase, by adding a line such as
"Phase 1: Approved 2026-11-27" to docs/workflow/APPROVALS.md.

Modes:
  (stdin JSON)   Claude Code PreToolUse hook. Exit 2 blocks the tool call.
  --status       Print the current phase and what it may write (SessionStart hook).
  --staged       Git pre-commit check: every staged file must be writable now.
"""
import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # from the file itself: CLAUDE_PROJECT_DIR can be stale
V1 = ROOT.parent / "Cascadia-DB"
APPROVALS = "docs/workflow/APPROVALS.md"

PHASES = {
    1: ("Spec And Mockup", "docs/workflow/phase-1-spec-and-mockup.md", ["docs/spec/", "mockups/", "docs/ui/"]),
    2: ("Schema And DuckLake", "docs/workflow/phase-2-schema-and-ducklake.md", ["docs/schema/"]),
    3: ("Quality Gates", "docs/workflow/phase-3-quality-gates.md", ["docs/quality/"]),
    4: ("Scaffolding", "docs/workflow/phase-4-scaffolding.md", None),  # None: the rest of the repo
    5: ("Build", "docs/workflow/phase-5-build.md", None),
}
ALWAYS = ["docs/workflow/STATUS.md", "docs/workflow/questions-log.md",
          "docs/workflow/change-requests.md", "scratch/"]
# Never written by the agent, in any phase.
PROTECTED = [APPROVALS, ".claude/hooks/", ".githooks/pre-commit", ".env", "Data/", "V1/", "CLAUDE.md",
             "V2Spec.MD"] + [doc for _, doc, _ in PHASES.values()]
SETTINGS = ".claude/settings.json"

BASH_RULES = [
    (r"APPROVALS\.md", "Only Brandon edits docs/workflow/APPROVALS.md."),
    (r"phase_gate\.py(?!\s+--status\s*$)|\.githooks","The phase gate and git hooks are not the agent's to change or run."),
    (r"--no-verify|core\.hooksPath|disableAllHooks", "Git and Claude hooks may not be skipped."),
    (r"(^|[\s/\\\"'=])\.env(?![\w.])", "The .env file holds live credentials and is off limits."),
    (r"export_databases\.py|SEDB_|SQLSERVER_", "The agent never connects to the live databases."),
    (r"\bgh\s+pr\s+merge\b", "Only Brandon merges pull requests."),
]


def approved():
    path = ROOT / APPROVALS
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return {int(n) for n in re.findall(r"(?im)^\s*Phase\s+([1-5])\s*:\s*Approved\b", text)}


def current_phase():
    done = approved()
    return next((n for n in PHASES if n not in done), None)


def rel(path):
    """Repo-relative POSIX path, or None when the path is outside the repo."""
    p = Path(path)
    p = (p if p.is_absolute() else ROOT / p).resolve()
    a, b = os.path.normcase(str(p)), os.path.normcase(str(ROOT))
    if a != b and not a.startswith(b + os.sep):
        return None
    return p.relative_to(ROOT).as_posix()


def under(r, paths):
    """Entries ending in / are folders; anything else is one exact file."""
    return any(r.startswith(x) or r == x.rstrip("/") if x.endswith("/") else r == x for x in paths)


def write_problem(path):
    """Why the agent may not write this path now, or None if it may."""
    r = rel(path)
    if r is None:
        v1 = os.path.normcase(str(V1.resolve()))
        return "The original V1 checkout (../Cascadia-DB) is read-only. Read V1/ instead." if os.path.normcase(str(Path(path).resolve())).startswith(v1) else None
    if under(r, PROTECTED):
        return f"{r} is protected: only Brandon changes it."
    if under(r, ALWAYS) or r == SETTINGS:
        return None
    phase = current_phase()
    if phase is None:
        return None
    name, _, own = PHASES[phase]
    frozen = [p for n in range(1, phase) for p in (PHASES[n][2] or [])]
    if own is None:
        return f"{r} belongs to an approved phase and is frozen. Log it in docs/workflow/change-requests.md and ask." if under(r, frozen) else None
    if under(r, own):
        return None
    return (f"Phase {phase} ({name}) may only write {', '.join(own)} and the workflow logs. "
            f"{r} waits for a later phase, or for a change request if it is frozen.")


def settings_problem(tool, inp):
    """settings.json may change from Phase 4 on, but the gate hook must stay in it."""
    if current_phase() not in (None, 4, 5):
        return "Claude settings change only from Phase 4, as part of the approved quality gates."
    path = ROOT / SETTINGS
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if tool == "Write":
        text = inp.get("content", "")
    for e in inp.get("edits") or [inp]:
        old, new = e.get("old_string", ""), e.get("new_string", "")
        text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
    return None if "phase_gate.py" in text else "The phase gate hook must stay in .claude/settings.json."


def bash_problem(cmd):
    for pattern, why in BASH_RULES:
        if re.search(pattern, cmd):
            return why
    if re.search(r"\bgit\s+(commit|merge|push|rebase|reset)\b", cmd):
        branch = subprocess.run(["git", "-C", str(ROOT), "branch", "--show-current"],
                                capture_output=True, text=True).stdout.strip()
        if branch in ("main", "master") or re.search(r"\bgit\s+push\b.*\b(main|master)\b", cmd):
            return "The agent works on a phase branch. main changes only when Brandon merges after previewing locally."
    return None


def hook():
    data = json.load(sys.stdin)
    tool, inp = data.get("tool_name", ""), data.get("tool_input") or {}
    if tool in ("Bash", "PowerShell"):
        problem = bash_problem(inp.get("command", ""))
    else:
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        problem = write_problem(path) if path else None
        if not problem and path and rel(path) == SETTINGS:
            problem = settings_problem(tool, inp)
    if problem:
        print(f"Phase gate: {problem}", file=sys.stderr)
        sys.exit(2)


def status():
    phase = current_phase()
    if phase is None:
        print("Phase gate: all five phases are approved.")
        return
    name, doc, own = PHASES[phase]
    print(f"Phase gate: current phase is {phase} ({name}). Read {doc} before doing anything.")
    print(f"Writable now: {', '.join(own) if own else 'the repo, except frozen and protected paths'}; "
          f"plus {', '.join(ALWAYS)}.")
    print(f"Approved so far: {sorted(approved()) or 'none'}. Only Brandon edits {APPROVALS}.")


def staged():
    if subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "-q", "HEAD"],
                      capture_output=True).returncode != 0:
        return  # the first commit sets the workflow up, so no phase applies yet
    out = subprocess.run(["git", "-C", str(ROOT), "diff", "--cached", "--name-only", "--diff-filter=ACMRD"],
                         capture_output=True, text=True, check=True).stdout.split()
    # Brandon commits approvals and protected files himself, so only phase rules apply here.
    bad = [(f, p) for f in out if not under(f, PROTECTED) and (p := write_problem(ROOT / f))]
    for f, p in bad:
        print(f"Phase gate: {p}", file=sys.stderr)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    {"--status": status, "--staged": staged}.get(sys.argv[1] if len(sys.argv) > 1 else "", hook)()
