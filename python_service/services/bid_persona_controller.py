"""
Bid Persona Controller Module.

Manages the detection of project types and assignment of appropriate
personas for proposal generation.
"""

import re
from typing import Dict, List

class BidPersonaController:
    """
    Controller for determining project type and selecting the appropriate persona hint.
    """

    TYPE_PATTERNS: Dict[str, str] = {
        "frontend": r"(react|vue|angular|javascript|html|css|frontend|ui/ux|figma|tailwind|bootstrap|jquery|dom)",
        "backend": r"(python|django|flask|fastapi|node|express|sql|database|aws|backend|api|server|postgres|mysql|mongodb|docker)",
        "ai": r"(ai|llm|gpt|openai|machine learning|nlp|vision|tensorflow|pytorch|rag|chatbot|langchain|huggingface)",
        "mobile": r"(ios|android|flutter|react native|swift|kotlin|mobile app|ipa|apk)",
        "fullstack": r"(fullstack|full stack|mern|mean|web application|end-to-end)"
    }

    PERSONA_HINTS: Dict[str, str] = {
        "frontend": "Focus on UX/UI details, responsiveness, and component reusability. Mention specific framework expertise (React/Vue).",
        "backend": "Emphasize system architecture, API security, database optimization, and scalability.",
        "ai": "Highlight experience with LLMs, RAG pipelines, prompt engineering, and Python data stacks.",
        "mobile": "Focus on cross-platform performance, native feel, and store deployment experience.",
        "fullstack": "Demonstrate end-to-end capability, from DB design to frontend state management.",
        "general": "Professional developer focusing on clean code, timely delivery, and clear communication."
    }

    @classmethod
    def detect_project_type(cls, title: str, description: str) -> str:
        """
        Detect the project type based on keywords in the title and description.

        Args:
            title: Project title.
            description: Project description.

        Returns:
            str: Detected project type (frontend, backend, ai, mobile, fullstack, or general).
        """
        text = (title + " " + description).lower()
        
        scores: Dict[str, int] = {k: 0 for k in cls.TYPE_PATTERNS.keys()}
        
        for p_type, pattern in cls.TYPE_PATTERNS.items():
            matches = re.findall(pattern, text)
            scores[p_type] = len(matches)
            
        # Priority Logic:
        # Fullstack often overlaps, so prioritize if explicitly mentioned 
        # or if there is significant overlap between frontend and backend keywords.
        if scores["fullstack"] > 0:
            return "fullstack"
            
        # Heuristic: If both frontend and backend have significant hits, it might be fullstack
        # arbitrary threshold: > 1 match for both
        if scores["frontend"] >= 1 and scores["backend"] >= 1:
            return "fullstack"
            
        # Find the max score
        best_match = max(scores.items(), key=lambda x: x[1])
        
        # If no keywords matched at all, return general
        if best_match[1] == 0:
            return "general"
            
        return best_match[0]

    @classmethod
    def get_persona_hint(cls, project_type: str) -> str:
        """
        Get the persona hint string for a given project type.

        Args:
            project_type: The project type key.

        Returns:
            str: The persona hint text.
        """
        return cls.PERSONA_HINTS.get(project_type, cls.PERSONA_HINTS["general"])
