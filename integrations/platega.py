\"\"\"Platega adapter placeholder.

Do not mark an order paid based only on a browser redirect. Implement signed webhook
verification and server-to-server status checks according to the current official
Platega documentation before enabling real payments.
\"\"\"

class PlategaAdapter:
    async def create_payment(self, *, order_id: int, amount_rub: str, description: str) -> dict:
        raise NotImplementedError("Platega credentials and current API contract must be verified first")

    async def verify_webhook(self, headers: dict, body: bytes) -> dict:
        raise NotImplementedError("Implement signature verification from official Platega docs")
