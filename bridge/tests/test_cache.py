from concurrent.futures import ThreadPoolExecutor

from hq_ocr_bridge.cache import TTLCache


def test_cache_handles_concurrent_reads_and_writes():
    cache = TTLCache(capacity=32, ttl_seconds=60)

    def access_cache(worker: int) -> None:
        for index in range(100):
            key = (worker + index) % 16
            cache.set(key, index)
            cache.get(key)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(access_cache, range(8)))

    assert cache.get(0) is not None
