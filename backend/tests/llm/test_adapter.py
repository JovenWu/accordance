from accordance.llm.adapter import build_llm


def test_build_llm_fake_returns_runnable_with_invoke():
    llm = build_llm("fake:fake")
    result = llm.invoke("hello")
    assert "status" in str(result)
