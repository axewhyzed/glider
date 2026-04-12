import pytest
from pydantic import ValidationError
from engine.schemas import ScraperConfig, Interaction, InteractionType

def test_valid_config_defaults():
    """Test minimal config fills v2.5 defaults correctly."""
    config_data = {
        "name": "Minimal",
        "base_url": "http://example.com",
        "fields": []
    }
    config = ScraperConfig(**config_data)
    assert config.concurrency == 2
    assert config.proxies is None
    assert config.interactions == []
    assert config.use_checkpointing is False
    assert config.respect_robots_txt is False

def test_proxies_list_validation():
    """Ensure proxies are accepted as a list of strings."""
    config_data = {
        "name": "ProxyTest",
        "base_url": "http://example.com",
        "proxies": [
            "http://user:pass@1.2.3.4:8080",
            "socks5://127.0.0.1:9050"
        ],
        "fields": []
    }
    config = ScraperConfig(**config_data)
    
    assert config.proxies is not None
    assert len(config.proxies) == 2
    assert "socks5" in config.proxies[1]

def test_interactions_schema():
    """Test the new Browser Interactions schema (Click, Fill, Wait)."""
    config_data = {
        "name": "InteractionTest",
        "base_url": "http://example.com",
        "use_playwright": True,
        "interactions": [
            {"type": "fill", "selector": "#search", "value": "test query"},
            {"type": "click", "selector": "button.submit"},
            {"type": "wait", "duration": 5000},
            {"type": "scroll"}
        ],
        "fields": []
    }
    config = ScraperConfig(**config_data)
    
    assert config.interactions is not None
    assert len(config.interactions) == 4
    assert config.interactions[0].type == InteractionType.FILL
    assert config.interactions[0].value == "test query"
    assert config.interactions[2].duration == 5000

def test_invalid_interaction_type():
    """Ensure invalid interaction types raise validation errors."""
    config_data = {
        "name": "BadInteraction",
        "base_url": "http://example.com",
        "interactions": [
            {"type": "dance", "selector": "#floor"}  # Invalid type
        ],
        "fields": []
    }
    with pytest.raises(ValidationError):
        ScraperConfig(**config_data)

def test_pagination_mode_requires_base_url():
    """Pagination mode without base_url should raise a validation error."""
    with pytest.raises(ValidationError):
        ScraperConfig(**{
            "name": "NoBASE",
            "mode": "pagination",
            "fields": []
        })

def test_list_mode_requires_start_urls():
    """List mode without start_urls should raise a validation error."""
    with pytest.raises(ValidationError):
        ScraperConfig(**{
            "name": "NoURLs",
            "mode": "list",
            "start_urls": [],
            "fields": []
        })

def test_list_mode_valid():
    """List mode with start_urls should be valid."""
    config = ScraperConfig(**{
        "name": "ListMode",
        "mode": "list",
        "start_urls": ["http://example.com/page1"],
        "fields": []
    })
    assert config.mode.value == "list"

def test_float_delays():
    """min_delay and max_delay should accept float values."""
    config = ScraperConfig(**{
        "name": "FloatDelays",
        "base_url": "http://example.com",
        "min_delay": 0.5,
        "max_delay": 1.5,
        "fields": []
    })
    assert config.min_delay == 0.5
    assert config.max_delay == 1.5