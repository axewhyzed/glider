import pytest
from engine.schemas import ScraperConfig, DataField, Selector, SelectorType

@pytest.mark.asyncio
async def test_scraper_config_validation():
    """Test that a valid config is accepted."""
    config = ScraperConfig(
        name="Test",
        # Pydantic converts string -> HttpUrl at runtime, but Pylance complains.
        # We silence the type checker here.
        base_url="http://example.com", # type: ignore
        fields=[
            # Fix: Use SelectorType.CSS instead of "css" string
            DataField(name="title", selectors=[Selector(type=SelectorType.CSS, value="h1")])
        ]
    )
    assert config.name == "Test"
    # Note: Pydantic v2 HttpUrl often normalizes URL (adds trailing slash)
    assert str(config.base_url).rstrip("/") == "http://example.com"

@pytest.mark.asyncio
async def test_engine_init():
    """Test engine initialization."""
    # Import locally to avoid circular import issues during test collection
    from engine.scraper import ScraperEngine
    
    config = ScraperConfig(
        name="Test",
        base_url="http://example.com", # type: ignore
        fields=[]
    )
    engine = ScraperEngine(config)
    assert engine.config.name == "Test"
    assert engine.rate_limiter is not None