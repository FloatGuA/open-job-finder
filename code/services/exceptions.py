class OpenJobFinderError(Exception):
    pass


class SessionExpiredError(OpenJobFinderError):
    pass


class RateLimitExceededError(OpenJobFinderError):
    pass


class LLMParseError(OpenJobFinderError):
    pass


class AllProvidersFailedError(OpenJobFinderError):
    pass


class OnboardingIncompleteError(OpenJobFinderError):
    pass


class DailyLimitReachedError(OpenJobFinderError):
    pass


class CaptchaRequiredError(OpenJobFinderError):
    pass


class JobExpiredError(OpenJobFinderError):
    """Raised when a Boss直聘 job detail page indicates the position is offline or no longer exists."""
    pass
