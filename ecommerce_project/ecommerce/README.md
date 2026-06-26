# E-Commerce Microservices — FastAPI

## Architecture

```
Browser (frontend/index.html)
        │
        ▼
  API Gateway :8000  ←── rate limiting, auth checks, routing
        │
   ┌────┼────────────┐
   ▼    ▼            ▼          ▼
User  Catalog    Warehouse   Order
:8001  :8002      :8003      :8004
  DB    DB          DB         DB
```

Each service has its own SQLite database — **decoupled by design**.

---

## How to Run

### Option A — Docker (recommended)
```bash
# From project root
docker-compose up --build

# Visit:
# API Gateway:      http://localhost:8000/docs
# User Service:     http://localhost:8001/docs
# Catalog Service:  http://localhost:8002/docs
# Warehouse:        http://localhost:8003/docs
# Order Service:    http://localhost:8004/docs
# Frontend:         open frontend/index.html in browser
```

### Option B — Without Docker (run each service manually)
```bash
pip install -r requirements.txt

# Terminal 1
cd user_service && uvicorn app.main:app --port 8001 --reload

# Terminal 2
cd catalog_service && uvicorn app.main:app --port 8002 --reload

# Terminal 3
cd warehouse_service && uvicorn app.main:app --port 8003 --reload

# Terminal 4
cd order_service && uvicorn app.main:app --port 8004 --reload

# Terminal 5
cd api_gateway && uvicorn app.main:app --port 8000 --reload
```

---

## API Flow — What to Demo

### 1. Register a customer and employee
```
POST /auth/register  {"username": "ajay", "password": "pass123", "role": "customer"}
POST /auth/register  {"username": "admin", "password": "pass123", "role": "employee"}
```

### 2. Login → get JWT token
```
POST /auth/login  (form data: username + password)
→ returns: {"access_token": "eyJ...", "role": "customer"}
```

### 3. Browse catalog (NO token needed)
```
GET /catalog/products
```

### 4. Place an order (customer token required)
```
POST /orders
Authorization: Bearer <token>
{"warehouse_id": 1, "items": [{"product_sku": "ELEC-001", "quantity": 2}]}
```

### 5. Employee manages warehouse (employee token required)
```
POST /warehouse/warehouses
Authorization: Bearer <employee_token>
{"name": "East Hub", "location": "Chennai"}
```

---

## Key Concepts — Know These for the Demo

### Why JWT?
- JWT (JSON Web Token) is a signed string that encodes user info (username, role).
- The gateway verifies it by checking the signature with SECRET_KEY — no DB lookup needed.
- If someone tampers with the token, the signature breaks and it's rejected.

### Why bcrypt for passwords?
- Hashing is one-way: even if the DB is stolen, attackers can't reverse the hash.
- bcrypt adds "salt" automatically — same password hashes differently each time.

### Why separate databases per service?
- Coupling: if all services share one DB, you can't deploy/scale them independently.
- The Order Service doesn't need to know how User passwords are stored.

### Why an API Gateway?
- Single entry point → security, rate limiting, and routing in one place.
- The frontend only knows one URL (localhost:8000), not 4 different ports.

### What is rate limiting?
- Prevents abuse: each IP can only make 60 requests per 60 seconds.
- After that, the gateway returns HTTP 429 Too Many Requests.

### Service-to-service communication
- Order Service calls Warehouse Service via HTTP (httpx) to reduce stock.
- This is NOT through the gateway — direct internal calls.

---

## Common Demo Questions — Prepare These Answers

**Q: What happens if Warehouse Service is down when an order is placed?**
A: httpx raises `RequestError` → we catch it and return HTTP 503 with a clear message.

**Q: How would you add a new "discount" feature?**
A: Add a `discount` field to the `Product` model in catalog_service, apply it in the Order Service total calculation. No other service needs to change.

**Q: What's the difference between 401 and 403?**
A: 401 = not authenticated (no token / bad token). 403 = authenticated but not authorized (customer trying to add a warehouse).

**Q: How does the Order Service know the price of a product?**
A: It calls the Catalog Service's `/products/sku/{sku}` endpoint and gets the live price. It doesn't store prices itself.
