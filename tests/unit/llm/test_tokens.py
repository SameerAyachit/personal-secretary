"""Tests for llm/tokens.py: tiktoken cl100k_base counting with vendored file (plan §7.4, C-14)."""


from secretary.llm.tokens import count_tokens


def test_count_tokens_returns_int():
    n = count_tokens("hello world")
    assert isinstance(n, int)
    assert n > 0


def test_count_tokens_empty():
    assert count_tokens("") == 0


def test_count_tokens_different_lengths():
    short = count_tokens("hi")
    long_ = count_tokens("this is a much longer sentence with more words")
    assert long_ > short


def test_count_tokens_deterministic():
    text = "The quick brown fox jumps over the lazy dog"
    assert count_tokens(text) == count_tokens(text)
