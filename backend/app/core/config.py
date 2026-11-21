from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@127.0.0.1:5433/workcode_v2"
    JWT_SECRET: str = "dev-only-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 720
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:5174"
    MAX_ADMINS: int = 3
    INTERN_TARGET_HEADCOUNT: int = 10
    OFFROLL_TRAINING_MONTHS: int = 6
    TIMEZONE: str = "Asia/Kolkata"
    LOGIN_RATE_LIMIT: int = 10          # attempts
    LOGIN_RATE_WINDOW_SECONDS: int = 300
    # --- e-mail (password reset links). Empty = e-mail is off and "Forgot password" answers "not set up". ---
    APP_URL: str = "http://localhost:5173"      # address people open WORKCODE at; the reset link starts with it
    PASSWORD_RESET_MINUTES: int = 30
    RESET_RATE_LIMIT: int = 5                    # reset requests per address / per computer ...
    RESET_RATE_WINDOW_SECONDS: int = 900         # ... in this many seconds
    MAIL_FROM: str = ""                          # sender address; empty = SMTP_USER (Gmail API: the signed-in account)
    MAIL_FROM_NAME: str = "WORKCODE"
    MAIL_TIMEOUT_SECONDS: int = 20
    MAIL_ASYNC: bool = True                      # send in the background so the answer takes equally long for every address
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_STARTTLS: bool = True
    GMAIL_CLIENT_ID: str = ""
    GMAIL_CLIENT_SECRET: str = ""
    GMAIL_REFRESH_TOKEN: str = ""
    ALLOW_QUERY_TOKEN: bool = False      # hosted-preview workaround only; keep False on your own server
    STORAGE_DIR: str = "./storage"       # recordings are stored here, outside the web root
    MAX_RECORDING_BYTES: int = 2_000_000_000
    RUNNER_ENABLED: bool = True
    RUNNER_MEMORY_MB: int = 512
    RUNNER_TMP_MB: int = 256
    RUNNER_CPUS: float = 1.0
    RUNNER_MAX_SECONDS: int = 90
    RUNNER_MAX_OUTPUT: int = 100_000
    RUNNER_MAX_PARALLEL: int = 4
    # Only when the backend itself runs in a container (docker-compose.yml): the folder where run copies are
    # written, and the Docker volume mounted on that folder. Empty = normal temp folder (backend runs on the PC).
    RUNNER_WORK_DIR: str = ""
    RUNNER_VOLUME: str = ""
    TERMINAL_IDLE_SECONDS: int = 1800      # no key in any terminal of the workspace for this long: they are closed
    TERMINAL_MAX_SECONDS: int = 14400      # longest life of one terminal
    TERMINAL_MAX_PER_USER: int = 4         # terminals open at the same time (they share one container)
    # Terminal container: "none" = no network at all, "bridge" = internet access (needed for npm install / pip install).
    TERMINAL_NETWORK: str = "none"
    # Ports of the terminal container that are published on this computer, so a dev server started in the terminal
    # (npm run dev, flask run, ...) can be opened in the Preview tab. Only used with TERMINAL_NETWORK=bridge.
    # Each one gets a free port on TERMINAL_PORTS_BIND. Empty = nothing is published.
    TERMINAL_PORTS: str = "3000,3001,4173,4200,5000,5173,8000,8080"
    TERMINAL_PORTS_BIND: str = "127.0.0.1"
    TERMINAL_MEMORY_MB: int = 1536
    TERMINAL_TMP_MB: int = 512
    MAX_CHUNK_BYTES: int = 25_000_000
    BCRYPT_ROUNDS: int = 12
    MAX_FILE_BYTES: int = 1_000_000
    MAX_FILES_PER_WORKSPACE: int = 2000
    MAX_WORKSPACE_BYTES: int = 50_000_000
    HEARTBEAT_MAX_GAP_SECONDS: int = 45  # longest gap credited between heartbeats
    INACTIVITY_TIMEOUT_SECONDS: int = 300      # 5 minutes without input pauses the timer
    INACTIVITY_WARNING_SECONDS: int = 240      # warning shown at 4 minutes
    EXTENSION_FRESH_SECONDS: int = 75          # extension reports older than this are ignored (safe pause)
    EXTENSION_TOKEN_MINUTES: int = 43200     # 30 days; this token can only report a site category
    AI_KEY_SECRET: str = ""              # encrypts stored AI provider keys; empty = derived from JWT_SECRET
    AI_TIMEOUT_SECONDS: int = 120
    SESSION_STALE_SECONDS: int = 1800    # session auto-closes after this silence
    # --- build 29: workday schedule and recording retention ---
    WORKDAY_TARGET_HOURS: float = 8.0    # regular schedule length; applies to developer / onroll / offroll
    RECORDING_RETENTION_DAYS: int = 30   # finished videos older than this (plus their chunks) are deleted automatically
    RECORDING_AWAY_GRACE_SECONDS: int = 60   # build 31: the workspace recording pauses the moment the tab is left;
                                             # after this many seconds away it is closed and saved (0 = close at once)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
