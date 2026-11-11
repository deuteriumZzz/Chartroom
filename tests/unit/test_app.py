from httpx import ASGITransport, AsyncClient

from chartroom.main import create_app


async def test_health() -> None:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
