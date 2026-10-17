"""Explicit review of exact warning occurrences in one output snapshot."""

from __future__ import annotations

from collections import Counter
import json
import re

from .score_document import ScoreError

DIAGNOSTIC_FIELDS = {"code", "severity", "location", "reason"}


def warning_identity(diagnostic: dict) -> dict:
    return {key: diagnostic[key] for key in sorted(DIAGNOSTIC_FIELDS)}


def diagnostic_signature(diagnostic: dict) -> str:
    return json.dumps(warning_identity(diagnostic), sort_keys=True)


class WarningAcknowledgments:
    """Consume reviewed warning occurrences; never change diagnostic severity."""

    def __init__(self, value: object):
        if (
            not isinstance(value, dict)
            or set(value) != {"outputSha256", "entries"}
            or not isinstance(value["outputSha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["outputSha256"])
            or not isinstance(value["entries"], list)
            or not value["entries"]
        ):
            raise ScoreError(
                "invalid-warning-acknowledgment",
                "Expected outputSha256 and a nonempty entries array.",
            )
        self.value = value
        self.remaining: Counter[str] = Counter()
        for entry in value["entries"]:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"diagnostic", "rationale"}
                or not isinstance(entry["rationale"], str)
                or not entry["rationale"].strip()
            ):
                raise ScoreError(
                    "invalid-warning-acknowledgment",
                    "Each entry requires an exact diagnostic and a nonempty review rationale.",
                )
            diagnostic = entry["diagnostic"]
            if (
                not isinstance(diagnostic, dict)
                or set(diagnostic) != DIAGNOSTIC_FIELDS
                or diagnostic["severity"] != "warning"
                or not isinstance(diagnostic["location"], dict)
                or not all(
                    isinstance(diagnostic[key], str) and diagnostic[key]
                    for key in ("code", "reason")
                )
            ):
                raise ScoreError(
                    "invalid-warning-acknowledgment",
                    "Only exact code, severity=warning, full location and reason may be acknowledged.",
                )
            self.remaining[diagnostic_signature(diagnostic)] += 1

    def check_output(self, output_hash: str) -> None:
        if self.value["outputSha256"] != output_hash:
            raise ScoreError(
                "stale-warning-acknowledgment",
                "Acknowledgment SHA-256 does not match the complete output snapshot.",
            )

    def consume(self, diagnostic: dict) -> bool:
        if diagnostic["severity"] != "warning":
            return False
        key = diagnostic_signature(diagnostic)
        if not self.remaining[key]:
            return False
        self.remaining[key] -= 1
        return True

    def finish(self) -> None:
        if any(self.remaining.values()):
            raise ScoreError(
                "unused-warning-acknowledgment",
                "Every acknowledgment must match one new-or-unmatched warning occurrence exactly.",
            )
