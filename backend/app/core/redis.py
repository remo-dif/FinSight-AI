from redis.asyncio import Redis


def create_redis_client(url: str) -> Redis:
    return Redis.from_url(
        url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )
