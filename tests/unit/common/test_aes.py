import pytest
from app.common.aes import aes_encrypt, aes_decrypt

class TestAES:
    def test_encryption_decryption(self):
        """Test basic encryption and decryption"""
        original_text = "Hello World"
        encrypted = aes_encrypt(original_text)
        decrypted = aes_decrypt(encrypted)
        assert decrypted == original_text
        assert encrypted != original_text

    def test_empty_string(self):
        """Test empty string handling"""
        assert aes_decrypt('') == ''
        # Encrypting empty string should return something (padding)
        assert aes_encrypt('') != ''
        assert aes_decrypt(aes_encrypt('')) == ''

    def test_custom_key_iv(self):
        """Test with custom key and IV"""
        key = "1234567890123456"
        iv = "abcdefghijklmnop"
        text = "Secret Message"
        encrypted = aes_encrypt(text, key=key, iv=iv)
        decrypted = aes_decrypt(encrypted, key=key, iv=iv)
        assert decrypted == text
        
        # Test failure with wrong key
        wrong_decrypted = aes_decrypt(encrypted, key="0000000000000000", iv=iv)
        # Depending on implementation, it might return garbage or empty string or raise error
        # In our implementation it catches exception and returns ''
        assert wrong_decrypted == '' or wrong_decrypted != text

    def test_invalid_input(self):
        """Test invalid input for decryption"""
        assert aes_decrypt("invalid_base64") == ''
