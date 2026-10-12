# SellStars — Telegram Mini App starter

Стартовый проект магазина с Telegram-ботом, Mini App, админ-панелью, FastAPI и PostgreSQL.

## Важно
- Администратор задаётся username `ownerparadoxy`.
- Mini App: `https://sellstarsss.bothost.tech` (порт контейнера/хоста `3000`).
- Цена по умолчанию: 1.50 RUB за звезду, минимальный заказ — 100.
- Platega и Fragment пока подключены как **заглушки адаптеров**: проект не имитирует успешные платежи/покупки. Реальные методы нужно добавить после проверки актуальной документации и условий поставщиков.
- Не вставляйте ключи в чат или Git. Введите их через админ-панель; они шифруются Fernet-ключом `MASTER_KEY`.
- Для публичного запуска нужен HTTPS на домене. Если хостинг уже предоставляет reverse proxy, направьте его на порт 3000.

## Запуск
1. Скопируйте `.env.example` в `.env`.
2. Задайте `BOT_TOKEN`, `MASTER_KEY`, `POSTGRES_PASSWORD`, `ADMIN_SESSION_SECRET`.
3. Сгенерировать ключ Fernet можно командой:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
4. Запустите: `docker compose up -d --build`
5. Откройте `http://localhost:3000` локально или домен после настройки HTTPS.
6. В Telegram укажите домен Mini App в настройках бота через BotFather.

## Первичная настройка
- `BOT_TOKEN` нужен для бота и проверки Telegram Mini App initData.
- Первый администратор — Telegram username `ownerparadoxy`. Username сам по себе не является аутентификацией: панель принимает только валидные подписанные Telegram initData с нужным username.
- В настройках Mini App можно добавить ключи Platega/Fragment. Секреты не возвращаются клиенту после сохранения.

## Состав
- `backend/`: FastAPI, Telegram initData validation, настройки и заказы.
- `bot/`: бот на aiogram с кнопкой открытия Mini App.
- `frontend/`: Mini App и административные настройки.
- `nginx/`: статика и проксирование `/api/`.
- `integrations/`: адаптеры-плейсхолдеры.

Перед реальной продажей настройте условия возвратов, поддержку, юридические требования, мониторинг и проверку поставщика/платежей.
