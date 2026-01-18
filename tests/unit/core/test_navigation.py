import pytest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QWidget
from app.core.navigation import LazyViewProxy, NavigationService

class TestLazyViewProxy:
    def test_lazy_loading(self, qtbot):
        """Test that view is created only when shown"""
        factory = MagicMock(return_value=QWidget())
        proxy = LazyViewProxy(factory, "proxy")
        
        # Not shown yet
        assert not proxy._loaded
        factory.assert_not_called()
        
        # Show
        proxy.show()
        # showEvent is triggered by Qt event loop
        # We can simulate it or wait
        # Or manually call showEvent if we don't want to rely on window system
        proxy.showEvent(None)
        
        assert proxy._loaded
        factory.assert_called_once()
        assert proxy._real_view is not None

class TestNavigationService:
    def test_register_route(self):
        """Test route registration"""
        service = NavigationService()
        factory = lambda: None
        service.register_route("home", factory)
        assert service._routes["home"] is factory
