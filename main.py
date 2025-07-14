from fastapi import FastAPI, Request
from pydantic import BaseModel
from typing import List
import uvicorn

app = FastAPI()

class ForecastRequest(BaseModel):
    product_name: str
    sales_history: List[int]
    stock: int
    gain: float

@app.post("/forecast_and_reorder")
async def forecast_and_reorder(data: ForecastRequest):
    sales = data.sales_history
    stock = data.stock

    # Forecast using 3-week moving average + buffer
    if len(sales) < 3:
        return {"error": "Not enough sales history"}
    
    avg = sum(sales[-3:]) / 3
    forecast = int(avg * 1.1)  # add a 10% buffer
    trend = "increasing" if sales[-1] > sales[-2] else "stable"

    # Reorder logic
    if stock < forecast:
        reorder_qty = forecast - stock + 5
        action = "reorder"
    else:
        reorder_qty = 0
        action = "do_nothing"

    return {
        "product_name": data.product_name,
        "next_week": forecast,
        "trend": trend,
        "action": action,
        "reorder_qty": reorder_qty,
        "confidence": 0.9  # placeholder for future model upgrade
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
