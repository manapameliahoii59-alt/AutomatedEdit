import pytest
from app.core.container import Container

class ServiceA:
    pass

class ServiceB:
    pass

class TestContainer:
    def setup_method(self):
        # Reset services before each test
        Container._services = {}

    def test_get_creates_singleton(self):
        """Test that get creates and returns a singleton"""
        s1 = Container.get(ServiceA)
        s2 = Container.get(ServiceA)
        
        assert isinstance(s1, ServiceA)
        assert s1 is s2

    def test_register(self):
        """Test manual registration"""
        instance = ServiceB()
        Container.register(ServiceB, instance)
        
        retrieved = Container.get(ServiceB)
        assert retrieved is instance

    def test_different_services(self):
        """Test different services are different instances"""
        s_a = Container.get(ServiceA)
        s_b = Container.get(ServiceB)
        
        assert s_a is not s_b
