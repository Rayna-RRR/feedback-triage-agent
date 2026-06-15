import json

import pytest

from feedback_triage_agent.llm_client import DeepSeekConfig, DeepSeekClient, LLMUnavailableError


def test_deepseek_config_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(LLMUnavailableError):
        DeepSeekConfig.from_env()


def test_deepseek_response_parser_accepts_json_content() -> None:
    client = DeepSeekClient(
        DeepSeekConfig(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
        )
    )
    response_body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "issue_category": "模型能力问题",
                                "summary": "回答不准确",
                                "user_need": "获得可靠答案",
                                "product_suggestion": "补充失败样本并加强事实性检查",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        },
        ensure_ascii=False,
    )

    draft = client._parse_response(response_body)

    assert draft.issue_category == "模型能力问题"
    assert draft.product_suggestion == "补充失败样本并加强事实性检查"


def test_deepseek_task_response_parser_accepts_json_content() -> None:
    client = DeepSeekClient(
        DeepSeekConfig(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
        )
    )
    response_body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "input_path": "data/reviews.csv",
                                "output_dir": "data/custom_output",
                                "use_llm_for_triage": False,
                                "generate_html_report": True,
                                "normalize_input": True,
                            }
                        )
                    }
                }
            ]
        }
    )

    intent = client._parse_task_response(response_body)

    assert intent.input_path == "data/reviews.csv"
    assert intent.output_dir == "data/custom_output"
    assert intent.use_llm_for_triage is False
    assert intent.generate_html_report is True
    assert intent.normalize_input is True


def test_deepseek_config_rejects_invalid_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT_SECONDS", "invalid")

    with pytest.raises(LLMUnavailableError):
        DeepSeekConfig.from_env()
