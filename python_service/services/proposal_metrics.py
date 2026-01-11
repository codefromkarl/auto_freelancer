"""
Proposal Metrics Collection Module

Tracks and analyzes proposal generation quality metrics.
"""

import json
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ProposalMetrics:
    """
    Single proposal generation metrics

    Attributes:
        proposal_id: Unique identifier for the proposal
        project_id: Associated project ID
        proposal_length: Character count of the proposal
        word_count: Word count of the proposal
        has_question: Whether the proposal contains a question mark
        has_markdown_headers: Whether the proposal contains markdown headers
        forbidden_phrases_count: Count of forbidden phrases found
        validation_passed: Whether validation passed
        validation_issues: List of validation issues
        generation_time_ms: Generation time in milliseconds
        model_used: LLM model used for generation
        timestamp: When the proposal was generated
    """

    proposal_id: str
    project_id: int
    proposal_length: int
    word_count: int
    has_question: bool
    has_markdown_headers: bool
    forbidden_phrases_count: int
    validation_passed: bool
    validation_issues: List[str] = field(default_factory=list)
    generation_time_ms: int = 0
    model_used: str = "unknown"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)


@dataclass
class MetricsSummary:
    """
    Summary statistics for collected metrics

    Attributes:
        total_proposals: Total number of proposals tracked
        avg_length: Average proposal character count
        avg_word_count: Average word count
        question_rate: Percentage of proposals with questions
        markdown_header_rate: Percentage with markdown headers
        avg_validation_issues: Average number of validation issues
        pass_rate: Percentage that passed validation
        avg_generation_time_ms: Average generation time
    """

    total_proposals: int
    avg_length: float
    avg_word_count: float
    question_rate: float
    markdown_header_rate: float
    avg_validation_issues: float
    pass_rate: float
    avg_generation_time_ms: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return asdict(self)


class ProposalMetricsCollector:
    """
    Collector for proposal generation metrics

    Tracks proposal quality over time and provides summary statistics.
    """

    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize the metrics collector

        Args:
            storage_path: Path to persist metrics (optional)
        """
        self._metrics: List[ProposalMetrics] = []
        self._storage_path = storage_path
        if storage_path:
            self._load_from_storage()

    def record_proposal(
        self,
        proposal_id: str,
        project_id: int,
        proposal: str,
        validation_result: Optional[Dict[str, Any]] = None,
        generation_time_ms: int = 0,
        model_used: str = "unknown",
    ) -> ProposalMetrics:
        """
        Record metrics for a single proposal

        Args:
            proposal_id: Unique identifier for the proposal
            project_id: Associated project ID
            proposal: The generated proposal text
            validation_result: Optional validation result dict with is_valid, issues keys
            generation_time_ms: Generation time in milliseconds
            model_used: LLM model used

        Returns:
            The created ProposalMetrics instance
        """
        # Calculate basic metrics
        word_count = len(proposal.split())
        has_question = "?" in proposal
        has_markdown_headers = bool(
            proposal.lstrip().startswith("#")
            or "###" in proposal
            or "##" in proposal
        )

        # Extract validation info if provided
        validation_passed = True
        validation_issues = []
        forbidden_count = 0

        if validation_result:
            validation_passed = validation_result.get("is_valid", True)
            validation_issues = validation_result.get("issues", [])
            # Count forbidden phrases from issues
            forbidden_count = sum(
                1 for issue in validation_issues
                if "forbidden" in issue.lower() or "prohibited" in issue.lower()
            )

        metrics = ProposalMetrics(
            proposal_id=proposal_id,
            project_id=project_id,
            proposal_length=len(proposal),
            word_count=word_count,
            has_question=has_question,
            has_markdown_headers=has_markdown_headers,
            forbidden_phrases_count=forbidden_count,
            validation_passed=validation_passed,
            validation_issues=validation_issues,
            generation_time_ms=generation_time_ms,
            model_used=model_used,
        )

        self._metrics.append(metrics)
        logger.info(f"Recorded metrics for proposal {proposal_id}")

        # Persist if storage path is set
        if self._storage_path:
            self._save_to_storage()

        return metrics

    def get_average_metrics(self) -> MetricsSummary:
        """
        Calculate average metrics from collected data

        Returns:
            MetricsSummary with calculated statistics
        """
        if not self._metrics:
            return MetricsSummary(
                total_proposals=0,
                avg_length=0.0,
                avg_word_count=0.0,
                question_rate=0.0,
                markdown_header_rate=0.0,
                avg_validation_issues=0.0,
                pass_rate=0.0,
                avg_generation_time_ms=0.0,
            )

        total = len(self._metrics)

        avg_length = sum(m.proposal_length for m in self._metrics) / total
        avg_word_count = sum(m.word_count for m in self._metrics) / total
        question_rate = sum(1 for m in self._metrics if m.has_question) / total * 100
        markdown_header_rate = (
            sum(1 for m in self._metrics if m.has_markdown_headers) / total * 100
        )
        avg_validation_issues = (
            sum(len(m.validation_issues) for m in self._metrics) / total
        )
        pass_rate = sum(1 for m in self._metrics if m.validation_passed) / total * 100
        avg_generation_time_ms = sum(m.generation_time_ms for m in self._metrics) / total

        return MetricsSummary(
            total_proposals=total,
            avg_length=round(avg_length, 2),
            avg_word_count=round(avg_word_count, 2),
            question_rate=round(question_rate, 2),
            markdown_header_rate=round(markdown_header_rate, 2),
            avg_validation_issues=round(avg_validation_issues, 2),
            pass_rate=round(pass_rate, 2),
            avg_generation_time_ms=round(avg_generation_time_ms, 2),
        )

    def export_metrics(self, output_path: Optional[Path] = None) -> str:
        """
        Export all collected metrics to JSON

        Args:
            output_path: Optional path to write JSON file

        Returns:
            JSON string of all metrics
        """
        data = {
            "metrics": [m.to_dict() for m in self._metrics],
            "summary": self.get_average_metrics().to_dict(),
            "exported_at": time.time(),
        }

        json_str = json.dumps(data, indent=2, default=str)

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json_str, encoding="utf-8")
            logger.info(f"Metrics exported to {output_path}")

        return json_str

    def get_metrics_by_project(self, project_id: int) -> List[ProposalMetrics]:
        """
        Get all metrics for a specific project

        Args:
            project_id: Project ID to filter by

        Returns:
            List of ProposalMetrics for the project
        """
        return [m for m in self._metrics if m.project_id == project_id]

    def clear_metrics(self) -> None:
        """Clear all collected metrics"""
        self._metrics.clear()
        logger.info("All metrics cleared")

    def _save_to_storage(self) -> None:
        """Persist metrics to storage file"""
        if not self._storage_path:
            return

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        json_data = [m.to_dict() for m in self._metrics]
        self._storage_path.write_text(
            json.dumps(json_data, indent=2), encoding="utf-8"
        )

    def _load_from_storage(self) -> None:
        """Load metrics from storage file"""
        if not self._storage_path or not self._storage_path.exists():
            return

        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
            self._metrics = [ProposalMetrics(**m) for m in data]
            logger.info(f"Loaded {len(self._metrics)} metrics from storage")
        except Exception as e:
            logger.warning(f"Failed to load metrics from storage: {e}")


# Singleton instance
_collector: Optional[ProposalMetricsCollector] = None


def get_metrics_collector(
    storage_path: Optional[Path] = None,
) -> ProposalMetricsCollector:
    """
    Get the singleton metrics collector instance

    Args:
        storage_path: Optional storage path (only used on first call)

    Returns:
        ProposalMetricsCollector singleton instance
    """
    global _collector
    if _collector is None:
        _collector = ProposalMetricsCollector(storage_path=storage_path)
    return _collector


def reset_collector() -> None:
    """Reset the singleton collector (for testing)"""
    global _collector
    _collector = None
    logger.debug("ProposalMetricsCollector singleton reset")
