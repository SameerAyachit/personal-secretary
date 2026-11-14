"""LLM errors (plan §7.4, §7.8)."""


class LLMError(Exception):
    """Base class for LLM-layer errors."""


class RequestTooLarge(LLMError):
    """Raised when estimated tokens exceed the whole bucket; never wait forever (concern C-9)."""


class ProviderUnavailable(LLMError):
    """The provider is unavailable or returned an error status."""


class AuthError(ProviderUnavailable):
    """The provider rejected the API key (HTTP 401/403)."""
