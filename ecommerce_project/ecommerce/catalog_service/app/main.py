from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from .database import get_db, create_tables, Product

app = FastAPI(title="Catalog Service", version="1.0.0",
              description="Browse products — no login required")


@app.on_event("startup")
def startup():
    create_tables()
    # Seed some demo products on first run
    db = next(get_db())
    if db.query(Product).count() == 0:
        seed_products = [
            Product(name="Laptop Pro", description="High-performance laptop", price=999.99, category="electronics", sku="ELEC-001"),
            Product(name="Wireless Mouse", description="Ergonomic wireless mouse", price=29.99, category="electronics", sku="ELEC-002"),
            Product(name="Desk Chair", description="Comfortable office chair", price=249.99, category="furniture", sku="FURN-001"),
            Product(name="Python Book", description="Learn Python the hard way", price=39.99, category="books", sku="BOOK-001"),
            Product(name="Standing Desk", description="Adjustable standing desk", price=499.99, category="furniture", sku="FURN-002"),
        ]
        db.add_all(seed_products)
        db.commit()
    db.close()


# ── Schemas ────────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    price: float
    category: Optional[str] = "general"
    sku: str


class ProductOut(BaseModel):
    id: int
    name: str
    description: str
    price: float
    category: str
    sku: str

    class Config:
        from_attributes = True


# ── Routes ─────────────────────────────────────────────────────────────────

@app.get("/products", response_model=List[ProductOut])
def list_products(
    category: Optional[str] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db)
):
    """List all products. Optionally filter by category. NO login required."""
    query = db.query(Product)
    if category:
        query = query.filter(Product.category == category)
    return query.all()


@app.get("/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    """Get a single product by ID."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@app.get("/products/sku/{sku}", response_model=ProductOut)
def get_product_by_sku(sku: str, db: Session = Depends(get_db)):
    """Get a product by its SKU. Used by Order Service to validate items."""
    product = db.query(Product).filter(Product.sku == sku).first()
    if not product:
        raise HTTPException(status_code=404, detail=f"Product with SKU '{sku}' not found")
    return product


@app.post("/products", response_model=ProductOut, status_code=201)
def create_product(product_data: ProductCreate, db: Session = Depends(get_db)):
    """
    Add a new product to the catalog.
    In production this would be employee-only (checked at API gateway level).
    """
    existing = db.query(Product).filter(Product.sku == product_data.sku).first()
    if existing:
        raise HTTPException(status_code=400, detail="Product with this SKU already exists")

    product = Product(**product_data.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()


@app.get("/health")
def health():
    return {"status": "ok", "service": "catalog_service"}
