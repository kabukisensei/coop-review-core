import pytest
import os
import subprocess
from coop_review_core.gitscope import get_changed_files
from coop_review_core.errors import GitScopeError

def test_get_changed_files(tmp_path):
    cwd = str(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=cwd, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=cwd, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=cwd, check=True)
    
    # tracked file
    (tmp_path / "old.sql").write_text("--")
    subprocess.run(["git", "add", "old.sql"], cwd=cwd, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=cwd, check=True)
    
    # modified tracked file
    (tmp_path / "old.sql").write_text("-- modified")
    
    # untracked file
    (tmp_path / "new.sql").write_text("-- new")
    
    # different extension
    (tmp_path / "other.txt").write_text("text")
    
    files = get_changed_files(".sql", ref="HEAD", cwd=cwd)
    assert files == ["new.sql", "old.sql"]

def test_get_changed_files_not_git(tmp_path):
    with pytest.raises(GitScopeError, match="not a git repository"):
        get_changed_files(".sql", cwd=str(tmp_path))
