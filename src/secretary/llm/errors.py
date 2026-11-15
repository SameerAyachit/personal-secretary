"""LLM errors (plan §7.4, §7.8)."""


class LLMError(Exception):
    """Base class for LLM-layer errors."""


class RequestTooLarge(LLMError):
    """Raised when estimated tokens exceed the whole bucket; never wait forever (concern C-9)."""


class ProviderUnavailable(LLMError):
    """The provider is unavailable or returned an error status."""


class AuthError(ProviderUnavailable):
    """The provider rejected the API key (HTTP 401/403)."""


class DailyLimitReached(LLMError):
    """The configured daily request/token budget (``rpd``/``tpd``) is used up.

    Never waited out (the wait could be hours); the turn fails with a clear message.
    """


class RateLimited(ProviderUnavailable):
    """The provider kept answering HTTP 429 after the allowed retries."""
