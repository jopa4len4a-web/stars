const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();
const initData = tg?.initData || "";
const headers = {"Content-Type":"application/json", "X-Telegram-Init-Data": initData};
const $ = id => document.getElementById(id);
const money = n => new Intl.NumberFormat("ru-RU",{maximumFractionDigits:2}).format(n) + " ₽";
let admin = false;

function amount() {
  let q = Math.max(100, Math.min(100000, Number($("quantity").value) || 100));
  $("quantity").value = q;
  $("total").textContent = money(q * 1.5);
}
$("quantity").addEventListener("input", amount);
$("minus").onclick = () => { $("quantity").value = Math.max(100, Number($("quantity").value || 100)-50); amount(); };
$("plus").onclick = () => { $("quantity").value = Math.min(100000, Number($("quantity").value || 100)+50); amount(); };
amount();

async function api(path, options={}) {
  const response = await fetch(path, { ...options, headers: {...headers, ...(options.headers||{})} });
  const data = await response.json().catch(()=>({detail:"Не удалось прочитать ответ сервера"}));
  if (!response.ok) throw new Error(data.detail || "Ошибка запроса");
  return data;
}
function notice(message, bad=false) {
  const el=$("notice"); el.textContent=message; el.classList.remove("hidden");
  el.style.color=bad?"#ff9a9a":"var(--accent)";
}
function renderOrders(target, orders) {
  const el=$(target);
  if (!orders.length) {el.textContent="Заказов пока нет."; return;}
  el.innerHTML=orders.map(o=>`<div class="order"><div><b>#${o.id} · ${o.stars} Stars</b><small>${o.recipient ? "@"+escapeHtml(o.recipient) : "Получатель: "+escapeHtml(o.user||"")} · ${escapeHtml(o.status)}</small></div><strong>${money(Number(o.total))}</strong></div>`).join("");
}
function escapeHtml(s) { return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }

$("createOrder").onclick = async () => {
  try {
    if (!initData) throw new Error("Откройте Mini App через Telegram, чтобы подтвердить аккаунт.");
    const recipient=$("recipient").value.trim().replace(/^@/,"");
    const stars=Number($("quantity").value);
    const result=await api("/api/orders",{method:"POST",body:JSON.stringify({recipient_username:recipient,stars})});
    notice(`Заказ #${result.order_id} создан. Статус: ${result.status}. ${result.message}`);
    await loadMyOrders();
  } catch(e) { notice(e.message, true); }
};
async function loadMyOrders() {
  if (!initData) { $("myOrders").textContent="Откройте Mini App из Telegram."; return; }
  try { renderOrders("myOrders", await api("/api/orders")); }
  catch(e) { $("myOrders").textContent=e.message; }
}
$("refreshOrders").onclick=loadMyOrders;

async function loadAdmin() {
  if (!initData) return;
  try {
    const overview=await api("/api/admin/overview");
    admin=true; $("adminPanel").classList.add("visible");
    $("ordersCount").textContent=overview.orders;
    $("gross").textContent=money(Number(overview.gross_rub));
    const cfg=await api("/api/admin/settings");
    $("plategaId").value=cfg.platega_merchant_id||"";
    $("fragmentUrl").value=cfg.fragment_api_url||"";
    $("plategaSecret").placeholder=cfg.platega_secret_configured?"Секрет сохранён — пусто, чтобы не менять":"Введите секрет";
    $("fragmentKey").placeholder=cfg.fragment_api_key_configured?"Ключ сохранён — пусто, чтобы не менять":"Введите API key";
    renderOrders("ordersList", await api("/api/admin/orders"));
  } catch(e) { /* non-admin users do not see admin panel */ }
}
$("saveSettings").onclick=async()=>{
  if(!admin) return notice("Нет прав администратора.",true);
  try {
    const result=await api("/api/admin/settings",{method:"PUT",body:JSON.stringify({
      platega_merchant_id:$("plategaId").value,
      platega_secret:$("plategaSecret").value,
      fragment_api_url:$("fragmentUrl").value,
      fragment_api_key:$("fragmentKey").value
    })});
    $("plategaSecret").value=""; $("fragmentKey").value="";
    notice(result.message);
    await loadAdmin();
  } catch(e) { notice(e.message,true); }
};
loadMyOrders();
loadAdmin();
