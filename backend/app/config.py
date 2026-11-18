"""Application settings, read from the environment.

Everything marked [CONFIRM] in the build specification lives here with the documented
default, and is listed in the README open-decisions table.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="FMS_", extra="ignore", case_sensitive=False
    )

    env: Literal["local", "ci", "staging", "production"] = "local"
    database_url: str = "postgresql+psycopg://fms:fms@localhost:5432/fms"
    secret_key: str = "change-me-in-every-real-environment-0123456789"
    file_store_path: str = "./var/files"

    # --- Auth -----------------------------------------------------------------
    access_token_minutes: int = 30
    idle_warning_minutes: int = 25
    password_min_length: int = 12
    max_failed_attempts: int = 5
    lockout_minutes: int = 15
    mfa_required_roles: tuple[str, ...] = ("SIGNATORY", "FINANCE", "ADMIN")
    mfa_issuer: str = "SIBK Fund Management"

    # --- Open decisions (section 13) -----------------------------------------
    # 6: management fee basis and rate.
    default_management_fee_pct: Decimal = Decimal("0.10")
    # 7: final withholding tax on profit paid to the client.
    default_final_wht_rate: Decimal = Decimal("0.00")
    # 8: day basis per counterparty.
    default_day_basis: int = 365
    # 11: number of signatories per instruction (no value thresholds yet).
    required_signatories: int = 2
    # 5: classification of the Taaj receivables balance.
    taaj_receivable_account: str = "1320"
    # 3: tolerance for the opening accrued-profit reasonableness check.
    accrual_tolerance_pct: Decimal = Decimal("0.01")
    accrual_tolerance_abs: Decimal = Decimal("1.00")
    # 13: letterhead / CMA licence details printed on instruction letters.
    firm_name: str = "SIBK Capital Limited"
    firm_address: str = "<ADDRESS PLACEHOLDER>, Nairobi, Kenya"
    firm_contact: str = "Tel <PLACEHOLDER>  |  ops@<PLACEHOLDER>"
    cma_licence_number: str = "<CMA LICENCE NO. PLACEHOLDER>"

    related_party_limit_pct: Decimal = Decimal("0.10")
    record_retention_years: int = 7

    @field_validator("mfa_required_roles", mode="before")
    @classmethod
    def _split_roles(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests that need to re-read the environment."""
    get_settings.cache_clear()
