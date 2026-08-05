"""Runtime configuration loaded from the environment."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Connection settings read from env (or a local .env file)."""

    database_url: str
    redis_url: str
    bocha_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    llm_model: str = "deepseek-v4-pro"

    # IM push (P1c). Channel selection: "stub" | "hermes_weixin" | "wecom_webhook"
    im_channel: str = "stub"
    report_dev_label: bool = True  # G0.4: prepend DEV/UNVERIFIED prefix; set False in prod
    weixin_account_id: str | None = None
    weixin_token: str | None = None
    weixin_chat_id: str | None = None
    wecom_webhook_url: str | None = None
    hermes_bin: str = "hermes"
    weixin_target: str = "weixin"

    # Triggering (P2a). misfire grace + per-job freshness tolerance (minutes) +
    # absolute freshness ceiling (CST). Retry budget is reserved here for the
    # startup timing assertion; the retry EXECUTION is P2b.
    misfire_grace_s: int = 900
    max_transient_retries: int = 2
    backoff_ceiling_s: int = 30
    premarket_tolerance_min: int = 90
    main_tolerance_min: int = 90
    freshness_ceiling_cst: str = "10:00"
    main_report_time_cst: str = "07:00"

    # Bark alert: iOS push when primary IM delivery fails. Empty = disabled.
    bark_url: str = ""

    # Dead-man's switch (out-of-process liveness watchdog). Per-job Healthchecks
    # ping URLs; empty ⇒ disabled (no external check-in). Set on the report node
    # only after the second host is provisioned — see docs/runbooks/deadman-switch.md.
    healthcheck_url_premarket: str = ""
    healthcheck_url_main: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
