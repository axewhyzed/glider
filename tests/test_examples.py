"""Every checked-in v3.2 example remains schema-valid."""

from pathlib import Path

from engine.validation import validate_config_file


def test_examples_validate_without_network():
    examples_dir = Path(__file__).parents[1] / "examples"
    configs = sorted(examples_dir.glob("*.json"))
    assert configs
    for path in configs:
        result = validate_config_file(path)
        assert result.valid, f"{path.name}: {result.as_dict()}"
