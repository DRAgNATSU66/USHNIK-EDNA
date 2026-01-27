# Mock triton module for Windows compatibility
# DNABERT-2 imports triton but we don't need flash attention - this provides stubs

import sys
from types import ModuleType

# Create fake triton module hierarchy
class FakeTritonLanguage:
    """Fake triton.language module."""
    constexpr = lambda x: x
    
    @staticmethod
    def load(*args, **kwargs):
        pass
    
    @staticmethod
    def store(*args, **kwargs):
        pass
    
    @staticmethod
    def program_id(*args, **kwargs):
        return 0
    
    @staticmethod
    def arange(*args, **kwargs):
        return None


class FakeTriton:
    """Fake triton module."""
    language = FakeTritonLanguage()
    
    @staticmethod
    def jit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    
    @staticmethod
    def cdiv(a, b):
        return (a + b - 1) // b
    
    @staticmethod
    def next_power_of_2(x):
        return 1 << (x - 1).bit_length()


# Register fake triton in sys.modules
sys.modules['triton'] = FakeTriton()
sys.modules['triton.language'] = FakeTritonLanguage()

print("[triton_stub] Fake triton module loaded for Windows compatibility")
