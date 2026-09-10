import json

from prompt_versions import (
    PromptVersion,
    build_prompt,
    get_prompt_version,
    get_prompt_versions,
    run_eval_suite,
)


def test_prompt_registry_returns_default_version():
    versions = get_prompt_versions("interview_question")
    assert versions
    selected = get_prompt_version("interview_question")
    assert selected.name == "interview_question"
    assert selected.version in {v.version for v in versions}
    assert selected.prompt_template


def test_build_prompt_renders_runtime_values():
    prompt = build_prompt(
        "interview_question",
        role="Backend Engineer",
        difficulty="mid",
        topic="API design",
        question_number=2,
        total_questions=4,
        persona_name="Alex Morgan",
        persona_style="encouraging",
    )

    assert "Backend Engineer" in prompt
    assert "API design" in prompt
    assert "question 2 of 4" in prompt.lower()
    assert "Alex Morgan" in prompt


def test_eval_suite_returns_results_for_each_case():
    cases = [
        {
            "name": "baseline",
            "context": {
                "role": "Backend Engineer",
                "difficulty": "mid",
                "topic": "API design",
            },
            "expected_keywords": ["API", "trade-off", "scale"],
        }
    ]

    results = run_eval_suite("interview_question", cases)

    assert len(results) == 1
    assert results[0]["name"] == "baseline"
    assert results[0]["passed"] in {True, False}
    assert "score" in results[0]
    assert "output" in results[0]
