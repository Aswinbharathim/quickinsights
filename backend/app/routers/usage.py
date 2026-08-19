from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Query

from app import store
from app.database import SessionLocal
from app.db_models import TokenUsageEventRow
from app.models import (
    RecentUsageItem,
    UsageBreakdownItem,
    UsageMetricSummary,
    UsageOverviewResponse,
    UsageTrendItem,
)

router = APIRouter(prefix="/api/usage", tags=["usage"])

CREDIT_CONVERSION_RATE = 100.0  # $1.00 USD = 100 Credits (1 Credit = $0.01 USD)
DEFAULT_TOTAL_BUDGET_CREDITS = 10000.0  # 10,000 Credits default pool ($100 USD value)


def _cost_to_credits(cost_usd: float) -> float:
    return round(cost_usd * CREDIT_CONVERSION_RATE, 2)


def _build_metric_summary(events: list[TokenUsageEventRow]) -> UsageMetricSummary:
    total_requests = len(events)
    total_tokens = sum(e.total_tokens or 0 for e in events)
    prompt_tokens = sum(e.prompt_tokens or 0 for e in events)
    completion_tokens = sum(e.completion_tokens or 0 for e in events)
    estimated_cost_usd = round(sum(e.estimated_cost_usd or 0.0 for e in events), 6)
    credits_used = _cost_to_credits(estimated_cost_usd)
    credits_remaining = max(0.0, round(DEFAULT_TOTAL_BUDGET_CREDITS - credits_used, 2))
    
    llm_requests = sum(1 for e in events if e.category == "llm")
    embedding_requests = sum(1 for e in events if e.category == "embedding")
    cached_requests = sum(1 for e in events if (e.prompt_tokens or 0) == 0 and e.category == "llm")

    return UsageMetricSummary(
        total_requests=total_requests,
        total_tokens=total_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimated_cost_usd,
        credits_used=credits_used,
        credits_remaining=credits_remaining,
        total_budget_credits=DEFAULT_TOTAL_BUDGET_CREDITS,
        llm_requests=llm_requests,
        embedding_requests=embedding_requests,
        cached_requests=cached_requests,
    )


@router.get("/overview", response_model=UsageOverviewResponse)
def get_usage_overview(
    days: Optional[int] = Query(default=None, ge=0),
    connection_id: Optional[str] = None,
    model: Optional[str] = None,
    operation: Optional[str] = None,
):
    with SessionLocal() as s:
        query = s.query(TokenUsageEventRow)
        
        if connection_id:
            query = query.filter(TokenUsageEventRow.connection_id == connection_id)
        if model:
            query = query.filter(TokenUsageEventRow.model == model)
        if operation:
            query = query.filter(TokenUsageEventRow.operation == operation)
            
        now_dt = datetime.now(timezone.utc)
        if days and days > 0:
            cutoff = (now_dt - timedelta(days=days)).isoformat()
            query = query.filter(TokenUsageEventRow.created_at >= cutoff)

        all_events = query.all()

    # Connections lookup dict
    conn_map = {conn.id: conn.name for conn in store.connections_store.values()}

    # Calculate Overall
    overall = _build_metric_summary(all_events)

    # Time boundaries (UTC)
    today_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now_dt - timedelta(days=now_dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    month_start = now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    today_events = [e for e in all_events if e.created_at >= today_start]
    week_events = [e for e in all_events if e.created_at >= week_start]
    month_events = [e for e in all_events if e.created_at >= month_start]

    today = _build_metric_summary(today_events)
    this_week = _build_metric_summary(week_events)
    this_month = _build_metric_summary(month_events)

    # Breakdown by Model
    model_groups: dict[str, list[TokenUsageEventRow]] = {}
    for e in all_events:
        m_name = e.model or "unknown"
        model_groups.setdefault(m_name, []).append(e)

    by_model = [
        UsageBreakdownItem(
            name=m_name,
            requests=len(evs),
            prompt_tokens=sum(e.prompt_tokens or 0 for e in evs),
            completion_tokens=sum(e.completion_tokens or 0 for e in evs),
            total_tokens=sum(e.total_tokens or 0 for e in evs),
            estimated_cost_usd=round(sum(e.estimated_cost_usd or 0.0 for e in evs), 6),
            credits_used=_cost_to_credits(sum(e.estimated_cost_usd or 0.0 for e in evs)),
        )
        for m_name, evs in sorted(model_groups.items(), key=lambda x: sum(e.estimated_cost_usd or 0 for e in x[1]), reverse=True)
    ]

    # Breakdown by Operation
    op_groups: dict[str, list[TokenUsageEventRow]] = {}
    for e in all_events:
        op_name = e.operation or "unknown"
        op_groups.setdefault(op_name, []).append(e)

    by_operation = [
        UsageBreakdownItem(
            name=op_name,
            requests=len(evs),
            prompt_tokens=sum(e.prompt_tokens or 0 for e in evs),
            completion_tokens=sum(e.completion_tokens or 0 for e in evs),
            total_tokens=sum(e.total_tokens or 0 for e in evs),
            estimated_cost_usd=round(sum(e.estimated_cost_usd or 0.0 for e in evs), 6),
            credits_used=_cost_to_credits(sum(e.estimated_cost_usd or 0.0 for e in evs)),
        )
        for op_name, evs in sorted(op_groups.items(), key=lambda x: len(x[1]), reverse=True)
    ]

    # Breakdown by Connection
    conn_groups: dict[str, list[TokenUsageEventRow]] = {}
    for e in all_events:
        c_id = e.connection_id or "global"
        conn_groups.setdefault(c_id, []).append(e)

    by_connection = [
        UsageBreakdownItem(
            name=conn_map.get(c_id, "Global / Internal System") if c_id != "global" else "Global / Internal System",
            requests=len(evs),
            prompt_tokens=sum(e.prompt_tokens or 0 for e in evs),
            completion_tokens=sum(e.completion_tokens or 0 for e in evs),
            total_tokens=sum(e.total_tokens or 0 for e in evs),
            estimated_cost_usd=round(sum(e.estimated_cost_usd or 0.0 for e in evs), 6),
            credits_used=_cost_to_credits(sum(e.estimated_cost_usd or 0.0 for e in evs)),
        )
        for c_id, evs in sorted(conn_groups.items(), key=lambda x: len(x[1]), reverse=True)
    ]

    # Recent Events
    sorted_events = sorted(all_events, key=lambda e: e.created_at, reverse=True)[:30]
    recent_events = [
        RecentUsageItem(
            id=e.id,
            created_at=e.created_at,
            connection_name=conn_map.get(e.connection_id, "Global / Internal System") if e.connection_id else "Global / Internal System",
            operation=e.operation,
            category=e.category,
            provider=e.provider,
            model=e.model,
            prompt_tokens=e.prompt_tokens or 0,
            completion_tokens=e.completion_tokens or 0,
            total_tokens=e.total_tokens or 0,
            estimated_cost_usd=round(e.estimated_cost_usd or 0.0, 6),
            credits_used=_cost_to_credits(e.estimated_cost_usd or 0.0),
        )
        for e in sorted_events
    ]

    return UsageOverviewResponse(
        overall=overall,
        today=today,
        this_week=this_week,
        this_month=this_month,
        by_model=by_model,
        by_operation=by_operation,
        by_connection=by_connection,
        recent_events=recent_events,
    )


@router.get("/trends", response_model=list[UsageTrendItem])
def get_usage_trends(
    days: Optional[int] = Query(default=14, ge=1, le=365),
    connection_id: Optional[str] = None,
    model: Optional[str] = None,
    operation: Optional[str] = None,
):
    with SessionLocal() as s:
        query = s.query(TokenUsageEventRow)
        if connection_id:
            query = query.filter(TokenUsageEventRow.connection_id == connection_id)
        if model:
            query = query.filter(TokenUsageEventRow.model == model)
        if operation:
            query = query.filter(TokenUsageEventRow.operation == operation)

        now_dt = datetime.now(timezone.utc)
        cutoff = (now_dt - timedelta(days=days)).isoformat()
        query = query.filter(TokenUsageEventRow.created_at >= cutoff)

        events = query.all()

    # Aggregate by Date (YYYY-MM-DD)
    date_groups: dict[str, list[TokenUsageEventRow]] = {}
    
    # Pre-fill all dates in the range to ensure continuous timeline
    for i in range(days - 1, -1, -1):
        dt_str = (now_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        date_groups[dt_str] = []

    for e in events:
        if e.created_at:
            d_str = e.created_at[:10]
            if d_str in date_groups:
                date_groups[d_str].append(e)

    trends = [
        UsageTrendItem(
            date=d_str,
            requests=len(evs),
            prompt_tokens=sum(e.prompt_tokens or 0 for e in evs),
            completion_tokens=sum(e.completion_tokens or 0 for e in evs),
            total_tokens=sum(e.total_tokens or 0 for e in evs),
            estimated_cost_usd=round(sum(e.estimated_cost_usd or 0.0 for e in evs), 6),
            credits_used=_cost_to_credits(sum(e.estimated_cost_usd or 0.0 for e in evs)),
        )
        for d_str, evs in sorted(date_groups.items())
    ]

    return trends
