# ESP32-S3 ADC2 ve WiFi Durumu

Merhabalar,

Az önce bahsettiğim "ESP-NOW ile ADC2 (Pin 14) çakışması" konusunda sizi yanılttım, düzeltmek isterim:

- **Eski ESP32** modellerinde bu sorun vardı ve WiFi açıkken ADC2 kullanılamıyordu.
- Ancak sizin kullandığınız **ESP32-S3** modelinde, donanımsal olarak **Analog Arbiter** (Hakem) birimi eklendi.
- Bu sayede **WiFi (ESP-NOW) açıkken bile Pin 14'ten analog okuma yapılabilir!**

Yani şu anki bağlantınız ve kodunuz **doğrudur** ve **sorunsuz çalışacaktır**. 
Endişelenmenize gerek yok.

İyi çalışmalar! 🚀
