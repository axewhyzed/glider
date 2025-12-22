"""
Pure Python Bloom Filter Implementation

Replaces pybloom-live to eliminate C-extension dependency.
Provides identical interface for drop-in compatibility.
"""

import hashlib
import math
from typing import Any


class BloomFilter:
    """
    Pure Python Bloom filter with configurable capacity and error rate.
    
    Uses multiple hash functions (murmur3-style) for optimal distribution.
    Memory-efficient bit array implementation.
    """
    
    def __init__(self, capacity: int = 100000, error_rate: float = 0.001):
        """
        Initialize Bloom filter.
        
        Args:
            capacity: Expected number of unique items
            error_rate: Acceptable false positive rate (0.001 = 0.1%)
        """
        self.capacity = capacity
        self.error_rate = error_rate
        
        # Calculate optimal bit array size and hash function count
        self.bit_size = self._optimal_bit_size(capacity, error_rate)
        self.hash_count = self._optimal_hash_count(self.bit_size, capacity)
        
        # Bit array stored as bytearray for memory efficiency
        self.bit_array = bytearray(math.ceil(self.bit_size / 8))
        
        # Track actual item count for debugging
        self.item_count = 0
    
    @staticmethod
    def _optimal_bit_size(n: int, p: float) -> int:
        """
        Calculate optimal bit array size.
        Formula: m = -(n * ln(p)) / (ln(2)^2)
        """
        m = -(n * math.log(p)) / (math.log(2) ** 2)
        return int(math.ceil(m))
    
    @staticmethod
    def _optimal_hash_count(m: int, n: int) -> int:
        """
        Calculate optimal number of hash functions.
        Formula: k = (m/n) * ln(2)
        """
        k = (m / n) * math.log(2)
        return int(math.ceil(k))
    
    def _hash(self, item: str, seed: int) -> int:
        """
        Generate hash using SHA256 with seed.
        Returns bit index in range [0, bit_size).
        """
        # Combine item with seed for multiple hash functions
        hash_input = f"{item}:{seed}".encode('utf-8')
        hash_digest = hashlib.sha256(hash_input).digest()
        
        # Convert first 8 bytes to integer
        hash_int = int.from_bytes(hash_digest[:8], byteorder='big')
        
        # Map to bit array size
        return hash_int % self.bit_size
    
    def _set_bit(self, index: int):
        """Set bit at given index to 1."""
        byte_index = index // 8
        bit_offset = index % 8
        self.bit_array[byte_index] |= (1 << bit_offset)
    
    def _get_bit(self, index: int) -> bool:
        """Check if bit at given index is 1."""
        byte_index = index // 8
        bit_offset = index % 8
        return bool(self.bit_array[byte_index] & (1 << bit_offset))
    
    def add(self, item: Any):
        """
        Add item to Bloom filter.
        
        Args:
            item: Item to add (will be converted to string)
        """
        item_str = str(item)
        
        # Set all k hash positions to 1
        for i in range(self.hash_count):
            index = self._hash(item_str, i)
            self._set_bit(index)
        
        self.item_count += 1
    
    def __contains__(self, item: Any) -> bool:
        """
        Check if item might be in the filter.
        
        Args:
            item: Item to check
            
        Returns:
            True if item might be present (with error_rate false positive chance)
            False if item is definitely not present
        """
        item_str = str(item)
        
        # Check all k hash positions
        for i in range(self.hash_count):
            index = self._hash(item_str, i)
            if not self._get_bit(index):
                return False  # Definitely not present
        
        return True  # Probably present
    
    @property
    def count(self) -> int:
        """Return approximate number of items added."""
        return self.item_count
    
    @property
    def memory_usage_kb(self) -> float:
        """Return memory usage in KB."""
        return len(self.bit_array) / 1024
    
    def __repr__(self) -> str:
        return (
            f"BloomFilter(capacity={self.capacity}, "
            f"error_rate={self.error_rate}, "
            f"items={self.item_count}, "
            f"memory={self.memory_usage_kb:.2f}KB)"
        )
