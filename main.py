import asyncio, hashlib, hmac, json, logging, os, sqlite3, time, uuid
from contextlib import asynccontextmanager
from decimal import Decimal, ROUND_UP
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT=Path(__file__).resolve().parent
DB_PATH=Path(os.getenv('DB_PATH',str(ROOT/'sellstars.db')))
BOT_TOKEN=os.getenv('BOT_TOKEN','').strip()
ADMIN_USERNAME=os.getenv('ADMIN_USERNAME','ownerparadoxy').strip().lstrip('@').casefold()
ADMIN_TELEGRAM_ID=os.getenv('ADMIN_TELEGRAM_ID','').strip()
APP_URL=os.getenv('APP_URL','https://sellstarsss.bothost.tech').strip().rstrip('/')
MASTER_KEY=os.getenv('MASTER_KEY','').strip()
PORT=int(os.getenv('PORT','3000'))
MIN_STARS=100; MAX_STARS=100000
# Telegram requires XTR amounts to be whole Stars. This rate means XTR paid per 100 delivered Stars.
XTR_PER_100_STARS=max(1,int(os.getenv('XTR_PER_100_STARS','10')))
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log=logging.getLogger('sellstars'); bot_task=None; bot_instance=None


def db():
 c=sqlite3.connect(DB_PATH,timeout=20); c.row_factory=sqlite3.Row; return c

def init_db():
 DB_PATH.parent.mkdir(parents=True,exist_ok=True)
 with db() as c:
  c.execute('PRAGMA journal_mode=WAL')
  c.execute('''CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_user_id TEXT NOT NULL, telegram_username TEXT NOT NULL DEFAULT '', recipient_username TEXT NOT NULL, stars INTEGER NOT NULL, total_price TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'XTR', status TEXT NOT NULL DEFAULT 'pending_payment', invoice_payload TEXT UNIQUE, telegram_charge_id TEXT, provider_order_id TEXT, provider_status TEXT, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
  c.execute('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
  # Safe additive migration from the earlier prototype schema.
  columns={r['name'] for r in c.execute('PRAGMA table_info(orders)').fetchall()}
  migrations={
   'currency': "TEXT NOT NULL DEFAULT 'XTR'", 'invoice_payload':'TEXT',
   'telegram_charge_id':'TEXT', 'provider_order_id':'TEXT', 'provider_status':'TEXT',
   'error':'TEXT', 'updated_at':'TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP'
  }
  for name,definition in migrations.items():
   if name not in columns: c.execute(f'ALTER TABLE orders ADD COLUMN {name} {definition}')

def validate_init_data(raw,max_age=86400):
 if not BOT_TOKEN or not raw: raise ValueError('Откройте Mini App из Telegram')
 data=dict(parse_qsl(raw,keep_blank_values=True)); got=data.pop('hash',None)
 if not got: raise ValueError('Нет подписи Telegram')
 try: auth=int(data.get('auth_date','0'))
 except ValueError: raise ValueError('Некорректная дата Telegram')
 if auth<=0 or time.time()-auth>max_age or auth-time.time()>60: raise ValueError('Сессия устарела, откройте Mini App заново')
 check='\n'.join(f'{k}={v}' for k,v in sorted(data.items()))
 secret=hmac.new(b'WebAppData',BOT_TOKEN.encode(),hashlib.sha256).digest()
 calc=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
 if not hmac.compare_digest(calc,got): raise ValueError('Не пройдена проверка подписи Telegram')
 user=json.loads(data.get('user','{}'))
 if not user.get('id'): raise ValueError('Не найден пользователь Telegram')
 return user

def telegram_user(x_telegram_init_data:str=Header(default='')):
 try:return validate_init_data(x_telegram_init_data)
 except Exception as e: raise HTTPException(401,detail=str(e)) from e

def require_admin(user=Depends(telegram_user)):
 if ADMIN_TELEGRAM_ID and str(user.get('id'))!=ADMIN_TELEGRAM_ID: raise HTTPException(403,detail='Нет доступа администратора')
 if not ADMIN_TELEGRAM_ID and (user.get('username') or '').casefold()!=ADMIN_USERNAME: raise HTTPException(403,detail='Нет доступа администратора; задайте ADMIN_TELEGRAM_ID для защиты по ID')
 return user

def encrypt_secret(value):
 if not MASTER_KEY: raise HTTPException(503,detail='На сервере не задан MASTER_KEY')
 try:
  from cryptography.fernet import Fernet
  return Fernet(MASTER_KEY.encode()).encrypt(value.encode()).decode()
 except Exception as e: raise HTTPException(503,detail='MASTER_KEY должен быть Fernet-ключом') from e

def decrypt_secret(value):
 if not value:return ''
 from cryptography.fernet import Fernet
 return Fernet(MASTER_KEY.encode()).decrypt(value.encode()).decode()

def settings():
 with db() as c:return {r['key']:r['value'] for r in c.execute('SELECT key,value FROM settings')}

def set_status(order_id,status,**fields):
 allowed={'telegram_charge_id','provider_order_id','provider_status','error'}
 updates={'status':status,**{k:v for k,v in fields.items() if k in allowed}}
 updates['updated_at']=time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime())
 sql=', '.join(f'{k}=?' for k in updates)
 with db() as c:c.execute(f'UPDATE orders SET {sql} WHERE id=?',(*updates.values(),order_id))

async def fragment_request(method,path,**kwargs):
 cfg=settings(); key=decrypt_secret(cfg.get('fragment_api_key',''))
 if not key: raise RuntimeError('Fragment API key не настроен в админке')
 base=(cfg.get('fragment_api_url') or 'https://v1.fragmentapi.com/api/v1/partner').rstrip('/')
 async with httpx.AsyncClient(timeout=25) as client:
  r=await client.request(method,base+path,headers={'API-Key':key},**kwargs)
  if r.status_code>=400: raise RuntimeError(f'Поставщик вернул HTTP {r.status_code}: {r.text[:300]}')
  return r.json() if r.content else {}

async def deliver_order(order_id):
 with db() as c: row=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
 if not row or row['status'] not in ('paid','delivery_pending'): return
 set_status(order_id,'delivery_pending')
 try:
  found=await fragment_request('GET','/star/recipient/search',params={'username':row['recipient_username'],'quantity':row['stars']})
  if not found.get('success') or not found.get('recipient'): raise RuntimeError('Поставщик не подтвердил получателя')
  # Idempotency key is stable per customer order; retries cannot create a second purchase.
  created=await fragment_request('POST','/orders/star',headers={'Idempotency-Key':str(uuid.uuid5(uuid.NAMESPACE_URL,'sellstars:'+str(order_id)))},json={'username':row['recipient_username'],'recipient_hash':found['recipient'],'quantity':row['stars'],'wallet_type':settings().get('fragment_wallet_type','TON')})
  provider_id=created.get('order_id')
  if not provider_id: raise RuntimeError('Поставщик не вернул order_id')
  set_status(order_id,'delivery_pending',provider_order_id=provider_id,provider_status=created.get('status','pending'))
  for _ in range(30):
   await asyncio.sleep(10)
   status=await fragment_request('GET','/orders/'+str(provider_id))
   state=str(status.get('status','pending')).lower()
   if state=='completed': set_status(order_id,'completed',provider_order_id=provider_id,provider_status=state,error=''); await notify_user(row['telegram_user_id'],f"Заказ #{order_id}: {row['stars']} Stars доставлены пользователю @{row['recipient_username']}."); return
   if state=='failed': set_status(order_id,'delivery_failed',provider_order_id=provider_id,provider_status=state,error=str(status.get('error') or 'Поставщик не выполнил заказ')); await notify_user(row['telegram_user_id'],f'Заказ #{order_id} оплачен, но поставщик сообщил об ошибке. Напишите в поддержку.'); return
  log.warning('Provider order %s remains pending after polling window',provider_id)
 except Exception as e:
  log.exception('Delivery failed for order %s',order_id); set_status(order_id,'delivery_failed',error=str(e)[:500]); await notify_user(row['telegram_user_id'],f'Заказ #{order_id} оплачен, но автоматическая доставка не завершилась. Заказ сохранён для проверки поддержки.')

async def notify_user(user_id,text):
 if bot_instance:
  try: await bot_instance.send_message(int(user_id),text)
  except Exception: log.exception('Could not notify Telegram user %s',user_id)

async def run_bot():
 global bot_instance
 from aiogram import Bot,Dispatcher,F
 from aiogram.filters import CommandStart,Command
 from aiogram.types import Message,InlineKeyboardMarkup,InlineKeyboardButton,WebAppInfo,LabeledPrice,PreCheckoutQuery
 bot_instance=Bot(BOT_TOKEN); dp=Dispatcher()
 @dp.message(CommandStart())
 async def start(m:Message):
  kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Открыть магазин',web_app=WebAppInfo(url=APP_URL))]])
  await m.answer('SellStars\n\nОформите заказ в Mini App. Оплата внутри Telegram проходит в Telegram Stars.',reply_markup=kb)
 @dp.message(Command('paysupport'))
 async def paysupport(m:Message): await m.answer('Поддержка по оплате: ответьте на это сообщение с номером заказа. Не отправляйте платёжные пароли или коды.')
 @dp.pre_checkout_query()
 async def pre_checkout(q:PreCheckoutQuery):
  try:
   oid=int(q.invoice_payload)
   with db() as c: row=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
   if not row or row['status']!='pending_payment' or str(row['telegram_user_id'])!=str(q.from_user.id): raise ValueError('Заказ недоступен')
   expected=max(1,(row['stars']*XTR_PER_100_STARS+99)//100)
   if q.currency!='XTR' or q.total_amount!=expected: raise ValueError('Сумма платежа не совпадает')
   await q.answer(ok=True)
  except Exception: await q.answer(ok=False,error_message='Не удалось проверить заказ. Создайте новый заказ.')
 @dp.message(F.successful_payment)
 async def paid(m:Message):
  p=m.successful_payment
  try: oid=int(p.invoice_payload)
  except Exception: return
  with db() as c: row=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone()
  if not row or str(row['telegram_user_id'])!=str(m.from_user.id): return
  if row['status']!='pending_payment': return
  expected=max(1,(row['stars']*XTR_PER_100_STARS+99)//100)
  if p.currency!='XTR' or p.total_amount!=expected:
   set_status(oid,'payment_review',telegram_charge_id=p.telegram_payment_charge_id,error='Payment amount mismatch'); return
  set_status(oid,'paid',telegram_charge_id=p.telegram_payment_charge_id)
  await m.answer(f'Оплата получена. Заказ #{oid} принят, начинаю доставку Stars.')
  asyncio.create_task(deliver_order(oid))
 @dp.message()
 async def other(m:Message): await m.answer('Нажмите /start, чтобы открыть магазин.')
 try:
  me=await bot_instance.get_me(); log.info('Telegram connected as @%s (%s)',me.username,me.id)
  await bot_instance.delete_webhook(drop_pending_updates=False)
  await dp.start_polling(bot_instance,allowed_updates=dp.resolve_used_update_types())
 except asyncio.CancelledError: raise
 except Exception: log.exception('Telegram polling crashed')
 finally:
  if bot_instance:
   await bot_instance.session.close(); bot_instance=None

@asynccontextmanager
async def lifespan(app):
 global bot_task
 init_db()
 if BOT_TOKEN: bot_task=asyncio.create_task(run_bot())
 else: log.error('BOT_TOKEN missing: bot disabled')
 yield
 if bot_task:
  bot_task.cancel()
  try: await bot_task
  except asyncio.CancelledError: pass
app=FastAPI(title='SellStars',version='2.0.0',lifespan=lifespan)
@app.get('/')
async def home():return FileResponse(ROOT/'index.html')
@app.get('/style.css')
async def style():return FileResponse(ROOT/'style.css',media_type='text/css')
@app.get('/app.js')
async def js():return FileResponse(ROOT/'app.js',media_type='application/javascript')
@app.get('/api/health')
async def health():return {'status':'ok','bot_token_configured':bool(BOT_TOKEN),'bot_task_running':bool(bot_task and not bot_task.done()),'payment':'Telegram Stars XTR','delivery_provider_configured':bool(settings().get('fragment_api_key'))}
@app.get('/api/catalog')
async def catalog():return {'minimum_stars':MIN_STARS,'maximum_stars':MAX_STARS,'xtr_per_100_stars':XTR_PER_100_STARS,'currency':'XTR'}
class OrderIn(BaseModel):
 recipient_username:str=Field(min_length=3,max_length=32,pattern=r'^[A-Za-z][A-Za-z0-9_]{2,31}$')
 stars:int=Field(ge=MIN_STARS,le=MAX_STARS)
@app.post('/api/orders')
async def create_order(payload:OrderIn,user=Depends(telegram_user)):
 if not bot_instance: raise HTTPException(503,detail='Telegram-бот ещё не подключён; проверьте логи')
 recipient=payload.recipient_username.strip().lstrip('@')
 total=max(1,(payload.stars*XTR_PER_100_STARS+99)//100)
 with db() as c:
  cur=c.execute('INSERT INTO orders(telegram_user_id,telegram_username,recipient_username,stars,total_price,currency,status,invoice_payload) VALUES(?,?,?,?,?,?,?,?)',(str(user['id']),user.get('username',''),recipient,str(payload.stars),str(total),'XTR','pending_payment',None))
  oid=cur.lastrowid; c.execute('UPDATE orders SET invoice_payload=? WHERE id=?',(str(oid),oid))
 try:
  from aiogram.types import LabeledPrice
  link=await bot_instance.create_invoice_link(title=f'{payload.stars} Telegram Stars',description=f'Доставка {payload.stars} Stars пользователю @{recipient}',payload=str(oid),provider_token='',currency='XTR',prices=[LabeledPrice(label=f'{payload.stars} Stars',amount=total)])
  return {'order_id':oid,'stars':payload.stars,'total_price':total,'currency':'XTR','status':'pending_payment','invoice_url':link,'message':'Оплатите счёт Telegram Stars. Доставка начнётся только после подтверждённого платежа.'}
 except Exception as e:
  set_status(oid,'invoice_error',error=str(e)[:300]); raise HTTPException(502,detail='Не удалось создать счёт Telegram. Проверьте настройки бота и повторите попытку.') from e
@app.get('/api/orders')
async def my_orders(user=Depends(telegram_user)):
 with db() as c: rows=c.execute('SELECT id,stars,recipient_username,total_price,currency,status,created_at FROM orders WHERE telegram_user_id=? ORDER BY id DESC LIMIT 50',(str(user['id']),)).fetchall()
 return [dict(id=r['id'],stars=r['stars'],recipient=r['recipient_username'],total=r['total_price'],currency=r['currency'],status=r['status'],created_at=r['created_at']) for r in rows]
@app.get('/api/admin/overview')
async def admin_overview(user=Depends(require_admin)):
 with db() as c: row=c.execute("SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN status IN ('paid','delivery_pending','completed','delivery_failed') THEN CAST(total_price AS REAL) ELSE 0 END),0) gross FROM orders").fetchone()
 return {'admin':user.get('username'),'orders':row['n'],'gross_xtr':row['gross'],'xtr_per_100_stars':XTR_PER_100_STARS,'minimum_stars':MIN_STARS}
@app.get('/api/admin/settings')
async def admin_settings(user=Depends(require_admin)):
 v=settings(); return {'fragment_api_url':v.get('fragment_api_url','https://v1.fragmentapi.com/api/v1/partner'),'fragment_api_key_configured':bool(v.get('fragment_api_key')),'fragment_wallet_type':v.get('fragment_wallet_type','TON')}
class SettingsIn(BaseModel): fragment_api_url:str='https://v1.fragmentapi.com/api/v1/partner'; fragment_api_key:str=''; fragment_wallet_type:str='TON'
@app.put('/api/admin/settings')
async def update_settings(p:SettingsIn,user=Depends(require_admin)):
 if p.fragment_wallet_type not in ('TON','USDT'): raise HTTPException(422,detail='Wallet type должен быть TON или USDT')
 url=p.fragment_api_url.strip().rstrip('/')
 if not url.startswith('https://'): raise HTTPException(422,detail='API URL должен использовать HTTPS')
 vals={'fragment_api_url':url,'fragment_wallet_type':p.fragment_wallet_type}
 if p.fragment_api_key.strip(): vals['fragment_api_key']=encrypt_secret(p.fragment_api_key.strip())
 with db() as c:
  for k,v in vals.items():c.execute('INSERT INTO settings(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP',(k,v))
 return {'ok':True,'message':'Настройки сохранены. API-ключ не показывается повторно.'}
@app.get('/api/admin/orders')
async def admin_orders(user=Depends(require_admin)):
 with db() as c: rows=c.execute('SELECT id,telegram_username,telegram_user_id,recipient_username,stars,total_price,currency,status,provider_order_id,provider_status,error,created_at FROM orders ORDER BY id DESC LIMIT 100').fetchall()
 return [dict(id=r['id'],user=r['telegram_username'] or r['telegram_user_id'],recipient=r['recipient_username'],stars=r['stars'],total=r['total_price'],currency=r['currency'],status=r['status'],provider_order_id=r['provider_order_id'],provider_status=r['provider_status'],error=r['error'],created_at=r['created_at']) for r in rows]
@app.post('/api/admin/orders/{order_id}/retry-delivery')
async def retry_delivery(order_id:int,user=Depends(require_admin)):
 with db() as c: row=c.execute('SELECT status FROM orders WHERE id=?',(order_id,)).fetchone()
 if not row or row['status'] not in ('delivery_failed','delivery_pending'): raise HTTPException(409,detail='Заказ нельзя повторить в текущем статусе')
 # Avoid creating a second provider order if one already exists; admin must inspect it first.
 with db() as c: row=c.execute('SELECT provider_order_id FROM orders WHERE id=?',(order_id,)).fetchone()
 if row['provider_order_id']: raise HTTPException(409,detail='У заказа уже есть ID поставщика. Сначала проверьте статус в кабинете поставщика.')
 set_status(order_id,'paid',error=''); asyncio.create_task(deliver_order(order_id)); return {'ok':True,'message':'Повторная доставка запущена'}
