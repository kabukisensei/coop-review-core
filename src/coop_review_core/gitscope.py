import subprocess
import os
from typing import List, Optional
from coop_review_core.errors import GitScopeError

def get_changed_files(ext: str, ref: Optional[str] = "HEAD", cwd: Optional[str] = None) -> List[str]:
    """
    Get a list of changed files with the given extension since `ref` (defaults to HEAD).
    Includes untracked files. Returns paths relative to cwd.
    Raises GitScopeError if not in a git repository.
    """
    if cwd is None:
        cwd = os.getcwd()

    # Check if we are inside a git repository
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise GitScopeError("not a git repository (or git is not installed)")

    if ref is None:
        ref = "HEAD"

    # diff tracked files
    cmd_diff = ["git", "diff", "--name-only", "--diff-filter=ACMR", "-z", ref, "--", f"*{ext}"]
    try:
        res_diff = subprocess.run(
            cmd_diff, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        )
        diff_out = res_diff.stdout.decode("utf-8").split("\0")
    except subprocess.CalledProcessError as e:
        raise GitScopeError(f"git diff failed: {e.stderr.decode('utf-8').strip()}")

    # untracked files
    cmd_untracked = ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", f"*{ext}"]
    try:
        res_untracked = subprocess.run(
            cmd_untracked, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        )
        untracked_out = res_untracked.stdout.decode("utf-8").split("\0")
    except subprocess.CalledProcessError as e:
        raise GitScopeError(f"git ls-files failed: {e.stderr.decode('utf-8').strip()}")

    # combine and filter empty strings, then filter to paths that still exist
    all_files = set(f for f in diff_out + untracked_out if f)
    existing_files = [f for f in all_files if os.path.isfile(os.path.join(cwd, f))]
    
    return sorted(existing_files)
