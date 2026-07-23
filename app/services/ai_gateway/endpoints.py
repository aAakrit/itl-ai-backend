"""
Central definition of all AI service endpoints.

Keeping endpoint paths here avoids hardcoding URLs across providers.
"""


class MainEndpoints:
    QUERY = "/api/v1/query"
    QUERY_V2 = "/api/v2/query"

    CASE_LAWS = "/api/v1/case-laws"

    CLARIFY = "/api/v1/clarify"
    REFINE = "/api/v1/refine"

    SESSIONS = "/api/v2/sessions"
    FEEDBACK = "/api/v2/feedback"

    HEALTH = "/api/health"


class PremiumEndpoints:
    SEARCH = "/api/v1/search"
    MORE = "/api/v1/more"

    CLARIFY = "/api/v1/clarify"
    REFINE = "/api/v1/refine"
    SIMILAR = "/api/v1/similar"

    FEEDBACK = "/api/v1/feedback"

    HEALTH = "/api/health"


class FreeEndpoints:
    SEARCH = "/api/v1/search"
    MORE = "/api/v1/more"

    CLARIFY = "/api/v1/clarify"
    REFINE = "/api/v1/refine"
    SIMILAR = "/api/v1/similar"

    HEALTH = "/api/health"


class NoticeEndpoints:
    GENERATE = "/api/v1/generate"

    HEALTH = "/api/health"


class SummarizerEndpoints:
    SUMMARIZE = "/api/v1/summarize"

    HEALTH = "/api/health"