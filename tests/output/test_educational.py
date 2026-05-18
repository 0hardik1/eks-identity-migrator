"""Tests for output/educational.py — short teaching renderables per command.

These renderables print to stderr by the *caller*; the renderer itself just
returns a Rich `Group`. We assert key teaching phrases (IRSA, OIDC, Pod
Identity, phase verbs) appear, and that ``set_quiet(True)`` reliably
silences the output.
"""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest
from rich.console import Console

from eks_identity_migrator.output import educational


def _render(renderable: object) -> str:
    buf = io.StringIO()
    Console(file=buf, no_color=True, width=120, force_terminal=False).print(renderable)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _reset_quiet() -> None:
    # Ensure each test starts with quiet=False.
    educational.set_quiet(False)


class TestAuditEducation:
    def test_intro_explains_irsa_and_oidc(self) -> None:
        out = _render(educational.audit_intro())
        assert "IRSA" in out
        assert "OIDC" in out
        # The user should learn the goal of the run.
        assert "Pod Identity" in out

    def test_intro_names_the_annotation(self) -> None:
        out = _render(educational.audit_intro())
        assert "eks.amazonaws.com/role-arn" in out

    def test_outro_includes_risk_legend(self) -> None:
        out = _render(educational.audit_outro())
        for word in ("green", "yellow", "red", "gray"):
            assert word in out.lower()

    def test_outro_suggests_next_command(self) -> None:
        out = _render(educational.audit_outro())
        # Whichever phrasing — the user should leave knowing the next command.
        assert "plan" in out.lower()


class TestPlanEducation:
    def test_intro_explains_plan_yaml_and_phases(self) -> None:
        out = _render(educational.plan_intro(strategy="append"))
        # Three phases mentioned somehow.
        assert "trust" in out.lower()
        assert "association" in out.lower()
        assert "cleanup" in out.lower()

    def test_intro_distinguishes_append_vs_replace(self) -> None:
        append = _render(educational.plan_intro(strategy="append"))
        replace = _render(educational.plan_intro(strategy="replace"))
        # Strategy-specific text should differ.
        assert append != replace


class TestApplyEducation:
    @pytest.mark.parametrize(
        ("phase", "keyword"),
        [
            ("trust", "trust policy"),
            ("association", "association"),
            ("cleanup", "annotation"),
        ],
    )
    def test_phase_intro_has_phase_specific_keyword(self, phase: str, keyword: str) -> None:
        out = _render(educational.apply_phase_intro(phase=phase))
        assert keyword.lower() in out.lower()

    def test_phase_intro_notes_journal(self) -> None:
        # Reversibility is the key safety property.
        out = _render(educational.apply_phase_intro(phase="trust"))
        assert "journal" in out.lower() or "reversible" in out.lower() or "rollback" in out.lower()


class TestVerifyEducation:
    def test_verify_intro_explains_env_var_signal(self) -> None:
        out = _render(educational.verify_intro())
        # IRSA pods have AWS_WEB_IDENTITY_TOKEN_FILE; Pod Identity pods have AWS_CONTAINER_CREDENTIALS_FULL_URI.
        assert "AWS_WEB_IDENTITY_TOKEN_FILE" in out or "AWS_CONTAINER_CREDENTIALS" in out


class TestRollbackEducation:
    def test_rollback_intro_mentions_journal(self) -> None:
        out = _render(educational.rollback_intro())
        assert "journal" in out.lower()


class TestMigrateEducation:
    def test_migrate_intro_says_green_only(self) -> None:
        out = _render(educational.migrate_intro())
        assert "green" in out.lower()


class TestQuietMode:
    @pytest.mark.parametrize(
        "renderable_factory",
        [
            lambda: educational.audit_intro(),
            lambda: educational.audit_outro(),
            lambda: educational.plan_intro(strategy="append"),
            lambda: educational.apply_phase_intro(phase="trust"),
            lambda: educational.verify_intro(),
            lambda: educational.rollback_intro(),
            lambda: educational.migrate_intro(),
        ],
    )
    def test_quiet_silences_all_renderers(self, renderable_factory: Callable[[], object]) -> None:
        educational.set_quiet(True)
        out = _render(renderable_factory())
        # Quiet mode renders something empty (no teaching text). Allow whitespace.
        assert out.strip() == ""


class TestSetQuietGlobalEffect:
    def test_set_quiet_toggles_in_both_directions(self) -> None:
        educational.set_quiet(True)
        assert _render(educational.audit_intro()).strip() == ""
        educational.set_quiet(False)
        assert "IRSA" in _render(educational.audit_intro())
