"""
Proposal Validator Module.

Validates generated proposals against strict quality and formatting rules.
Ensures proposals meet word count limits, contain necessary elements (like questions),
and avoid prohibited phrases or formatting.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import re

@dataclass
class ValidationResult:
    """
    Result of a proposal validation check.

    Attributes:
        is_valid: Boolean indicating if the proposal passed all critical checks.
        issues: List of string descriptions for any issues found.
        severity: Severity of the issues ('low', 'medium', 'high').
    """
    is_valid: bool
    issues: List[str] = field(default_factory=list)
    severity: str = "low"


class ProposalValidator:
    """
    Validator for proposal content.
    """

    PROHIBITED_PHRASES: List[str] = [
        r"i am an expert",
        r"check my portfolio",
        r"trust me",
        r"kindly hire me",
        r"dear sir",
        r"dear madam",
        r"hope you are doing well",
        r"thanks for reading"
    ]
    
    PROHIBITED_HEADERS: List[str] = [
        r"^#\s",   # Top-level H1 headers are usually too aggressive/large for a proposal
    ]

    @classmethod
    def validate(cls, proposal_text: str) -> ValidationResult:
        """
        Validate a proposal string.

        Args:
            proposal_text: The content of the proposal.

        Returns:
            ValidationResult object containing status and issues.
        """
        issues = []
        
        # 1. Word count check (80-200 words)
        # Using a simple whitespace split for approximation
        words = proposal_text.split()
        word_count = len(words)
        
        if word_count < 80:
            issues.append(f"Word count too low ({word_count} < 80 words).")
        elif word_count > 200:
            issues.append(f"Word count too high ({word_count} > 200 words).")
            
        # 2. Question mark check
        # A good proposal usually includes a clarifying question.
        if "?" not in proposal_text:
            issues.append("No question marks found. The proposal should ask at least one relevant question.")

        # 3. Prohibited Markdown Headers
        for line in proposal_text.split('\n'):
            for pattern in cls.PROHIBITED_HEADERS:
                if re.match(pattern, line):
                    issues.append(f"Prohibited header style found: '{line.strip()}'. Avoid using H1 (#).")

        # 4. Prohibited Phrases
        # Case-insensitive search for banned marketing fluff or generic greetings.
        lower_text = proposal_text.lower()
        for pattern in cls.PROHIBITED_PHRASES:
            # We use re.search to find the phrase anywhere in the text
            if re.search(pattern, lower_text):
                # Clean up the regex pattern for display (remove raw string markers if printed, but here just showing pattern)
                readable_pattern = pattern.replace(r"\s", " ")
                issues.append(f"Prohibited phrase found: matches pattern '{readable_pattern}'.")

        is_valid = len(issues) == 0
        severity = "high" if issues else "low"
        
        return ValidationResult(is_valid=is_valid, issues=issues, severity=severity)
