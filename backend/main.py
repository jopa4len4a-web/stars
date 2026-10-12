from contextlib import asynccontextmanager
from decimal import Decimal
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from .config import settings
from .db import Base, engine, SessionLocal
from .models import Setting, Order
from .security import validate_telegram_init_data
from .crypto import encrypt_secret

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(title="SellStars API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.app_url, "http://localhost:3000"], allow_credentials=False, allow_methods=["GET","POST","PUT"], allow_headers=["*"])

async def db_session():
    async with SessionLocal() as session:
        yield session

def telegram_user(x_telegram_init_data: str = Header(default="")):
    try:
        return validate_telegram_init_data(x_telegram_init_data)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Telegram authentication failed: {exc}")

def require_admin(user=Depends(telegram_user)):
    if (user.get("username") or "").casefold() != settings.admin_username.casefold():
        raise HTTPException(status_code=403, detail="Admin only")
    return user

class OrderIn(BaseModel):
    recipient_username: str = Field(min_length=3, max_length=32)
    stars: int = Field(ge=100, le=100000)

class SettingIn(BaseModel):
    platega_merchant_id: str = ""
    platega_secret: str = ""
    fragment_api_url: str = ""
    fragment_api_key: str = ""

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/catalog")
async def catalog():
    return {"unit_price": 1.50, "minimum_stars": 100, "currency": "RUB", "provider_status": "manual_setup_required"}

@app.post("/api/orders")
async def create_order(payload: OrderIn, user=Depends(telegram_user), db: AsyncSession = Depends(db_session)):
    recipient = payload.recipient_username.strip().lstrip("@")
    if not recipient.replace("_", "").isalnum():
        raise HTTPException(status_code=422, detail="Invalid Telegram username")
    price = Decimal("1.50")
    total = price * payload.stars
    order = Order(
        telegram_user_id=str(user["id"]),
        telegram_username=user.get("username", ""),
        recipient_username=recipient,
        stars=payload.stars,
        unit_price=float(price),
        total_price=float(total),
        status="awaiting_provider_setup",
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return {"order_id": order.id, "stars": order.stars, "total_price": str(total), "currency": "RUB", "status": order.status,
            "message": "Заказ создан. Оплата и доставка не включены до настройки проверенных интеграций."}

@app.get("/api/orders")
async def my_orders(user=Depends(telegram_user), db: AsyncSession = Depends(db_session)):
    result = await db.execute(select(Order).where(Order.telegram_user_id == str(user["id"])).order_by(Order.id.desc()).limit(50))
    rows = result.scalars().all()
    return [{"id": x.id, "stars": x.stars, "recipient": x.recipient_username, "total": str(x.total_price), "status": x.status, "created_at": x.created_at.isoformat() if x.created_at else None} for x in rows]

@app.get("/api/admin/overview")
async def admin_overview(user=Depends(require_admin), db: AsyncSession = Depends(db_session)):
    total_orders = await db.scalar(select(func.count()).select_from(Order)) or 0
    total_amount = await db.scalar(select(func.coalesce(func.sum(Order.total_price), 0)).select_from(Order)) or 0
    return {"admin": user.get("username"), "orders": total_orders, "gross_rub": str(total_amount), "unit_price": 1.50, "minimum_stars": 100}

@app.get("/api/admin/settings")
async def admin_settings(user=Depends(require_admin), db: AsyncSession = Depends(db_session)):
    result = await db.execute(select(Setting))
    values = {item.key: item.value for item in result.scalars().all()}
    # Never send saved secrets back to browser.
    return {"platega_merchant_id": values.get("platega_merchant_id", ""), "platega_secret_configured": bool(values.get("platega_secret")),
            "fragment_api_url": values.get("fragment_api_url", ""), "fragment_api_key_configured": bool(values.get("fragment_api_key"))}

@app.put("/api/admin/settings")
async def update_settings(payload: SettingIn, user=Depends(require_admin), db: AsyncSession = Depends(db_session)):
    if not settings.master_key:
        raise HTTPException(status_code=503, detail="MASTER_KEY is not configured on server")
    vals = {"platega_merchant_id": payload.platega_merchant_id.strip(),
            "fragment_api_url": payload.fragment_api_url.strip()}
    if payload.platega_secret.strip():
        vals["platega_secret"] = encrypt_secret(payload.platega_secret.strip())
    if payload.fragment_api_key.strip():
        vals["fragment_api_key"] = encrypt_secret(payload.fragment_api_key.strip())
    for key, value in vals.items():
        row = await db.get(Setting, key)
        if row:
            row.value = value
        else:
            db.add(Setting(key=key, value=value))
    await db.commit()
    return {"ok": True, "message": "Настройки сохранены. Секреты не возвращаются в браузер."}

@app.get("/api/admin/orders")
async def admin_orders(user=Depends(require_admin), db: AsyncSession = Depends(db_session)):
    result = await db.execute(select(Order).order_by(Order.id.desc()).limit(100))
    return [{"id": x.id, "user": x.telegram_username or x.telegram_user_id, "recipient": x.recipient_username, "stars": x.stars, "total": str(x.total_price), "status": x.status} for x in result.scalars().all()]
