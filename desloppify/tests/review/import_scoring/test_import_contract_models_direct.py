"""Direct tests for typed review import contract models."""

from __future__ import annotations

from desloppify.intelligence.review.importing.contracts import (
    AssessmentImportPolicyModel,
    AssessmentProvenanceModel,
)


def test_assessment_provenance_model_round_trip():
    model = AssessmentProvenanceModel.from_mapping(
        {
            "trusted": True,
            "reason": "trusted blind subagent provenance",
            "import_file": "findings.json",
            "runner": "claude",
            "packet_path": "/tmp/review_packet_blind.json",
            "packet_sha256": "a" * 64,
        }
    )
    dumped = model.to_dict()
    assert dumped["trusted"] is True
    assert dumped["runner"] == "claude"
    assert dumped["packet_path"] == "/tmp/review_packet_blind.json"


def test_assessment_import_policy_model_round_trip():
    model = AssessmentImportPolicyModel.from_mapping(
        {
            "assessments_present": True,
            "assessment_count": 2,
            "trusted": True,
            "mode": "trusted_internal",
            "reason": "trusted internal run-batches import",
            "provenance": {
                "trusted": True,
                "reason": "trusted blind subagent provenance",
                "import_file": "findings.json",
            },
        }
    )
    dumped = model.to_dict()
    assert dumped["mode"] == "trusted_internal"
    assert dumped["assessment_count"] == 2
    assert dumped["provenance"]["trusted"] is True
