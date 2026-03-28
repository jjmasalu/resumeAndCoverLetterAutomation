from config import Settings


def make_settings(**overrides) -> Settings:
    base = {
        "supabase_url": "https://example.supabase.co",
        "supabase_service_key": "service-key",
        "gemini_api_key": "gemini-key",
        "tavily_api_key": "tavily-key",
        "firecrawl_api_key": "firecrawl-key",
    }
    base.update(overrides)
    return Settings(**base)


def test_allowed_frontend_origins_supports_multiple_production_urls():
    settings = make_settings(
        frontend_url="https://resume-ai-blue-zeta.vercel.app",
        frontend_urls="https://resume-and-cover-letter-automation.vercel.app, https://another-frontend.vercel.app",
    )

    assert settings.allowed_frontend_origins == [
        "https://resume-ai-blue-zeta.vercel.app",
        "https://resume-and-cover-letter-automation.vercel.app",
        "https://another-frontend.vercel.app",
        "http://localhost:3000",
        "http://localhost:3010",
        "http://localhost:3014",
    ]


def test_allowed_frontend_origins_dedupes_repeated_values():
    settings = make_settings(
        frontend_url="https://resume-ai-blue-zeta.vercel.app",
        frontend_urls="https://resume-ai-blue-zeta.vercel.app, http://localhost:3000",
    )

    assert settings.allowed_frontend_origins == [
        "https://resume-ai-blue-zeta.vercel.app",
        "http://localhost:3000",
        "http://localhost:3010",
        "http://localhost:3014",
    ]
