from app.models.schemas import Holding, PortfolioMetrics


def calculate_sector_breakdown(holdings: list[Holding]) -> dict[str, float]:
    total_value = sum(h.current_value for h in holdings)
    if total_value == 0:
        return {}
    sector_totals: dict[str, float] = {}
    for h in holdings:
        sector = h.sector or "Unknown"
        sector_totals[sector] = sector_totals.get(sector, 0) + h.current_value
    breakdown = {s: round((v / total_value) * 100, 2) for s, v in sector_totals.items()}
    return dict(sorted(breakdown.items(), key=lambda kv: kv[1], reverse=True))


def calculate_diversification_score(holdings: list[Holding]) -> float:
    total_value = sum(h.current_value for h in holdings)
    if total_value == 0 or len(holdings) == 0:
        return 0.0
    weights = [h.current_value / total_value for h in holdings]
    hhi = sum(w ** 2 for w in weights)
    n = len(holdings)
    if n == 1:
        return 0.0
    min_hhi = 1 / n
    score = (1 - hhi) / (1 - min_hhi) * 100
    return round(max(0.0, min(100.0, score)), 2)


def calculate_concentration(holdings: list[Holding]) -> tuple[float, str, float, str]:
    total_value = sum(h.current_value for h in holdings)
    if total_value == 0 or not holdings:
        return 0.0, "N/A", 0.0, "N/A"
    top_holding = max(holdings, key=lambda h: h.current_value)
    top_holding_pct = round((top_holding.current_value / total_value) * 100, 2)
    sector_breakdown = calculate_sector_breakdown(holdings)
    # "Unknown" means missing data, not a real sector - don't report it as a concentration.
    known = {k: v for k, v in sector_breakdown.items() if k != "Unknown"}
    top_sector, top_sector_pct = next(iter(known.items()), ("Unknown", 0.0))
    return top_holding_pct, top_holding.ticker, top_sector_pct, top_sector


def calculate_portfolio_beta(holdings: list[Holding], betas: dict[str, float | None]) -> tuple[float | None, float]:
    """Value-weighted beta over holdings whose beta is known. Returns (beta or None, coverage %)."""
    total_value = sum(h.current_value for h in holdings)
    total_known_value = 0.0
    weighted_sum = 0.0
    for h in holdings:
        beta = betas.get(h.ticker)
        if beta is None:
            continue
        weighted_sum += h.current_value * beta
        total_known_value += h.current_value
    if total_known_value == 0:
        return None, 0.0
    coverage = round(total_known_value / total_value * 100, 1) if total_value else 0.0
    return round(weighted_sum / total_known_value, 3), coverage


def calculate_health_score(diversification_score, top_holding_pct, top_sector_pct, portfolio_beta) -> float:
    diversification_component = diversification_score
    holding_penalty = max(0, top_holding_pct - 10)
    holding_component = max(0, 100 - holding_penalty * 2)
    sector_penalty = max(0, top_sector_pct - 25)
    sector_component = max(0, 100 - sector_penalty * 1.5)
    if portfolio_beta is None:
        # Beta unavailable: re-weight the remaining components instead of assuming a beta of 1.0.
        return round((diversification_component * 0.40 + holding_component * 0.25
                      + sector_component * 0.20) / 0.85, 2)
    beta_distance = abs(portfolio_beta - 1.0)
    beta_component = max(0, 100 - beta_distance * 60)
    health_score = (
        diversification_component * 0.40
        + holding_component * 0.25
        + sector_component * 0.20
        + beta_component * 0.15
    )
    return round(health_score, 2)


def compute_all_metrics(holdings: list[Holding], betas: dict[str, float | None]) -> PortfolioMetrics:
    """Metrics over *priced* holdings only - unpriced holdings are reported separately by the caller."""
    holdings = [h for h in holdings if h.priced]
    total_value = sum(h.current_value for h in holdings)
    total_cost = sum(h.cost_basis for h in holdings)
    total_gain_loss_pct = round(((total_value - total_cost) / total_cost) * 100, 2) if total_cost > 0 else 0.0
    diversification_score = calculate_diversification_score(holdings)
    top_holding_pct, top_holding_ticker, top_sector_pct, top_sector = calculate_concentration(holdings)
    portfolio_beta, beta_coverage = calculate_portfolio_beta(holdings, betas)
    health_score = calculate_health_score(diversification_score, top_holding_pct, top_sector_pct, portfolio_beta)
    return PortfolioMetrics(
        diversification_score=diversification_score,
        concentration_top_holding_pct=top_holding_pct,
        concentration_top_sector_pct=top_sector_pct,
        top_holding_ticker=top_holding_ticker,
        top_sector=top_sector,
        portfolio_beta=portfolio_beta,
        beta_coverage_pct=beta_coverage,
        health_score=health_score,
        total_value=round(total_value, 2),
        total_gain_loss_pct=total_gain_loss_pct,
    )
