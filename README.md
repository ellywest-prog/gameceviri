# 🎮 Apex Çeviri – Gerçek Zamanlı Türkçe→İngilizce Ses Çevirisi

Apex Legends oynarken Türkçe konuşmanızı gerçek zamanlı olarak İngilizceye çevirip takım arkadaşlarınıza sanal mikrofon üzerinden ileten masaüstü uygulaması.

---

## 📋 Gereksinimler

1. **Python 3.10+** (Geliştirici/Kod modu için) – [python.org](https://python.org)
2. **VB-Audio Virtual Cable** – [İndir (ücretsiz)](https://vb-audio.com/Cable/)
   - ZIP dosyasını klasöre çıkarın.
   - `VBCABLE_Setup_x64.exe` dosyasına **sağ tıklayıp "Yönetici olarak çalıştır"** deyin.
   - Kurulumdan sonra bilgisayarınızı **yeniden başlatın**.
3. **OpenAI API Key** – [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

---

## 🚀 Hızlı Başlangıç (Klasör Kurulumu)

Uygulamayı indirdiğiniz klasörde şu adımları izleyin:

1. **`start_server.bat`** dosyasına çift tıklayarak uygulamayı başlatın.
   - Sunucu otomatik olarak arka planda çalışmaya başlayacaktır.
   - Varsayılan tarayıcınızda **http://localhost:8765** sayfası otomatik olarak açılacaktır.

---

## 🛠️ Başka Bilgisayara Taşıma (Portatif Kullanım)

Projeyi başka bir bilgisayara (örneğin evdeki bilgisayarınıza) taşırken şu adımları izleyin:

1. **VB-Cable Sürücüsünü Kurun:**
   - Taşımadan önce veya taşıdıktan sonra hedef bilgisayara `VBCABLE_Driver_Pack45.zip` paketini kurun ve bilgisayarı yeniden başlatın.
2. **Gereksinimleri Kurun:**
   - Hedef bilgisayarda Python kurulu olduğundan emin olun. Klasör içindeki CMD'de `pip install -r requirements.txt` komutunu çalıştırarak bağımlılıkları yükleyin.
3. **Çalıştırın:**
   - `start_server.bat` dosyasına tıklayarak sunucuyu ve arayüzü başlatın.

---

## 📦 Tek Tıkla Çalışan EXE Yapma (PyInstaller Bundle)

Uygulamayı Python kurulumuna ihtiyaç duymayan, tek tıkla açılan bağımsız bir `.exe` programı haline getirmek için:

1. Geliştirici terminalinde PyInstaller kütüphanesini yükleyin:
   ```bash
   pip install pyinstaller
   ```
2. Aşağıdaki komutla tüm projeyi tek bir EXE dosyasına paketleyin:
   ```bash
   pyinstaller --name="ApexCeviri" --add-data "static;static" --noconsole --onefile server.py
   ```
3. Paketleme bittiğinde, **`dist/`** klasörü içinde **`ApexCeviri.exe`** oluşacaktır.
4. Bu EXE dosyasını istediğiniz bilgisayara taşıyıp çift tıklayarak çalıştırabilirsiniz! (Arka planda uvicorn çalışacak ve tarayıcı ekranınız otomatik açılacaktır).

---

## 🎮 Kullanım Adımları

1. **Web arayüzünde:**
   - OpenAI API Key'ini girin ve geçerliliğini test etmek için **API Key Test Et** butonuna basın.
   - Giriş mikrofonu olarak **gerçek mikrofonunuzu** seçin.
   - Çıkış cihazı olarak **CABLE Input (VB-Audio Virtual Cable)** seçin.
   - **Bağlan** butonuna tıklayın.

2. **Apex Legends'ta:**
   - Ses ayarlarına gidin.
   - Mikrofon (Voice Input Device) olarak **CABLE Output** seçin.
   - Ses iletim modunu **Open Mic** (Her zaman açık) yapın.
   
3. **Oynayın:**
   - **T tuşuna** basılı tutun ve Türkçe konuşun.
   - Tuşu bıraktığınızda çevrilmiş İngilizce ses anında oyuna aktarılır.
   - Tuşa basmadığınızda sanal mikrofondan hiç ses gitmez (arka plan gürültüsü, nefes sesi vb. tamamen engellenir - bas konuş konforu korunur).

4. **Uygulamayı Kapatma:**
   - İşiniz bittiğinde web arayüzündeki **Uygulamayı Kapat** butonuna tıklamanız yeterlidir. Arka planda çalışan tüm servisler güvenle sonlandırılacaktır.

---

## ⌨️ Kısayol Tuşları (Push-to-Talk)

| Yöntem | Çalışma Alanı | Özellik |
|--------|---------------|---------|
| **T Tuşu** (Hile Koruması Uyumlu) | Oyun içi / Arka plan / Masaüstü | Apex Legends aktifken de algılar. |
| **Web Butonu** | Tarayıcı odağı | Mouse ile basılı tutarak konuşabilirsiniz. |

---

## 💰 Maliyet Bilgisi

- Uygulama sadece siz **T tuşuna basılı tutup konuştuğunuzda** OpenAI Realtime API'sini kullanır. Konuşmadığınız bekleme sürelerinde hiçbir ücret yansımaz.
- Ortalama konuşma maliyeti **dakika başına ~$0.03** seviyesindedir. Canlı maliyet göstergenizi ve toplam harcamanızı ekranın sol alt köşesinden takip edebilirsiniz.
