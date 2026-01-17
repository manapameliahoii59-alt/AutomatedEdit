from typing import Callable, Dict
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentWindow, NavigationItemPosition

class NavigationService:
    def __init__(self):
        self._routes: Dict[str, Callable[[], QWidget]] = {}
        self._items = {}
        self._window: FluentWindow = None
        self._created_views = {}

    def set_window(self, window: FluentWindow):
        self._window = window

    def register_route(self, route_key: str, factory: Callable[[], QWidget]):
        """Register a route with a factory function for lazy loading."""
        self._routes[route_key] = factory

    def add_navigation_item(self, route_key: str, icon, text: str, position=NavigationItemPosition.TOP):
        """Add item to navigation bar. View will be created only when clicked."""
        if not self._window:
            raise RuntimeError("NavigationService: Window not set")
            
        # We need a placeholder widget or we intercept the click.
        # FluentWindow addSubInterface requires a widget. 
        # Strategy: Create the widget immediately? No, that defeats lazy loading.
        # Strategy: Create a placeholder widget or use custom logic.
        # FluentWidgets API `addSubInterface` adds the widget to QStackedWidget.
        # If we want true lazy loading, we might need to use `addSubInterface` with a dummy,
        # then swap it, OR, check if QFluentWidgets supports lazy loading.
        # QFluentWidgets doesn't support lazy loading out of the box easily without instantiation.
        # However, we can use a "Proxy" widget that initializes the real content on showEvent.
        
        # Simpler approach for this refactor:
        # Just register the route. The MainWindow will handle the lazy creation logic 
        # by connecting to the navigation changed signal, OR we use a ProxyWidget.
        pass

class LazyViewProxy(QWidget):
    """A proxy widget that loads the real view content only when shown."""
    def __init__(self, factory: Callable[[], QWidget], object_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self._factory = factory
        self._real_view = None
        self._loaded = False
        
        # Layout to hold the real view
        from PySide6.QtWidgets import QVBoxLayout
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0,0,0,0)

    def showEvent(self, event):
        if not self._loaded:
            self._real_view = self._factory()
            self._layout.addWidget(self._real_view)
            self._loaded = True
        super().showEvent(event)
        
    def __getattr__(self, name):
        # Forward attribute access to real view if possible (tricky with inheritance)
        if self._real_view:
            return getattr(self._real_view, name)
        raise AttributeError(f"'LazyViewProxy' object has no attribute '{name}'")
