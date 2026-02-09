"""
Proposal Validator Module.

Validates generated proposals against strict quality and formatting rules.
Ensures proposals meet word count limits, contain necessary elements (like questions),
and avoid prohibited phrases or formatting.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple
import re


@dataclass
class ValidationResult:
    """
    Result of a proposal validation check.

    Attributes:
        is_valid: Boolean indicating if the proposal passed all critical checks.
        issues: List of string descriptions for any issues found.
        severity: Severity of the issues ('low', 'medium', 'high').
        warnings: List of warnings (non-critical issues).
    """

    is_valid: bool
    issues: List[str] = field(default_factory=list)
    severity: str = "low"
    warnings: List[str] = field(default_factory=list)


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
        r"thanks for reading",
    ]

    PROHIBITED_HEADERS: List[str] = [
        r"^#\s",  # Top-level H1 headers are usually too aggressive/large for a proposal
    ]

    # Common technical skills to detect in proposals
    COMMON_SKILLS: List[str] = [
        "python",
        "javascript",
        "typescript",
        "react",
        "vue",
        "angular",
        "node",
        "nodejs",
        "django",
        "fastapi",
        "flask",
        "express",
        "postgresql",
        "mysql",
        "mongodb",
        "redis",
        "sqlite",
        "aws",
        "azure",
        "gcp",
        "docker",
        "kubernetes",
        "terraform",
        "git",
        "github",
        "gitlab",
        "ci/cd",
        "jenkins",
        "github actions",
        "api",
        "rest",
        "graphql",
        "websockets",
        "microservices",
        "machine learning",
        "ml",
        "ai",
        "nlp",
        "llm",
        "gpt",
        "tensorflow",
        "pytorch",
        "pandas",
        "numpy",
        "scikit-learn",
        "scraping",
        "automation",
        "bot",
        "crawler",
        "frontend",
        "backend",
        "fullstack",
        "full-stack",
        "mobile",
        "ios",
        "android",
        "flutter",
        "react native",
        "css",
        "html",
        "sass",
        "less",
        "tailwind",
        "testing",
        "pytest",
        "jest",
        "unittest",
        "cypress",
        "security",
        "oauth",
        "jwt",
        "ssl",
        "encryption",
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
            issues.append(
                "No question marks found. The proposal should ask at least one relevant question."
            )

        # 3. Prohibited Markdown Headers
        for line in proposal_text.split("\n"):
            for pattern in cls.PROHIBITED_HEADERS:
                if re.match(pattern, line):
                    issues.append(
                        f"Prohibited header style found: '{line.strip()}'. Avoid using H1 (#)."
                    )

        # 4. Prohibited Phrases
        # Case-insensitive search for banned marketing fluff or generic greetings.
        lower_text = proposal_text.lower()
        for pattern in cls.PROHIBITED_PHRASES:
            # We use re.search to find the phrase anywhere in the text
            if re.search(pattern, lower_text):
                # Clean up the regex pattern for display (remove raw string markers if printed, but here just showing pattern)
                readable_pattern = pattern.replace(r"\s", " ")
                issues.append(
                    f"Prohibited phrase found: matches pattern '{readable_pattern}'."
                )

        is_valid = len(issues) == 0
        severity = "high" if issues else "low"

        return ValidationResult(is_valid=is_valid, issues=issues, severity=severity)

    @classmethod
    def validate_tech_accuracy(
        cls, proposal: str, project: Dict[str, Any]
    ) -> ValidationResult:
        """
        P2: Technical Accuracy Validation

        Check if the proposal mentions skills/technologies that match the project requirements.

        Args:
            proposal: The proposal text to validate.
            project: Project information containing skills and description.

        Returns:
            ValidationResult with is_valid=True if tech stack matches sufficiently,
            warnings for missing skills, and issues for complete mismatch.
        """
        issues = []
        warnings = []

        # Extract project skills
        project_skills = project.get("skills") or []
        if isinstance(project_skills, str):
            # Handle comma-separated string
            project_skills = [s.strip().lower() for s in project_skills.split(",")]

        project_skills = [s.lower() for s in project_skills]

        # Get additional context from title and description
        project_context = f"{project.get('title', '')} {project.get('description', '')}"
        project_context_lower = project_context.lower()

        # Extract mentioned skills from proposal
        proposal_lower = proposal.lower()
        mentioned_skills = []

        for skill in cls.COMMON_SKILLS:
            # Use word boundary matching to avoid false positives
            pattern = r"\b" + re.escape(skill) + r"\b"
            if re.search(pattern, proposal_lower):
                mentioned_skills.append(skill)

        # Also check for skills mentioned in project_skills that are not in COMMON_SKILLS
        for skill in project_skills:
            if skill.lower() not in cls.COMMON_SKILLS:
                pattern = r"\b" + re.escape(skill.lower()) + r"\b"
                if re.search(pattern, proposal_lower):
                    mentioned_skills.append(skill.lower())

        # Calculate skill coverage
        if project_skills:
            matched_skills = [
                s
                for s in mentioned_skills
                if any(s in ps or ps in s for ps in project_skills)
            ]

            coverage = len(set(matched_skills)) / len(set(project_skills))

            if coverage < 0.3:
                issues.append(
                    f"Low skill coverage: only {len(matched_skills)}/{len(project_skills)} project skills mentioned"
                )

            # Generate warnings for missing important skills
            missing_skills = [
                s
                for s in project_skills
                if not any(s in m or m in s for m in mentioned_skills)
            ]
            if missing_skills and coverage > 0:
                # Only warn if some skills are matched but others are missing
                warnings.append(
                    f"Consider mentioning these skills: {', '.join(missing_skills[:3])}"
                )
        else:
            # No project skills defined, check if proposal mentions any tech at all
            if not mentioned_skills:
                warnings.append(
                    "Consider mentioning specific technologies or skills relevant to this project"
                )

        is_valid = len(issues) == 0

        return ValidationResult(
            is_valid=is_valid,
            issues=issues,
            severity="high" if issues else ("medium" if warnings else "low"),
            warnings=warnings,
        )

    @classmethod
    def detect_duplicates(cls, proposals: List[str]) -> float:
        """
        P3: Duplicate Content Detection

        Detect similarity between proposals using multiple algorithms:
        1. Jaccard similarity (word-based)
        2. Levenshtein distance normalization
        3. N-gram similarity

        Args:
            proposals: List of proposal texts to compare.

        Returns:
            float: Similarity score between 0.0 (completely different) and 1.0 (identical).
                   Returns 0.0 if fewer than 2 proposals.
        """
        if len(proposals) < 2:
            return 0.0

        # Calculate pairwise similarities and return the maximum
        max_similarity = 0.0

        for i in range(len(proposals)):
            for j in range(i + 1, len(proposals)):
                sim = cls._calculate_similarity(proposals[i], proposals[j])
                max_similarity = max(max_similarity, sim)

        return max_similarity

    @classmethod
    def _calculate_similarity(cls, text1: str, text2: str) -> float:
        """
        Calculate similarity between two texts using multiple methods.

        Args:
            text1: First text.
            text2: Second text.

        Returns:
            float: Normalized similarity score (0-1).
        """
        # Normalize texts
        text1 = cls._normalize_text(text1)
        text2 = cls._normalize_text(text2)

        if not text1 or not text2:
            return 0.0

        # 1. Jaccard Similarity (word-based)
        words1 = set(text1.split())
        words2 = set(text2.split())

        if words1 and words2:
            intersection = len(words1 & words2)
            union = len(words1 | words2)
            jaccard_sim = intersection / union if union > 0 else 0.0
        else:
            jaccard_sim = 0.0

        # 2. Character-level 3-gram similarity
        def get_ngrams(text: str, n: int = 3) -> set:
            return set(text[i : i + n] for i in range(len(text) - n + 1))

        ngrams1 = get_ngrams(text1)
        ngrams2 = get_ngrams(text2)

        if ngrams1 and ngrams2:
            ngram_intersection = len(ngrams1 & ngrams2)
            ngram_union = len(ngrams1 | ngrams2)
            ngram_sim = ngram_intersection / ngram_union if ngram_union > 0 else 0.0
        else:
            ngram_sim = 0.0

        # 3. Longest Common Subsequence ratio
        lcs_length = cls._lcs_length(text1, text2)
        max_len = max(len(text1), len(text2))
        lcs_sim = (2 * lcs_length) / (len(text1) + len(text2)) if max_len > 0 else 0.0

        # Weighted average of similarities
        # Give more weight to word-level and n-gram similarity
        final_similarity = (0.4 * jaccard_sim) + (0.4 * ngram_sim) + (0.2 * lcs_sim)

        return final_similarity

    @staticmethod
    def _normalize_text(text: str) -> str:
        """
        Normalize text for comparison.

        Args:
            text: Text to normalize.

        Returns:
            Normalized lowercase text with punctuation removed.
        """
        # Convert to lowercase
        text = text.lower()

        # Remove punctuation and extra whitespace
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        return text

    @staticmethod
    def _lcs_length(text1: str, text2: str) -> int:
        """
        Calculate the length of the Longest Common Subsequence.

        Args:
            text1: First text.
            text2: Second text.

        Returns:
            Length of LCS.
        """
        m, n = len(text1), len(text2)

        # Use only if texts are short enough (avoid O(n^2) for long texts)
        if m * n > 100000:  # Limit for performance
            return min(m, n) // 2  # Rough estimate

        # Create DP table
        dp = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if text1[i - 1] == text2[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

        return dp[m][n]
