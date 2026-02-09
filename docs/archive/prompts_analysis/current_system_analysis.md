# Current System Analysis & Optimization Plan
**Date:** 2026-01-11
**Context:** Aligning `freelancer_automation` with the "Humanized Bid" methodology.

## 1. Current System Gap Analysis

### A. The "Structure" Blocker (Critical)
*   **Location:** `python_service/services/bid_service.py` -> `check_content_risk`
*   **Issue:** The current code explicitly **enforces** the "Structured Superstition" you want to break.
    *   *Line 80:* It checks for keywords: `["方案", "计划", "technical", "implementation", "approach"...]`.
    *   *Line 82:* If fewer than 2 distinct section keywords are found, it rejects the bid with "缺乏结构化表达" (Lack of structured expression).
*   **Conflict:** If we generate a humanized, conversational pitch (which avoids headers like "Technical Approach"), this validator will **block** it.

### B. The "Hardcoded Robot" Templates
*   **Location:** `python_service/services/project_scorer.py` -> `generate_proposal_draft`
*   **Issue:** The fallback generation logic uses rigid, list-heavy templates.
    *   *Example:* `**技术架构设计：**
- 后端框架...`
    *   *Effect:* Even if the LLM fails or isn't used, the fallback is the exact opposite of the desired "human" persona.

### C. The Generic LLM Prompt
*   **Location:** `python_service/services/llm_scoring_service.py` -> `_get_default_system_prompt`
*   **Issue:** The prompt asks for a "Brief professional proposal" but lacks specific styling instructions. It focuses heavily on "Win Rate Scoring" but treats the proposal generation as a secondary byproduct without "Persona" or "Pain Point" logic.

## 2. Optimization Plan

To implement the "Experience Contractor Interview" methodology, we need to execute the following changes:

### Step 1: Dismantle the "Structure Police"
*   **Action:** Modify `python_service/services/bid_service.py`.
*   **Change:** Remove or disable the "Section Structure Check" (Rule #6 in `check_content_risk`).
*   **Reasoning:** Conversational pitches do not use standard headers.

### Step 2: Inject the "Expert Persona" into LLM
*   **Action:** Update `python_service/services/llm_scoring_service.py`.
*   **Change:** Rewrite `_get_default_system_prompt` to include:
    1.  **Persona Definition:** "Direct, technical backend architect."
    2.  **Chain of Thought:** "First, analyze the hardest 20% of the project (Latency, Concurrency...)."
    3.  **Experience Anchor:** Inject a dynamic "User Profile/Experience" block (need to define where this comes from, likely `config` or hardcoded for now).
    4.  **Style Rules:** "No markdown headers. Start with the pain point. Ask 1 question."

### Step 3: Humanize the Fallback Templates
*   **Action:** Update `python_service/services/project_scorer.py`.
*   **Change:** Rewrite `_generate_web_proposal`, `_generate_ai_proposal`, etc., to use the new "Context-Driven Paragraph" style instead of bullet points.
    *   *From:* `**Technical:** - FastAPI`
    *   *To:* "I recommend using **FastAPI** to ensure low latency..."

### Step 4: n8n Workflow Integration (Conceptual)
*   The Python service currently handles the "Analysis" (Scoring) and "Writing" (Drafting) in one pass (`score_projects_concurrent`).
*   **Recommendation:** To fully implement the "3-Node" logic:
    *   Split the LLM prompt to output JSON with `{"analysis": "...", "pain_points": [...], "draft": "..."}`.
    *   This allows the Python service (or n8n) to log the "Analysis" separately from the "Draft".

## 3. Next Steps
1.  **User Confirmation:** Approve the removal of the strict structure check in `bid_service.py`.
2.  **Profile Setup:** Provide the "User Summary" (e.g., the Ruijin Hospital experience) to be hardcoded or loaded from config for the LLM prompt.
3.  **Execution:** I will proceed with modifying the Python files.
