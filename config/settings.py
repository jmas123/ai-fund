from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Anthropic
    anthropic_api_key: str = ""

    # Alpaca
    alpaca_key: str = ""
    alpaca_secret: str = ""
    alpaca_paper: bool = True

    # FRED
    fred_api_key: str = ""

    # EIA (Energy Information Administration)
    eia_api_key: str = ""

    # Quiver Quantitative
    quiver_api_key: str = ""

    # Pinecone
    pinecone_api_key: str = ""

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6380

    # --- Hard risk limits ---
    max_single_position: float = Field(default=0.10, description="Max 10% in one position")
    max_drawdown_kill: float = Field(default=0.15, description="15% drawdown halts system")
    max_portfolio_var: float = Field(default=0.05, description="5% daily VaR limit")
    max_sector_exposure: float = Field(default=0.30, description="30% max per sector")

    # --- Models ---
    boss_model: str = "claude-opus-4-6"
    agent_model: str = "claude-sonnet-4-6"
    boss_max_tokens: int = 3500
    agent_max_tokens: int = 1024
    pharma_max_tokens: int = 3000
    quant_max_tokens: int = 2500
    distill_max_tokens: int = 2048
    agent_temperature: float = 0.1
    boss_temperature: float = 0.2

    # --- Alpha engine ---
    agent_weights: dict = Field(default={
        "macro": 0.20, "pharma": 0.20, "tech": 0.15,
        "energy": 0.15, "political": 0.15, "science": 0.05, "quant": 0.10,
    })
    alpha_threshold: float = Field(default=0.25, description="Min |score| to trade")
    vol_target: float = Field(default=0.15, description="Annualized portfolio vol target")
    horizon_discounts: dict = Field(default={"30d": 1.0, "90d": 0.7, "180d": 0.4})

    # --- Scenario engine ---
    scenario_n_paths: int = Field(default=2000, description="Monte Carlo paths per ticker")
    scenario_horizon: int = Field(default=30, description="Simulation horizon in trading days")
    scenario_drift_scale: float = Field(default=0.0004, description="Daily drift per unit of alpha score")
    scenario_disagreement_vol_boost: float = Field(default=0.3, description="Vol multiplier for max disagreement")
    scenario_downside_penalty_threshold: float = Field(default=0.20, description="p_down_10pct above this penalizes weight")
    scenario_dispersion_penalty_threshold: float = Field(default=0.40, description="Dispersion above this penalizes weight")

    # --- Memory ---
    episodic_confidence_gate: float = 0.70
    min_trades_for_distillation: int = 5

    @property
    def alpaca_base_url(self) -> str:
        if self.alpaca_paper:
            return "https://paper-api.alpaca.markets"
        return "https://api.alpaca.markets"


settings = Settings()
