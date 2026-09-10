from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class PromptVersion:
    name: str
    version: str
    prompt_template: str


PROMPT_REGISTRY: Dict[str, List[PromptVersion]] = {
    "interview_question": [
        PromptVersion(
            name="interview_question",
            version="v1",
            prompt_template=(
                "You are {persona_name}, a {persona_style} interviewer.\n"
                "Interviewing a {role} candidate at {difficulty} level.\n"
                "Topic: {topic}.\n"
                "This is question {question_number} of {total_questions}.\n"
                "Ask one concise, practical interview question that tests deep reasoning."
            ),
        ),
        PromptVersion(
            name="interview_question",
            version="v2",
            prompt_template=(
                "You are {persona_name}, a {persona_style} interviewer at a tech company.\n"
                "You are interviewing a candidate for a {role} position at {difficulty} level.\n"
                "The interview topic is: {topic}.\n"
                "This is question {question_number} of {total_questions}.\n"
                "Generate a single, clear interview question. Keep it concise (2-3 sentences max).\n"
                "Focus on practical engineering trade-offs and system-level thinking.\n"
                "Return ONLY the question."
            ),
        ),
    ],
    "answer_evaluation": [
        PromptVersion(
            name="answer_evaluation",
            version="v1",
            prompt_template=(
                "Evaluate the answer for a {role} candidate at {difficulty} level.\n"
                "Question: {question}\n\n"
                "Candidate answer: {candidate_answer}\n\n"
                "Return concise JSON with overall_score, correctness, clarity, approach, communication, strengths, weaknesses."
            ),
        )
    ],
    "final_report": [
        PromptVersion(
            name="final_report",
            version="v1",
            prompt_template=(
                "Write a final interview summary for {candidate_name}, applying for {role}.\n"
                "Difficulty: {difficulty}.\n"
                "Topic: {topic}.\n"
                "Use short sections: Overall Assessment, Key Strengths, Areas to Improve, Recommendation."
            ),
        )
    ],
}


def get_prompt_versions(prompt_name: str) -> List[PromptVersion]:
    return PROMPT_REGISTRY.get(prompt_name, [])


def get_prompt_version(prompt_name: str, version: str = "v2") -> PromptVersion:
    versions = get_prompt_versions(prompt_name)
    for item in versions:
        if item.version == version:
            return item
    if not versions:
        raise ValueError(f"Unknown prompt: {prompt_name}")
    return versions[-1]


def build_prompt(prompt_name: str, version: str = "v2", **kwargs: Any) -> str:
    prompt = get_prompt_version(prompt_name, version)
    defaults = {
        "persona_name": "Alex Morgan",
        "persona_style": "encouraging and pragmatic",
        "question_number": 1,
        "total_questions": 1,
        "difficulty": "mid",
        "role": "Backend Engineer",
        "topic": "system design",
        "candidate_name": "Candidate",
    }
    defaults.update(kwargs)
    return prompt.prompt_template.format(**defaults)


def run_eval_suite(prompt_name: str, cases: List[Dict[str, Any]], version: str = "v2") -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for case in cases:
        payload = case.get("context", {})
        payload.setdefault("persona_name", "Alex Morgan")
        payload.setdefault("persona_style", "encouraging and pragmatic")
        payload.setdefault("question_number", 1)
        payload.setdefault("total_questions", 1)
        prompt = build_prompt(prompt_name, version=version, **payload)
        output = prompt
        expected_keywords = case.get("expected_keywords", [])

        matches = sum(1 for keyword in expected_keywords if keyword.lower() in output.lower())
        score = round(matches / max(len(expected_keywords), 1), 2) if expected_keywords else 1.0
        passed = score >= 0.5

        results.append({
            "name": case.get("name", "case"),
            "score": score,
            "passed": passed,
            "output": output,
        })
    return results
