# 🎮 Apex Çeviri – Gerçek Zamanlı Türkçe→İngilizce Ses Çevirisi

Apex Legends oynarken Türkçe konuşmanızı gerçek zamanlı olarak İngilizceye çevirip takım arkadaşlarınıza sanal mikrofon üzerinden ileten uygulama.

## 📋 Gereksinimler

1. **Python 3.10+** – [python.org](https://python.org) 
2. **VB-Audio Virtual Cable** – [İndir (ücretsiz)](https://vb-audio.com/Cable/)
   - ZIP'i aç, `VBCABLE_Setup_x64.exe`'yi **Yönetici olarak** çalıştır
   - Bilgisayarı yeniden başlat
3. **OpenAI API Key** – [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

## 🚀 Kurulum

```bash
# 1. Bağımlılıkları kur
pip install -r requirements.txt

# 2. Sunucuyu başlat (Yönetici olarak önerilir - global tuş için)
python server.py

# 3. Tarayıcıda aç
# http://localhost:8765
```

## 🎮 Kullanım

1. **Web arayüzünde:**
   - OpenAI API Key'ini gir
   - Giriş mikrofonu olarak gerçek mikrofonunu seç
   - Çıkış cihazı olarak **CABLE Input** seç
   - **Bağlan** butonuna tıkla

2. **Apex Legends'ta:**
   - Ses ayarlarına git
   - Mikrofon olarak **CABLE Output** seç
   - Ses modunu **Open Mic** yap

3. **Oyna:**
   - **T tuşuna** basılı tut ve Türkçe konuş
   - Bıraktığında çevrilmiş İngilizce ses oyuna akar
   - Takım arkadaşların İngilizce duyar!

## ⌨️ Push-to-Talk

| Yöntem | Açıklama |
|--------|----------|
| **T tuşu** (global) | Oyun açıkken bile çalışır |
| **Web butonu** | Tarayıcı açıkken mouse ile basılı tut |

## 💰 Maliyet

- **$0.034 / dakika** (sadece konuştuğun süre)
- 1 saat oyun (~15-20 dk konuşma) ≈ $0.50-0.70
- Canlı maliyet göstergesi arayüzde görünür

## ❓ Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| T tuşu çalışmıyor | Scripti **Yönetici olarak** çalıştır |
| CABLE Input görünmüyor | VB-Cable'ı yeniden kur, PC'yi yeniden başlat |
| API bağlantı hatası | API key'ini kontrol et, bakiyeni kontrol et |
| Ses çok sessiz/yüksek | Windows Ses Ayarları → CABLE → Seviye ayarla |
