import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.core.config import settings


class CryptoVault:
    def __init__(self, master_key: bytes | None = None):
        # Master key bắt buộc phải là 32 bytes (256-bit)
        if master_key is None:
            # Fallback lấy từ settings hoặc biến môi trường
            raw_secret = getattr(settings, "VAULT_SECRET_KEY", "0" * 32)
            self.key = raw_secret.encode()[:32].ljust(32, b"0")
        else:
            self.key = master_key
        self.aesgcm = AESGCM(self.key)

    def encrypt(self, plaintext: str) -> bytes:
        """Mã hóa chuỗi string thành bytes dùng AES-256-GCM."""
        nonce = os.urandom(12)  # Nonce 96-bit chuẩn cho AES-GCM
        ciphertext = self.aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return nonce + ciphertext  # Gộp nonce vào đầu payload

    def decrypt(self, encrypted_payload: bytes) -> str:
        """Giải mã bytes thành plaintext string ban đầu."""
        if len(encrypted_payload) < 28:  # 12 bytes nonce + 16 bytes tag tối thiểu
            raise ValueError("Invalid encrypted payload size")
        
        nonce = encrypted_payload[:12]
        ciphertext = encrypted_payload[12:]
        decrypted_bytes = self.aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted_bytes.decode("utf-8")


vault = CryptoVault()
# Giữ nguyên toàn bộ code class CryptoVault phía trên của bạn
vault = CryptoVault()

# Thêm 2 hàm này ở cuối file:
encrypt_secret = vault.encrypt
decrypt_secret = vault.decrypt