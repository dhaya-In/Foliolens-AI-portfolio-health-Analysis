from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, WatchlistItem
from app.db.session import get_db
from app.deps import get_current_user
from app.models.schemas import WatchlistIn, WatchlistUpdate
from app.services import market_data
from app.services.auth_service import log_activity
from app.services.http_client import ProviderError

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])
MAX_ITEMS = 50


def _owned(db: Session, user: User, item_id: int) -> WatchlistItem:
    item = db.scalar(select(WatchlistItem).where(WatchlistItem.id == item_id, WatchlistItem.user_id == user.id))
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")
    return item


def _check_alerts(above, below):
    if above is not None and below is not None and below >= above:
        raise HTTPException(status_code=422, detail="The 'below' alert must be lower than the 'above' alert.")


@router.get("")
def list_items(refresh: bool = False, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(WatchlistItem).where(WatchlistItem.user_id == user.id)
                       .order_by(WatchlistItem.created_at)).all()
    quotes = market_data.get_quotes([i.symbol for i in items], force=refresh) if items else {}
    out = []
    for i in items:
        q = quotes.get(i.symbol)
        err = q.public() if isinstance(q, ProviderError) else None
        q = q if isinstance(q, dict) else None
        triggered = []
        if q and i.alert_above is not None and q["price"] >= i.alert_above:
            triggered.append("above")
        if q and i.alert_below is not None and q["price"] <= i.alert_below:
            triggered.append("below")
        out.append({"id": i.id, "symbol": i.symbol, "note": i.note, "alert_above": i.alert_above,
                    "alert_below": i.alert_below, "created_at": i.created_at, "quote": q, "error": err,
                    "alerts_triggered": triggered})
    return {"items": out}


@router.post("", status_code=status.HTTP_201_CREATED)
def add_item(body: WatchlistIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check_alerts(body.alert_above, body.alert_below)
    count = len(db.scalars(select(WatchlistItem.id).where(WatchlistItem.user_id == user.id)).all())
    if count >= MAX_ITEMS:
        raise HTTPException(status_code=422, detail=f"Watchlist is limited to {MAX_ITEMS} symbols.")
    try:
        symbol = market_data.resolve_symbol(body.symbol)
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=exc.message)
    if not symbol:
        raise HTTPException(status_code=404, detail=f"No market listing found for {body.symbol}.")
    if db.scalar(select(WatchlistItem.id).where(WatchlistItem.user_id == user.id, WatchlistItem.symbol == symbol)):
        raise HTTPException(status_code=409, detail=f"{symbol} is already on your watchlist.")
    item = WatchlistItem(user_id=user.id, symbol=symbol, note=body.note.strip(),
                         alert_above=body.alert_above, alert_below=body.alert_below)
    db.add(item)
    log_activity(db, user.id, "watchlist", f"Added {symbol} to watchlist.")
    db.commit()
    return {"id": item.id, "symbol": item.symbol}


@router.put("/{item_id}")
def update_item(item_id: int, body: WatchlistUpdate, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    _check_alerts(body.alert_above, body.alert_below)
    item = _owned(db, user, item_id)
    item.note, item.alert_above, item.alert_below = body.note.strip(), body.alert_above, body.alert_below
    db.commit()
    return {"id": item.id, "symbol": item.symbol}


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = _owned(db, user, item_id)
    log_activity(db, user.id, "watchlist", f"Removed {item.symbol} from watchlist.")
    db.delete(item)
    db.commit()
