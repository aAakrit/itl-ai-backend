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

    ANALYTICS = "/api/v2/analytics/summary"

    HEALTH = "/api/health"


class PremiumEndpoints:
    SEARCH = "/api/judgements/premium/search"
    MORE = "/api/judgements/premium/more"

    CLARIFY = "/api/judgements/premium/clarify"
    REFINE = "/api/judgements/premium/refine"
    SIMILAR = "/api/judgements/premium/similar"

    FEEDBACK = "/api/judgements/premium/feedback"

    HEALTH = "/api/health"


class FreeEndpoints:
    SEARCH = "/api/judgements/free/search"
    MORE = "/api/judgements/free/more"

    CLARIFY = "/api/judgements/free/clarify"
    REFINE = "/api/judgements/free/refine"
    SIMILAR = "/api/judgements/free/similar"

    HEALTH = "/api/health"


class NoticeEndpoints:
    PROCESS_TEXT = "/api/notice/process"

    PROCESS_FILE = "/api/notice/process-file"

    HEALTH = "/api/health"


class SummarizerEndpoints:
    SUMMARIZE_TEXT = "/api/summarize/text"
    
    SUMMARIZE_FILE = "/api/summarize/file"

    HEALTH = "/api/health"