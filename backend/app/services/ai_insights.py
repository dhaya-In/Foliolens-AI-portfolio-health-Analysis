"""AI-written interpretation via the Anthropic Claude API.

The model only ever receives numbers and facts we already computed or fetched; it is told not to
introduce new facts. Its output is labelled "AI interpretation" in the UI, separate from verified data.
When AI_API_KEY is missing we say so explicitly and show rule-based insights labelled as such.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import anthropic

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.schemas import AIInsight, Holding, PortfolioMetrics
from app.services.market_data import _record

log = get_logger(__name__)

NOT_CONFIGURED = ("AI insights are not configured: set AI_API_KEY in backend/.env "
                  "(create a key at https://console.anthropic.com/settings/keys).")


class AIError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


def ai_configured() -> bool:
    s = get_settings()
    return s.ai_provider == "anthropic" and bool(s.ai_api_key)


def _client() -> anthropic.Anthropic:
    s = get_settings()
    return anthropic.Anthropic(api_key=s.ai_api_key, timeout=s.ai_timeout_seconds, max_retries=2)


def _call_json(system: str, user: str, schema: dict, max_tokens: int = 4000) -> dict:
    if not ai_configured():
        raise AIError("not_configured", NOT_CONFIGURED)
    s = get_settings()
    try:
        response = _client().beta.messages.create(
            model=s.ai_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            # Server-side refusal fallback: if the primary model declines, the API retries on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        _record("anthropic", False, "authentication failed")
        raise AIError("auth", "The AI provider rejected AI_API_KEY (invalid, revoked or expired).") from exc
    except anthropic.PermissionDeniedError as exc:
        _record("anthropic", False, "permission denied")
        raise AIError("auth", "The AI API key lacks permission for this model.") from exc
    except anthropic.NotFoundError as exc:
        _record("anthropic", False, "model not found")
        raise AIError("bad_config", f"AI model '{s.ai_model}' was not found. Check AI_MODEL.") from exc
    except anthropic.RateLimitError as exc:
        _record("anthropic", False, "rate limited")
        raise AIError("rate_limited", "The AI provider is rate-limiting requests. Try again shortly.") from exc
    except anthropic.APIStatusError as exc:
        _record("anthropic", False, f"HTTP {exc.status_code}")
        raise AIError("unavailable", f"The AI provider returned an error (HTTP {exc.status_code}).") from exc
    except anthropic.APIConnectionError as exc:
        _record("anthropic", False, "connection error")
        raise AIError("unavailable", "Could not reach the AI provider (network error or timeout).") from exc

    if response.stop_reason == "refusal":
        raise AIError("refused", "The AI model declined to produce this analysis.")
    if response.stop_reason == "max_tokens":
        raise AIError("truncated", "The AI response was cut off. Try again.")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise AIError("bad_response", "The AI response could not be parsed.") from exc
    _record("anthropic", True)
    return data


# ------------------------------------------------------------------ portfolio insights

PORTFOLIO_SYSTEM = """You are a portfolio analyst writing for a beginner investor.
You are given pre-calculated portfolio metrics. Write exactly 3 insights:
one "risk", one "positive", one "suggestion".
Rules:
- Each insight MUST cite at least one specific number from the data given.
- Do NOT give generic advice that could apply to any portfolio.
- Do NOT invent numbers, events or facts not provided. Do not predict prices.
- Each insight under 45 words, plain language, no unexplained jargon."""

PORTFOLIO_SCHEMA = {
    "type": "object",
    "properties": {"insights": {"type": "array", "items": {
        "type": "object",
        "properties": {"insight_type": {"type": "string", "enum": ["risk", "positive", "suggestion"]},
                       "content": {"type": "string"}},
        "required": ["insight_type", "content"], "additionalProperties": False}}},
    "required": ["insights"], "additionalProperties": False,
}


def _build_summary(holdings: list[Holding], metrics: PortfolioMetrics, currency: str | None) -> str:
    priced = [h for h in holdings if h.gain_loss_pct is not None]
    sorted_h = sorted(priced, key=lambda h: h.gain_loss_pct, reverse=True)
    lines = [
        f"Total portfolio value: {metrics.total_value} {currency or ''}",
        f"Total gain/loss: {metrics.total_gain_loss_pct}%",
        f"Number of priced holdings: {len(priced)}",
        f"Diversification score: {metrics.diversification_score}/100",
        f"Top holding: {metrics.top_holding_ticker} at {metrics.concentration_top_holding_pct}%",
        f"Top sector: {metrics.top_sector} at {metrics.concentration_top_sector_pct}%",
        f"Portfolio beta: {metrics.portfolio_beta if metrics.portfolio_beta is not None else 'unavailable'} "
        f"(market = 1.0; covers {metrics.beta_coverage_pct}% of value)",
        f"Health score: {metrics.health_score}/100",
    ]
    if sorted_h:
        lines.append(f"Best performer: {sorted_h[0].ticker} ({sorted_h[0].gain_loss_pct:.1f}%)")
        lines.append(f"Worst performer: {sorted_h[-1].ticker} ({sorted_h[-1].gain_loss_pct:.1f}%)")
    return "\n".join(lines)


def rule_based_insights(metrics: PortfolioMetrics) -> list[AIInsight]:
    beta_txt = (f"Portfolio beta is {metrics.portfolio_beta}: it has historically moved "
                f"{'more' if metrics.portfolio_beta > 1 else 'less'} than the market. Check that this matches your risk appetite."
                if metrics.portfolio_beta is not None else
                "Beta data was unavailable for your holdings, so market sensitivity could not be estimated.")
    return [
        AIInsight(insight_type="risk", content=(
            f"{metrics.top_sector} makes up {metrics.concentration_top_sector_pct}% of your portfolio and "
            f"{metrics.top_holding_ticker} alone is {metrics.concentration_top_holding_pct}%. "
            "A downturn in either would have an outsized impact.")),
        AIInsight(insight_type="positive", content=(
            f"Your diversification score is {metrics.diversification_score}/100 - "
            f"{'a good spread across holdings.' if metrics.diversification_score > 60 else 'there is room to spread risk further.'}")),
        AIInsight(insight_type="suggestion", content=beta_txt),
    ]


def portfolio_insights(holdings: list[Holding], metrics: PortfolioMetrics, currency: str | None) -> dict:
    s = get_settings()
    base = {"generated_at": datetime.now(timezone.utc)}
    if not ai_configured():
        return {**base, "source": "rules", "model": None, "notice": NOT_CONFIGURED,
                "insights": [i.model_dump() for i in rule_based_insights(metrics)]}
    try:
        data = _call_json(PORTFOLIO_SYSTEM, _build_summary(holdings, metrics, currency), PORTFOLIO_SCHEMA, 2000)
        insights = [AIInsight(**i).model_dump() for i in data.get("insights", [])][:3]
        if not insights:
            raise AIError("bad_response", "The AI returned no insights.")
        return {**base, "source": "ai", "model": s.ai_model, "notice": None, "insights": insights}
    except AIError as exc:
        return {**base, "source": "rules", "model": None,
                "notice": f"{exc.message} Showing rule-based insights instead.",
                "insights": [i.model_dump() for i in rule_based_insights(metrics)]}


# ------------------------------------------------------------------ stock signal interpretation

SIGNAL_SYSTEM = """You explain a rules-based stock analysis to a retail investor.
You receive JSON with verified data (prices, fundamentals, news headlines with dates) and the
signal our rules computed. Write a short interpretation.
Rules:
- Use ONLY facts present in the JSON. Never add events, numbers, targets or forecasts.
- Do not change or override the computed signal; explain it.
- Do not claim any factor caused a price move; note uncertainty and contradictions.
- Never promise returns or predict prices. This is decision support, not advice.
- Plain language, 120-180 words for "summary"; 2-4 short bullet strings for "key_uncertainties"."""

SIGNAL_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"},
                   "key_uncertainties": {"type": "array", "items": {"type": "string"}}},
    "required": ["summary", "key_uncertainties"], "additionalProperties": False,
}


def interpret_signal(signal: dict) -> dict:
    facts = {
        "stock": f"{signal.get('name')} ({signal.get('symbol')})",
        "price": signal.get("price"), "currency": signal.get("currency"),
        "signal": signal.get("signal"), "why": signal.get("why"),
        "evidence_quality": signal["evidence_quality"]["level"],
        "factors": [{k: f[k] for k in ("name", "available", "value", "contribution", "explanation")}
                    for f in signal["factors"]],
        "positive_news": [{"title": a["title"], "source": a["source"], "published": str(a["published_at"])}
                          for a in signal["news"]["positive"]],
        "negative_news": [{"title": a["title"], "source": a["source"], "published": str(a["published_at"])}
                          for a in signal["news"]["negative"]],
        "risks": signal["risks"],
        "wait_for_lower_price": signal["wait_for_lower_price"],
    }
    data = _call_json(SIGNAL_SYSTEM, json.dumps(facts, default=str), SIGNAL_SCHEMA, 3000)
    return {"summary": data.get("summary", ""), "key_uncertainties": data.get("key_uncertainties", [])[:4],
            "model": get_settings().ai_model, "generated_at": datetime.now(timezone.utc)}
