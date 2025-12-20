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
    
    # FIX: Assert not None to satisfy Pylance "Optional" check
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
    
    # FIX: Assert not None to satisfy Pylance
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