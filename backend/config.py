from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    supabase_url: str
    supabase_service_key: str
    gemini_api_key: str
    tavily_api_key: str
    firecrawl_api_key: str
    frontend_url: str = "http://localhost:3000"
    frontend_urls: str = ""

    @property
    def allowed_frontend_origins(self) -> list[str]:
        origins = [self.frontend_url]
        if self.frontend_urls:
            origins.extend(
                origin.strip()
                for origin in self.frontend_urls.split(",")
                if origin.strip()
            )

        origins.extend([
            "http://localhost:3000",
            "http://localhost:3010",
            "http://localhost:3014",
        ])

        deduped: list[str] = []
        seen: set[str] = set()
        for origin in origins:
            if origin in seen:
                continue
            seen.add(origin)
            deduped.append(origin)
        return deduped


settings = Settings()
