from accordance.config import Settings


def test_session_defaults():
    s = Settings(llm_api_key="", openai_api_key="", voyage_api_key="")
    assert s.session_ttl_days == 14
    assert s.session_cookie_secure is False
