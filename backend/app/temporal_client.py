from temporalio.client import Client

from .config import get_settings

_client: Client | None = None


async def get_temporal_client() -> Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = await Client.connect(
            settings.temporal_host, namespace=settings.temporal_namespace
        )
    return _client
