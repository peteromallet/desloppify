"""Tests for structured reflect disposition ledger parsing and organize validation."""

from __future__ import annotations

from desloppify.app.commands.plan.triage.validation.core import (
    ReflectDisposition,
    parse_reflect_dispositions,
)
from desloppify.app.commands.plan.triage.validation.organize_policy import (
    validate_organize_against_reflect_ledger,
)

# ---------------------------------------------------------------------------
# parse_reflect_dispositions
# ---------------------------------------------------------------------------


class TestParseReflectDispositions:
    """Tests for parsing the Coverage Ledger into structured dispositions."""

    def test_basic_cluster_and_skip(self):
        report = (
            "Some preamble.\n"
            "## Coverage Ledger\n"
            '- aabb1122 -> cluster "triage-runner-simplification"\n'
            '- ccdd3344 -> skip "core-runner-already-collapsed"\n'
            "## Next Section\n"
        )
        valid_ids = {
            "review::aabb1122",
            "review::ccdd3344",
        }
        result = parse_reflect_dispositions(report, valid_ids)
        assert len(result) == 2
        assert result[0] == ReflectDisposition(
            issue_id="review::aabb1122",
            decision="cluster",
            target="triage-runner-simplification",
        )
        assert result[1] == ReflectDisposition(
            issue_id="review::ccdd3344",
            decision="permanent_skip",
            target="core-runner-already-collapsed",
        )

    def test_empty_without_ledger_section(self):
        report = "Some report without a coverage ledger section."
        valid_ids = {"review::aabb1122"}
        result = parse_reflect_dispositions(report, valid_ids)
        assert result == []

    def test_full_id_match(self):
        report = (
            "## Coverage Ledger\n"
            '- review::aabb1122 -> cluster "my-cluster"\n'
        )
        valid_ids = {"review::aabb1122"}
        result = parse_reflect_dispositions(report, valid_ids)
        assert len(result) == 1
        assert result[0].issue_id == "review::aabb1122"

    def test_single_quotes(self):
        report = (
            "## Coverage Ledger\n"
            "- aabb1122 -> cluster 'my-cluster'\n"
        )
        valid_ids = {"review::aabb1122"}
        result = parse_reflect_dispositions(report, valid_ids)
        assert len(result) == 1
        assert result[0].target == "my-cluster"

    def test_skip_synonyms_normalized(self):
        """dismiss, defer, drop, remove should all map to permanent_skip."""
        for keyword in ("skip", "dismiss", "defer", "drop", "remove"):
            report = (
                "## Coverage Ledger\n"
                f'- aabb1122 -> {keyword} "some-reason"\n'
            )
            valid_ids = {"review::aabb1122"}
            result = parse_reflect_dispositions(report, valid_ids)
            assert len(result) == 1, f"Failed for keyword: {keyword}"
            assert result[0].decision == "permanent_skip", f"Failed for keyword: {keyword}"

    def test_case_insensitive_header(self):
        report = (
            "## coverage ledger\n"
            '- aabb1122 -> cluster "my-cluster"\n'
        )
        valid_ids = {"review::aabb1122"}
        result = parse_reflect_dispositions(report, valid_ids)
        assert len(result) == 1

    def test_stops_at_next_section(self):
        report = (
            "## Coverage Ledger\n"
            '- aabb1122 -> cluster "my-cluster"\n'
            "## Strategy\n"
            '- ccdd3344 -> cluster "other-cluster"\n'
        )
        valid_ids = {"review::aabb1122", "review::ccdd3344"}
        result = parse_reflect_dispositions(report, valid_ids)
        assert len(result) == 1
        assert result[0].issue_id == "review::aabb1122"

    def test_unknown_ids_ignored(self):
        report = (
            "## Coverage Ledger\n"
            '- aabb1122 -> cluster "my-cluster"\n'
            '- unknown1 -> skip "reason"\n'
        )
        valid_ids = {"review::aabb1122"}
        result = parse_reflect_dispositions(report, valid_ids)
        assert len(result) == 1

    def test_backtick_wrapped_ids(self):
        report = (
            "## Coverage Ledger\n"
            '- `aabb1122` -> cluster "my-cluster"\n'
        )
        valid_ids = {"review::aabb1122"}
        result = parse_reflect_dispositions(report, valid_ids)
        assert len(result) == 1

    def test_bracket_wrapped_ids(self):
        report = (
            "## Coverage Ledger\n"
            '- [aabb1122] -> cluster "my-cluster"\n'
        )
        valid_ids = {"review::aabb1122"}
        result = parse_reflect_dispositions(report, valid_ids)
        assert len(result) == 1

    def test_ambiguous_short_ids_require_disambiguated_tokens(self):
        report = (
            "## Coverage Ledger\n"
            '- review::src/alpha.py::arch::shared_util -> cluster "alpha-fixes"\n'
            '- review::src/beta.py::arch::shared_util -> cluster "beta-fixes"\n'
        )
        valid_ids = {
            "review::src/beta.py::arch::shared_util",
            "review::src/alpha.py::arch::shared_util",
        }
        result = parse_reflect_dispositions(report, valid_ids)
        assert result == [
            ReflectDisposition(
                issue_id="review::src/alpha.py::arch::shared_util",
                decision="cluster",
                target="alpha-fixes",
            ),
            ReflectDisposition(
                issue_id="review::src/beta.py::arch::shared_util",
                decision="cluster",
                target="beta-fixes",
            ),
        ]

    def test_ambiguous_short_ids_are_not_resolved_by_order(self):
        report = (
            "## Coverage Ledger\n"
            '- shared_util -> cluster "alpha-fixes"\n'
            '- shared_util -> cluster "beta-fixes"\n'
        )
        valid_ids = {
            "review::src/beta.py::arch::shared_util",
            "review::src/alpha.py::arch::shared_util",
        }
        result = parse_reflect_dispositions(report, valid_ids)
        assert result == []


# ---------------------------------------------------------------------------
# validate_organize_against_reflect_ledger
# ---------------------------------------------------------------------------


class TestValidateOrganizeAgainstReflectLedger:
    """Tests for checking plan state matches reflect dispositions."""

    def _make_plan(
        self,
        *,
        clusters: dict | None = None,
        skipped: dict | None = None,
    ) -> dict:
        return {
            "clusters": clusters or {},
            "skipped": skipped or {},
        }

    def _make_stages(self, ledger: list[dict]) -> dict:
        return {
            "reflect": {
                "stage": "reflect",
                "report": "...",
                "disposition_ledger": ledger,
            },
        }

    def test_no_ledger_legacy_compat(self):
        """Old runs without a ledger should pass validation."""
        plan = self._make_plan()
        stages = {"reflect": {"stage": "reflect", "report": "..."}}
        result = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert result == []

    def test_empty_ledger(self):
        plan = self._make_plan()
        stages = self._make_stages([])
        result = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert result == []

    def test_all_dispositions_match(self):
        ledger = [
            {"issue_id": "review::aabb1122", "decision": "cluster", "target": "my-cluster"},
            {"issue_id": "review::ccdd3344", "decision": "permanent_skip", "target": "already-done"},
        ]
        plan = self._make_plan(
            clusters={
                "my-cluster": {
                    "issue_ids": ["review::aabb1122"],
                    "description": "test",
                },
            },
            skipped={
                "review::ccdd3344": {"kind": "permanent"},
            },
        )
        stages = self._make_stages(ledger)
        result = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert result == []

    def test_skip_but_clustered(self):
        """Reflect said skip, but issue is in a cluster."""
        ledger = [
            {"issue_id": "review::aabb1122", "decision": "permanent_skip", "target": "reason"},
        ]
        plan = self._make_plan(
            clusters={
                "my-cluster": {
                    "issue_ids": ["review::aabb1122"],
                    "description": "test",
                },
            },
        )
        stages = self._make_stages(ledger)
        result = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert len(result) == 1
        assert result[0].expected_decision == "permanent_skip"
        assert "clustered" in result[0].actual_state

    def test_cluster_but_skipped(self):
        """Reflect said cluster, but issue is skipped."""
        ledger = [
            {"issue_id": "review::aabb1122", "decision": "cluster", "target": "my-cluster"},
        ]
        plan = self._make_plan(
            skipped={
                "review::aabb1122": {"kind": "permanent"},
            },
        )
        stages = self._make_stages(ledger)
        result = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert len(result) == 1
        assert result[0].expected_decision == "cluster"
        assert "skipped" in result[0].actual_state

    def test_cluster_a_but_cluster_b(self):
        """Reflect said cluster A, but issue is in cluster B."""
        ledger = [
            {"issue_id": "review::aabb1122", "decision": "cluster", "target": "cluster-a"},
        ]
        plan = self._make_plan(
            clusters={
                "cluster-b": {
                    "issue_ids": ["review::aabb1122"],
                    "description": "test",
                },
            },
        )
        stages = self._make_stages(ledger)
        result = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert len(result) == 1
        assert result[0].expected_decision == "cluster"
        assert "cluster-b" in result[0].actual_state
        assert "cluster-a" in result[0].actual_state

    def test_cluster_not_in_any(self):
        """Reflect said cluster, but issue is not in any cluster."""
        ledger = [
            {"issue_id": "review::aabb1122", "decision": "cluster", "target": "my-cluster"},
        ]
        plan = self._make_plan()
        stages = self._make_stages(ledger)
        result = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert len(result) == 1
        assert "not in any cluster" in result[0].actual_state

    def test_skip_not_skipped_not_clustered(self):
        """Reflect said skip, but issue is neither skipped nor clustered."""
        ledger = [
            {"issue_id": "review::aabb1122", "decision": "permanent_skip", "target": "reason"},
        ]
        plan = self._make_plan()
        stages = self._make_stages(ledger)
        result = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert len(result) == 1
        assert "not skipped" in result[0].actual_state

    def test_auto_clusters_ignored(self):
        """Auto-clusters should not count as cluster membership."""
        ledger = [
            {"issue_id": "review::aabb1122", "decision": "cluster", "target": "my-cluster"},
        ]
        plan = self._make_plan(
            clusters={
                "auto-cluster": {
                    "auto": True,
                    "issue_ids": ["review::aabb1122"],
                },
            },
        )
        stages = self._make_stages(ledger)
        result = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert len(result) == 1

    def test_multiple_mismatches(self):
        ledger = [
            {"issue_id": "review::aabb1122", "decision": "permanent_skip", "target": "reason-a"},
            {"issue_id": "review::ccdd3344", "decision": "cluster", "target": "cluster-x"},
            {"issue_id": "review::eeff5566", "decision": "cluster", "target": "cluster-y"},
        ]
        plan = self._make_plan(
            clusters={
                "cluster-x": {
                    "issue_ids": ["review::aabb1122"],  # wrong: should be skipped
                    "description": "test",
                },
                # ccdd3344 missing from cluster-x
                # eeff5566 missing from cluster-y
            },
        )
        stages = self._make_stages(ledger)
        result = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Round-trip: parse -> validate
# ---------------------------------------------------------------------------


class TestLedgerRoundTrip:
    """Integration test: parse ledger from prose, then validate against plan."""

    def test_parsed_ledger_validates_matching_plan(self):
        report = (
            "## Coverage Ledger\n"
            '- aabb1122 -> cluster "refactor-batch"\n'
            '- ccdd3344 -> skip "already-collapsed"\n'
            "## Strategy\n"
        )
        valid_ids = {"review::aabb1122", "review::ccdd3344"}
        ledger = parse_reflect_dispositions(report, valid_ids)
        assert len(ledger) == 2

        plan = {
            "clusters": {
                "refactor-batch": {
                    "issue_ids": ["review::aabb1122"],
                    "description": "Refactor batch processing",
                },
            },
            "skipped": {
                "review::ccdd3344": {"kind": "permanent"},
            },
        }
        stages = {
            "reflect": {
                "stage": "reflect",
                "report": report,
                "disposition_ledger": ledger,
            },
        }
        mismatches = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert mismatches == []

    def test_parsed_ledger_detects_drift(self):
        report = (
            "## Coverage Ledger\n"
            '- aabb1122 -> skip "already-collapsed"\n'
            "## Strategy\n"
        )
        valid_ids = {"review::aabb1122"}
        ledger = parse_reflect_dispositions(report, valid_ids)

        # But plan still has it clustered (the bug this feature prevents)
        plan = {
            "clusters": {
                "my-cluster": {
                    "issue_ids": ["review::aabb1122"],
                    "description": "test",
                },
            },
            "skipped": {},
        }
        stages = {
            "reflect": {
                "stage": "reflect",
                "report": report,
                "disposition_ledger": ledger,
            },
        }
        mismatches = validate_organize_against_reflect_ledger(
            plan=plan, stages=stages,
        )
        assert len(mismatches) == 1
        assert mismatches[0].expected_decision == "permanent_skip"
        assert "clustered" in mismatches[0].actual_state
