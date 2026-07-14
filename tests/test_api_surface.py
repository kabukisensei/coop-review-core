"""The public API surface: ``__all__`` in every module, the CoopReviewError
hierarchy, and the do-not-break names (issue #8)."""

import importlib
import pkgutil

import pytest

import coop_review_core
from coop_review_core import CoopReviewError
from coop_review_core.config import StandardsError
from coop_review_core.suppressions import BaselineError
from coop_review_core.upgrade import UpgradeError

# Derive the module list from the package itself so a NEWLY-ADDED module can
# never be silently skipped by the star-import / private-leak audit — the way
# the hand-maintained list once skipped the 0.4.0 additions (cliutils, report).
MODULES = ["coop_review_core"] + [
    f"coop_review_core.{info.name}" for info in pkgutil.iter_modules(coop_review_core.__path__)
]


@pytest.mark.parametrize("exc_type", [StandardsError, BaselineError, UpgradeError])
def test_user_facing_errors_share_the_coop_review_base(exc_type):
    assert issubclass(exc_type, CoopReviewError)
    # Re-parenting is backward compatible: `except <Type>:` and broad
    # `except Exception:` handlers in shipped consumers keep working.
    assert issubclass(exc_type, Exception)


def test_coop_review_error_is_catchable_for_each_subclass():
    for exc_type in (StandardsError, BaselineError, UpgradeError):
        with pytest.raises(CoopReviewError):
            raise exc_type("boom")


@pytest.mark.parametrize("name", MODULES)
def test_star_import_exports_exactly_all_and_no_private_names(name):
    module = importlib.import_module(name)
    assert hasattr(module, "__all__"), f"{name} must declare __all__"
    namespace: dict = {}
    exec(f"from {name} import *", namespace)  # noqa: S102 - deliberate star-import audit
    exported = {key for key in namespace if key != "__builtins__"}
    assert exported == set(module.__all__)
    leaked = [key for key in exported if key.startswith("_")]
    assert not leaked, f"{name} leaks private names via *: {leaked}"
    for public in module.__all__:
        assert hasattr(module, public), f"{name}.__all__ names missing attribute {public!r}"


def test_all_mirrors_the_do_not_break_list():
    """Every name on the AGENTS.md do-not-break list (plus the names the shipped
    consumers import at module load) must be in its module's ``__all__``."""
    expected = {
        "coop_review_core": {"CoopReviewError"},
        "coop_review_core.progress": {"Progress", "Tick", "should_enable"},
        "coop_review_core.diagnostics": {"Diagnostic", "SYNTAX_ERROR", "SCAN_EMPTY"},
        "coop_review_core.severity": {"SEVERITIES", "severity_rank", "at_or_above", "fingerprint"},
        "coop_review_core.suppressions": {
            "scan_directives",
            "is_inline_suppressed",
            "scan_syntax_ignores",
            "is_syntax_ignored",
            "baseline_payload",
            "write_baseline",
            "BaselineError",
            "load_baseline",
        },
        "coop_review_core.upgrade": {
            "UpgradeError",
            "DependencyStatus",
            "UpgradePlan",
            "classify_update",
            "is_vcs_spec",
            "build_plan",
            "upgrade_command",
        },
        "coop_review_core.config": {
            "RuleConfig",
            "StandardsError",
            "add_ignores",
            "apply_config",
            "default_config_path",
            "resolve_standards_path",
            "standards_info",
            "load_config_friendly",
            "parse_syntax_errors_knob",
            "SYNTAX_ERROR_MODES",
        },
        # The 0.4.0 shared layers: both shipped consumers import these at module
        # load (coop-sql-review & coop-dax-review cli.py / report.py), so dropping
        # one from __all__ or the module is a do-not-break regression.
        "coop_review_core.cliutils": {
            "display_path",
            "stdio_interactive",
            "use_color",
            "config_write_path",
            "apply_syntax_error_policy",
            "write_extra_report",
            "should_open_report",
            "force_utf8_console",
            "run_upgrade",
            "with_upgrade_options",
        },
        "coop_review_core.report": {
            "BADGE",
            "BADGE_COLOR",
            "ANSI",
            "sty",
            "HTML_STYLE",
            "logo_data_uri",
            "esc",
            "chip",
            "verdict",
            "build_envelope",
            "envelope_text",
            "diagnostic_json",
            "log_text",
            "to_sarif",
            "SARIF_FINGERPRINT_KEY",
        },
    }
    for name, names in expected.items():
        module = importlib.import_module(name)
        missing = names - set(module.__all__)
        assert not missing, f"{name}.__all__ is missing do-not-break names: {sorted(missing)}"
