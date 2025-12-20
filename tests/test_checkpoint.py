import pytest
import sqlite3
from pathlib import Path
from engine.checkpoint import CheckpointManager

# Use a temporary directory for DB tests to avoid polluting /data
@pytest.fixture
def temp_checkpoint(tmp_path):
    # Monkeypatch the path in the class instance logic for the test
    # (Or simply init the manager and check the file creation)
    
    # Since CheckpointManager hardcodes "data/checkpoints.db", 
    # for unit testing cleanly, we should mock the path or just cleanup.
    # For this test, we will allow it to create the file but ensure we close it.
    
    manager = CheckpointManager("test_config", enabled=True)
    # Redirect DB path for test safety (optional, but good practice)
    manager.db_path = tmp_path / "test_checkpoints.db"
    manager._init_db() # Re-init with new path
    
    yield manager
    
    manager.close()

def test_checkpoint_disabled_by_default():
    manager = CheckpointManager("test", enabled=False)
    assert manager.is_done("http://example.com") is False
    manager.mark_done("http://example.com")
    assert manager.is_done("http://example.com") is False

def test_mark_and_check_done(temp_checkpoint):
    url = "http://example.com/page1"
    
    # Should be False initially
    assert temp_checkpoint.is_done(url) is False
    
    # Mark done
    temp_checkpoint.mark_done(url)
    
    # Should be True now
    assert temp_checkpoint.is_done(url) is True

def test_persistence(tmp_path):
    """Test that state persists across instances."""
    db_file = tmp_path / "persistent.db"
    url = "http://persist.com"
    
    # Run 1: Save state
    mgr1 = CheckpointManager("persist_test", enabled=True)
    mgr1.db_path = db_file
    mgr1._init_db()
    mgr1.mark_done(url)
    mgr1.close()
    
    # Run 2: Load state
    mgr2 = CheckpointManager("persist_test", enabled=True)
    mgr2.db_path = db_file
    mgr2._init_db()
    
    assert mgr2.is_done(url) is True
    mgr2.close()