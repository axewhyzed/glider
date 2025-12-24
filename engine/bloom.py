"""
Pure Python Bloom Filter Implementation (Persistable)

Replaces pybloom-live to eliminate C-extension dependency.
Provides identical interface for drop-in compatibility.
"""

import hashlib
import math
import os
from pathlib import Path
from typing import Any
from loguru import logger

class BloomFilter:
    """
    Pure Python Bloom filter with configurable capacity and error rate.
    Supports persistence to disk.
    """
    
    def __init__(self, capacity: int = 100000, error_rate: float = 0.001):
        self.capacity = capacity
        self.error_rate = error_rate
        
        # Calculate optimal bit array size and hash function count
        self.bit_size = self._optimal_bit_size(capacity, error_rate)
        self.hash_count = self._optimal_hash_count(self.bit_size, capacity)
        
        # Bit array stored as bytearray for memory efficiency
        self.bit_array = bytearray(math.ceil(self.bit_size / 8))
        self.item_count = 0
    
    @staticmethod
    def _optimal_bit_size(n: int, p: float) -> int:
        m = -(n * math.log(p)) / (math.log(2) ** 2)
        return int(math.ceil(m))
    
    @staticmethod
    def _optimal_hash_count(m: int, n: int) -> int:
        k = (m / n) * math.log(2)
        return int(math.ceil(k))
    
    def _hash(self, item: str, seed: int) -> int:
        hash_input = f"{item}:{seed}".encode('utf-8')
        hash_digest = hashlib.sha256(hash_input).digest()
        hash_int = int.from_bytes(hash_digest[:8], byteorder='big')
        return hash_int % self.bit_size
    
    def add(self, item: Any):
        item_str = str(item)
        for i in range(self.hash_count):
            index = self._hash(item_str, i)
            byte_index = index // 8
            bit_offset = index % 8
            self.bit_array[byte_index] |= (1 << bit_offset)
        self.item_count += 1
    
    def __contains__(self, item: Any) -> bool:
        item_str = str(item)
        for i in range(self.hash_count):
            index = self._hash(item_str, i)
            byte_index = index // 8
            bit_offset = index % 8
            if not (self.bit_array[byte_index] & (1 << bit_offset)):
                return False
        return True
    
    def save(self, path: Path):
        """Persist bit array to disk."""
        try:
            with open(path, 'wb') as f:
                f.write(self.bit_array)
        except Exception as e:
            logger.warning(f"Failed to save bloom filter: {e}")
            
    def load(self, path: Path):
        """Load bit array from disk if size matches."""
        if not path.exists():
            return
        
        try:
            file_size = os.path.getsize(path)
            if file_size != len(self.bit_array):
                logger.warning(f"⚠️ Bloom Filter size mismatch. Expected {len(self.bit_array)}, got {file_size}. Starting fresh.")
                return
                
            with open(path, 'rb') as f:
                self.bit_array = bytearray(f.read())
                logger.info(f"🌸 Loaded Bloom Filter ({len(self.bit_array)} bytes)")
        except Exception as e:
            logger.error(f"Failed to load bloom filter: {e}")