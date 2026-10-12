\"\"\"Fragment adapter placeholder.

This module deliberately does not automate undocumented internal endpoints or pretend
that an order was fulfilled. Implement only after verifying the provider's API access,
terms, authentication, recipient format, and transaction status semantics.
\"\"\"

class FragmentAdapter:
    async def quote(self, *, recipient_username: str, stars: int) -> dict:
        raise NotImplementedError("A verified provider API contract is required")

    async def purchase(self, *, recipient_username: str, stars: int, idempotency_key: str) -> dict:
        raise NotImplementedError("Purchasing is disabled until a verified, permitted API is configured")

    async def check_status(self, *, provider_reference: str) -> dict:
        raise NotImplementedError("A verified provider API contract is required")
