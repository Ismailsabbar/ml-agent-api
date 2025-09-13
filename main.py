import os
from typing import Optional, List
from datetime import date, timedelta
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text

# --- Config ---
DATABASE_URL = os.getenv("DATABASE_URL")  # e.g., postgres://user:pass@host:port/db
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is required")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# --- API ---
app = FastAPI(title="Inventory ML API")

class RequestById(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None

class MLResponse(BaseModel):
    product_id: int
    product_name: str
    next_week: int
    trend: str
    action: str
    reorder_qty: int
    confidence: float

def _get_product(conn, product_id=None, product_name=None):
    if product_id is not None:
        q = text("""select * from products where id=:pid and active is true""")
        row = conn.execute(q, {"pid": product_id}).mappings().first()
    else:
        q = text("""select * from products where lower(name)=lower(:pname) and active is true""")
        row = conn.execute(q, {"pname": product_name}).mappings().first()
    return row

def _get_recent_sales(conn, pid: int, weeks: int = 8) -> List[int]:
    q = text("""
      select qty
      from sales
      where product_id=:pid
      order by week_start desc
      limit :lim
    """)
    rows = conn.execute(q, {"pid": pid, "lim": weeks}).fetchall()
    return [r[0] for r in rows][::-1]  # oldest->newest

def _moving_average_fcst(sales: List[int], k: int = 3, buffer: float = 0.10) -> int:
    if len(sales) == 0:
        return 0
    base = sum(sales[-k:]) / min(k, len(sales))
    return int(round(base * (1 + buffer)))

def _trend(sales: List[int]) -> str:
    if len(sales) < 2: 
        return "stable"
    return "increasing" if sales[-1] > sales[-2] else ("declining" if sales[-1] < sales[-2] else "stable")

def _reorder_calc(stock_on_hand: int, weekly_fcst: int, lead_time_days: int, moq: int, safety_stock: int):
    lead_weeks = max(1, round(lead_time_days / 7))
    reorder_point = weekly_fcst * lead_weeks + safety_stock
    if stock_on_hand < reorder_point:
        gap = reorder_point - stock_on_hand
        reorder_qty = max(moq, gap)
        return "reorder", reorder_qty
    return "do_nothing", 0

@app.post("/forecast_and_reorder", response_model=MLResponse)
def forecast_and_reorder(payload: RequestById):
    if not payload.product_id and not payload.product_name:
        raise HTTPException(400, "Provide product_id OR product_name")

    with engine.begin() as conn:
        prod = _get_product(conn, payload.product_id, payload.product_name)
        if not prod:
            raise HTTPException(404, "Product not found")

        sales_series = _get_recent_sales(conn, prod["id"], weeks=8)
        fcst = _moving_average_fcst(sales_series, k=3, buffer=0.10)
        tr = _trend(sales_series)
        action, qty = _reorder_calc(
            stock_on_hand=prod["stock_on_hand"],
            weekly_fcst=fcst,
            lead_time_days=prod["lead_time_days"] or 7,
            moq=prod["moq"] or 0,
            safety_stock=prod["safety_stock"] or 0
        )
        resp = MLResponse(
            product_id=prod["id"],
            product_name=prod["name"],
            next_week=fcst,
            trend=tr,
            action=action,
            reorder_qty=qty,
            confidence=0.90
        )

        # write to forecast_log
        conn.execute(text("""
          insert into forecast_log (product_id, next_week, trend, action, reorder_qty, confidence)
          values (:pid, :nw, :tr, :ac, :rq, :conf)
        """), {"pid": resp.product_id, "nw": resp.next_week, "tr": resp.trend, "ac": resp.action, "rq": resp.reorder_qty, "conf": resp.confidence})

        return resp

@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("select 1"))
    return {"ok": True}
