from app.data.services.auth_service import AuthService
from app.ui.views.login.view_model import LoginViewModel

class Container:
    """Simple Dependency Injection Container"""
    _services = {}

    @classmethod
    def get(cls, service_type):
        if service_type not in cls._services:
            cls._services[service_type] = service_type()
        return cls._services[service_type]

    @classmethod
    def register(cls, service_type, instance):
        cls._services[service_type] = instance

    # Specific factories for ViewModels to support injection
    @staticmethod
    def auth_service() -> AuthService:
        return Container.get(AuthService)

    @staticmethod
    def login_view_model(parent=None) -> LoginViewModel:
        # ViewModel usually needs to be created fresh or with a parent
        # But here we inject services into it.
        # Since LoginViewModel currently instantiates AuthService internally, 
        # we will refactor it later to accept it.
        # For now, let's just return the class or instance.
        # In MVVM, ViewModels are typically not singletons per app, but per View.
        vm = LoginViewModel(parent)
        vm.auth_service = Container.auth_service()
        return vm
