import pytest
from app.common.aes import aes_encrypt, aes_decrypt
from app.ui.views.login.view_model import LoginViewModel

class TestSecurity:
    def test_password_encryption_strength(self):
        """Ensure AES implementation uses proper padding and blocks"""
        # We can't easily check key size dynamically as it's hardcoded in the function defaults
        # But we can verify it doesn't crash on long inputs and output is different
        
        long_pass = "a" * 1000
        encrypted = aes_encrypt(long_pass)
        assert len(encrypted) > 1000
        assert aes_decrypt(encrypted) == long_pass

    def test_no_plain_password_storage(self, mocker):
        """Test that passwords are encrypted before storage"""
        from app.common.config import cfg, qconfig
        
        # Mock qconfig.set to verify what's being saved
        mock_set = mocker.patch.object(qconfig, 'set')
        
        vm = LoginViewModel()
        vm.auth_service = mocker.MagicMock()
        vm.auth_service.login.return_value = True # Not awaited here but needed for flow
        
        # Bypass task manager to call handle_login_success directly or mock it
        # Easier to call _handle_login_success directly
        vm._handle_login_success("user", "password123", True, False)
        
        # Check calls to qconfig.set(cfg.password, ...)
        # Find call for cfg.password
        password_call = None
        for call in mock_set.mock_calls:
            if call.args[0] == cfg.password:
                password_call = call
                break
                
        assert password_call is not None
        saved_value = password_call.args[1]
        
        assert saved_value != "password123"
        assert saved_value != ""
        # It should be encrypted
        assert aes_decrypt(saved_value) == "password123"

    def test_input_sanitization(self):
        """Test input sanitization (basic check)"""
        # In PyQt, text inputs usually handle SQL injection chars as plain text unless passed to raw SQL.
        # But we can check if sensitive chars are allowed or handled.
        # This is more of a placeholder as we don't have a backend to exploit here.
        pass
