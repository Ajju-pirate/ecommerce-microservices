from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from .database import get_db, create_tables, Warehouse, InventoryItem
from .auth import require_employee, get_current_user

app = FastAPI(title="Warehouse Service", version="1.0.0")


@app.on_event("startup")
def startup():
    create_tables()
    # Seed demo warehouses
    db = next(get_db())
    if db.query(Warehouse).count() == 0:
        warehouses = [
            Warehouse(name="North Hub", location="Delhi"),
            Warehouse(name="South Hub", location="Hyderabad"),
            Warehouse(name="West Hub", location="Mumbai"),
        ]
        db.add_all(warehouses)
        db.commit()
        # Add some inventory
        items = [
            InventoryItem(warehouse_id=1, product_sku="ELEC-001", product_name="Laptop Pro", quantity=50),
            InventoryItem(warehouse_id=1, product_sku="ELEC-002", product_name="Wireless Mouse", quantity=200),
            InventoryItem(warehouse_id=2, product_sku="FURN-001", product_name="Desk Chair", quantity=30),
            InventoryItem(warehouse_id=3, product_sku="BOOK-001", product_name="Python Book", quantity=100),
        ]
        db.add_all(items)
        db.commit()
    db.close()


# ── Schemas ────────────────────────────────────────────────────────────────

class WarehouseCreate(BaseModel):
    name: str
    location: str


class WarehouseUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None


class WarehouseOut(BaseModel):
    id: int
    name: str
    location: str

    class Config:
        from_attributes = True


class InventoryItemCreate(BaseModel):
    product_sku: str
    product_name: str
    quantity: int


class InventoryItemOut(BaseModel):
    id: int
    warehouse_id: int
    product_sku: str
    product_name: str
    quantity: int

    class Config:
        from_attributes = True


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/warehouses", response_model=List[WarehouseOut])
def list_warehouses(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Any logged-in user can see warehouses."""
    return db.query(Warehouse).all()


@app.get("/warehouses/{warehouse_id}", response_model=WarehouseOut)
def get_warehouse(warehouse_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    wh = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return wh


@app.post("/warehouses", response_model=WarehouseOut, status_code=201)
def create_warehouse(data: WarehouseCreate, employee=Depends(require_employee), db: Session = Depends(get_db)):
    """EMPLOYEE ONLY — create a new warehouse."""
    wh = Warehouse(**data.model_dump())
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


@app.patch("/warehouses/{warehouse_id}", response_model=WarehouseOut)
def update_warehouse(warehouse_id: int, data: WarehouseUpdate, employee=Depends(require_employee), db: Session = Depends(get_db)):
    """EMPLOYEE ONLY — update warehouse name or location."""
    wh = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    if data.name:
        wh.name = data.name
    if data.location:
        wh.location = data.location
    db.commit()
    db.refresh(wh)
    return wh


@app.delete("/warehouses/{warehouse_id}", status_code=204)
def delete_warehouse(warehouse_id: int, employee=Depends(require_employee), db: Session = Depends(get_db)):
    """EMPLOYEE ONLY — delete a warehouse."""
    wh = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    db.delete(wh)
    db.commit()


@app.get("/warehouses/{warehouse_id}/inventory", response_model=List[InventoryItemOut])
def get_inventory(warehouse_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """View inventory of a specific warehouse — any logged-in user."""
    return db.query(InventoryItem).filter(InventoryItem.warehouse_id == warehouse_id).all()


@app.post("/warehouses/{warehouse_id}/inventory", response_model=InventoryItemOut, status_code=201)
def add_inventory(warehouse_id: int, data: InventoryItemCreate, employee=Depends(require_employee), db: Session = Depends(get_db)):
    """EMPLOYEE ONLY — add product to a warehouse."""
    wh = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not wh:
        raise HTTPException(status_code=404, detail="Warehouse not found")

    # Check if item already exists, just update quantity
    existing = db.query(InventoryItem).filter(
        InventoryItem.warehouse_id == warehouse_id,
        InventoryItem.product_sku == data.product_sku
    ).first()

    if existing:
        existing.quantity += data.quantity
        db.commit()
        db.refresh(existing)
        return existing

    item = InventoryItem(warehouse_id=warehouse_id, **data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.patch("/warehouses/{warehouse_id}/inventory/{sku}/reduce")
def reduce_inventory(warehouse_id: int, sku: str, quantity: int, db: Session = Depends(get_db)):
    """
    Called internally by Order Service to reduce stock when an order is placed.
    No user auth needed since it's service-to-service communication.
    """
    item = db.query(InventoryItem).filter(
        InventoryItem.warehouse_id == warehouse_id,
        InventoryItem.product_sku == sku
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found in warehouse")
    if item.quantity < quantity:
        raise HTTPException(status_code=400, detail=f"Insufficient stock. Available: {item.quantity}")
    item.quantity -= quantity
    db.commit()
    return {"message": "Stock reduced", "remaining": item.quantity}


@app.get("/health")
def health():
    return {"status": "ok", "service": "warehouse_service"}
