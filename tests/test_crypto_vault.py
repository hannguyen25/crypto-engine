import logging
import pytest
from cryptography.exceptions import InvalidTag
from app.core.crypto_vault import vault


# TC-SEC-01: Tính toàn vẹn mã hóa/giải mã
def test_tc_sec_01_roundtrip_integrity():
    binance_secret = "vL3k9xZaTestSecretKeyCryptoIntentEngine2026"
    
    # Chu trình Encrypt -> Decrypt
    ciphertext = vault.encrypt(binance_secret)
    decrypted = vault.decrypt(ciphertext)
    
    # Chuỗi trả về trùng khớp 100% với plaintext ban đầu
    assert decrypted == binance_secret


# TC-SEC-02: Tính ngẫu nhiên của IV/Nonce
def test_tc_sec_02_nonce_randomness():
    secret = "vL3k9xZaSameSecretKeyTwice"
    
    # Mã hóa cùng 1 secret 2 lần liên tiếp
    ciphertext_1 = vault.encrypt(secret)
    ciphertext_2 = vault.encrypt(secret)
    
    # Hai ciphertext (bytea) phải hoàn toàn khác biệt nhau
    assert ciphertext_1 != ciphertext_2
    
    # 12 bytes đầu chính là Nonce/IV, bắt buộc phải khác nhau
    nonce_1 = ciphertext_1[:12]
    nonce_2 = ciphertext_2[:12]
    assert nonce_1 != nonce_2


# TC-SEC-03: Chống giả mạo dữ liệu (Tamper Resistance)
def test_tc_sec_03_tamper_resistance():
    secret = "vL3k9xZaTamperTestSecret"
    ciphertext = bytearray(vault.encrypt(secret))
    
    # Thay đổi ngẫu nhiên 1 byte trong ciphertext (hoặc tag phía sau)
    ciphertext[-1] ^= 0xFF
    
    # Hàm decrypt phải quăng ngoại lệ InvalidTag (hoặc Exception kiểm tra Tag thất bại)
    with pytest.raises((InvalidTag, Exception)):
        vault.decrypt(bytes(ciphertext))


# TC-SEC-04: Cấm log khóa bí mật (Zero Plaintext Leakage)
def test_tc_sec_04_no_secret_in_logs(caplog):
    secret_key = "vL3kSuperSecretKeyShouldNeverAppearInLogs9xZa"
    
    # Kích hoạt bắt logger ở mức DEBUG
    with caplog.at_level(logging.DEBUG):
        # Thực hiện các thao tác với vault
        ciphertext = vault.encrypt(secret_key)
        _ = vault.decrypt(ciphertext)
    
    # Kiểm tra log output tuyệt đối không chứa plaintext API key/secret
    captured_logs = caplog.text
    assert secret_key not in captured_logs, "CẢNH BÁO BẢO MẬT: Phát hiện API secret bị ghi vào log!"