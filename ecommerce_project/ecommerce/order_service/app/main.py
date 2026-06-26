from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import httpx
import os
from jose import jwt, JWTError

from .database import get_db, create_tables, Order, OrderItem

app = FastAPI(title="Order Service", version="1.0.0")

SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey123")
ALGORITHM = "HS256"
WAREHOUSE_URL = os.getenv("WAREHOUSE_SERVICE_URL", "http://localhost:8003")
CATALOG_URL = os.getenv("CATALOG_SERVICE_URL", "http://localhost:8002")


@app.on_event("startup")
def startup():
    create_tables()


# ── Auth dependency ────────────────────────────────────────────────────────

def get_current_user(authorization: str = Header(...)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")
    token = authorization.split(" ")[1]
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── Schemas ────────────────────────────────────────────────────────────────

class OrderItemRequest(BaseModel):
    product_sku: str
    quantity: int


class OrderCreate(BaseModel):
    warehouse_id: int                      # customer chooses or is auto-matched
    items: List[OrderItemRequest]


class OrderItemOut(BaseModel):
    product_sku: str
    product_name: str
    quantity: int
    unit_price: float

    class Config:
        from_attributes = True


class OrderOut(BaseModel):
    id: int
    username: str
    warehouse_id: int
    status: str
    total_price: float
    created_at: datetime
    items: List[OrderItemOut]

    class Config:
        from_attributes = True


# ── Routes ─────────────────────────────────────────────────────────────────

@app.post("/orders", response_model=OrderOut, status_code=201)
async def create_order(order_data: OrderCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Customer places an order.
    Flow:
      1. Validate each product SKU against Catalog Service
      2. Check stock in Warehouse Service
      3. Reduce stock in Warehouse Service
      4. Save order to our DB
    """
    order_items = []
    total = 0.0

    async with httpx.AsyncClient() as client:
        for item_req in order_data.items:
            # Step 1: validate product exists in catalog
            try:
                catalog_resp = await client.get(f"{CATALOG_URL}/products/sku/{item_req.product_sku}")
                if catalog_resp.status_code != 200:
                    raise HTTPException(status_code=400, detail=f"Product SKU '{item_req.product_sku}' not found in catalog")
                product = catalog_resp.json()
            except httpx.RequestError:
                raise HTTPException(status_code=503, detail="Catalog service unavailable")

            # Step 2: reduce stock in warehouse (this also validates stock availability)
            try:
                stock_resp = await client.patch(
                    f"{WAREHOUSE_URL}/warehouses/{order_data.warehouse_id}/inventory/{item_req.product_sku}/reduce",
                    params={"quantity": item_req.quantity}
                )
                if stock_resp.status_code != 200:
                    error = stock_resp.json().get("detail", "Stock error")
                    raise HTTPException(status_code=400, detail=error)
            except httpx.RequestError:
                raise HTTPException(status_code=503, detail="Warehouse service unavailable")

            # Step 3: compute line total
            line_total = product["price"] * item_req.quantity
            total += line_total
            order_items.append({
                "product_sku": item_req.product_sku,
                "product_name": product["name"],
                "quantity": item_req.quantity,
                "unit_price": product["price"]
            })

    # Step 4: save order
    order = Order(
        user_id=current_user.get("user_id"),
        username=current_user.get("sub"),
        warehouse_id=order_data.warehouse_id,
        status="confirmed",
        total_price=total
    )
    db.add(order)
    db.flush()   # get the order.id before committing

    for item_data in order_items:
        db.add(OrderItem(order_id=order.id, **item_data))

    db.commit()
    db.refresh(order)
    return order


@app.get("/orders", response_model=List[OrderOut])
def list_my_orders(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Customer sees only their own orders."""
    username = current_user.get("sub")
    return db.query(Order).filter(Order.username == username).all()


@app.get("/orders/all", response_model=List[OrderOut])
def list_all_orders(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """EMPLOYEE ONLY — see all orders across all users."""
    if current_user.get("role") != "employee":
        raise HTTPException(status_code=403, detail="Employees only")
    return db.query(Order).all()


@app.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # Customers can only see their own orders
    if current_user.get("role") == "customer" and order.username != current_user.get("sub"):
        raise HTTPException(status_code=403, detail="Not your order")
    return order


@app.patch("/orders/{order_id}/status")
def update_order_status(order_id: int, status: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """EMPLOYEE ONLY — update order status (e.g. shipped, delivered)."""
    if current_user.get("role") != "employee":
        raise HTTPException(status_code=403, detail="Employees only")
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    valid_statuses = ["pending", "confirmed", "shipped", "delivered", "cancelled"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Status must be one of {valid_statuses}")
    order.status = status
    db.commit()
    return {"message": f"Order {order_id} updated to '{status}'"}


@app.get("/health")
def health():
    return {"status": "ok", "service": "order_service"}
