import pytest
import asyncio
from engine.schemas import ScraperConfig
from engine.scraper import ScraperEngine

def test_engine_initialization_with_callbacks():
    # FIX: Use dictionary unpacking to allow Pydantic to coerce string to HttpUrl
    # without Pylance complaining about type mismatch in __init__
    config = ScraperConfig(**{
        "name": "InitTest",
        "base_url": "http://test.com",
        "fields": []
    })
    
    async def mock_output(data):
        pass
        
    def mock_stats(status):
        pass
    
    engine = ScraperEngine(
        config,
        output_callback=mock_output,
        stats_callback=mock_stats
    )
    
    assert engine.output_callback is mock_output
    assert engine.stats_callback is mock_stats
    assert engine.ua_rotator is not None
    assert engine.checkpoint.enabled is False  # Default from config

@pytest.mark.asyncio
async def test_proxy_pool_rotation():
    # FIX: Use dictionary unpacking
    config = ScraperConfig(**{
        "name": "ProxyTest",
        "base_url": "http://test.com",
        "proxies": ["p1", "p2"],
        "fields": []
    })
    
    engine = ScraperEngine(config)
    
    # Check rotation logic
    p1 = engine._get_next_proxy()
    p2 = engine._get_next_proxy()
    p3 = engine._get_next_proxy()
    
    assert p1 == "p1"
    assert p2 == "p2"
    assert p3 == "p1"  # Should cycle back