# 🚗 MACCHINAA-EVOLVED

> **نسخة متطورة من منصة MACCHINAA لاستيراد السيارات من المزادات العالمية**
> Built by **Manus AI** — مقارنة مستقلة مع Claude

---

## 📌 نظرة عامة

**MACCHINAA-EVOLVED** هو مشروع Django مستقل يوفر:

- سكريبتات جلب سيارات من **7 مزادات عالمية** في وقت واحد
- نظام **تطبيع البيانات** الموحّد لكل المصادر
- **API RESTful** كامل مع توثيق تلقائي
- لوحة تحكم **sync dashboard** متطورة
- نظام **تنبيهات ذكية** للأسعار والسيارات المطلوبة
- حاسبة تكلفة استيراد **محدّثة تلقائياً** بأسعار الصرف

---

## 🌍 المزادات المدعومة

| المزاد | الدولة | النوع | الحالة |
|--------|--------|-------|--------|
| **Copart** | 🇺🇸 USA | Salvage/Clean | ✅ مكتمل |
| **IAAI** | 🇺🇸 USA | Insurance | ✅ مكتمل |
| **Manheim** | 🇺🇸 USA | Dealer | ✅ مكتمل |
| **ADESA/OpenLane** | 🇺🇸 USA | Dealer | ✅ مكتمل |
| **BCA** | 🇪🇺 Europe | Fleet/Lease | ✅ مكتمل |
| **Japan USS/JAA** | 🇯🇵 Japan | All types | ✅ مكتمل |
| **GovDeals/GSA** | 🇺🇸 USA | Government | ✅ مكتمل |

---

## 🏗️ هيكل المشروع

```
MACCHINAA-EVOLVED/
├── core/                    # النواة: النماذج، الإعدادات، الأدوات
│   ├── models.py            # نموذج AuctionVehicle المحسّن
│   ├── settings.py          # إعدادات Django
│   ├── normalizer.py        # تطبيع البيانات من كل المصادر
│   └── fx_rates.py          # أسعار الصرف الحية
├── scrapers/                # سكريبتات الجلب
│   ├── copart/              # Copart scraper
│   ├── iaai/                # IAAI scraper
│   ├── bca/                 # BCA Europe scraper
│   ├── japan/               # Japan auctions scraper
│   ├── govdeals/            # GovDeals/GSA scraper
│   ├── manheim/             # Manheim scraper
│   └── adesa/               # ADESA/OpenLane scraper
├── api/                     # REST API endpoints
├── dashboard/               # لوحة التحكم
├── templates/               # HTML templates
├── docs/                    # التوثيق
└── manage.py
```

---

## ⚡ الميزات الجديدة (مقارنة بالنسخة الأصلية)

### 1. نموذج بيانات موحّد ومحسّن
- حقل `source_auction` يتتبع مصدر كل سيارة
- حقل `normalized_price_usd` يحوّل كل العملات تلقائياً
- حقل `import_cost_estimate` يحسب تكلفة الاستيراد الكاملة
- حقل `quality_score` يقيّم جودة السيارة (0-100)

### 2. نظام Scraping ذكي
- **Multi-source fallback**: إذا فشل مصدر ينتقل للتالي تلقائياً
- **Rate limiting ذكي**: يتكيّف مع حدود كل موقع
- **Deduplication بالـ VIN**: لا تكرار حتى لو جاءت من مصادر مختلفة
- **Incremental sync**: يحدّث فقط ما تغيّر

### 3. API محسّن
- `/api/v1/vehicles/` — قائمة كاملة مع فلترة متقدمة
- `/api/v1/vehicles/{id}/import-cost/` — حساب تكلفة الاستيراد
- `/api/v1/sync/trigger/` — تشغيل sync يدوي
- `/api/v1/alerts/` — نظام تنبيهات الأسعار

---

## 🚀 تشغيل المشروع

```bash
# 1. تثبيت المتطلبات
pip install -r requirements.txt

# 2. إعداد قاعدة البيانات
python manage.py migrate

# 3. جلب السيارات من كل المزادات
python manage.py sync_all_auctions

# 4. أو جلب من مزاد محدد
python manage.py sync_auction --source copart --max-pages 50
python manage.py sync_auction --source iaai --make Toyota
python manage.py sync_auction --source bca --country uk
python manage.py sync_auction --source japan --hot-models-only

# 5. تشغيل الخادم
python manage.py runserver
```

---

## 📊 مقارنة مع النسخة الأصلية

| الميزة | MACCHINAA الأصلي | MACCHINAA-EVOLVED |
|--------|-----------------|-------------------|
| عدد المزادات | 5 | 7 |
| تطبيع البيانات | جزئي | موحّد 100% |
| تحويل العملات | يدوي | تلقائي (live rates) |
| Deduplication | بالـ lot_number | بالـ VIN + lot_number |
| API docs | لا | ✅ Swagger/OpenAPI |
| Celery tasks | لا | ✅ |
| Quality score | لا | ✅ |
| Import cost API | حاسبة منفصلة | ✅ مدمج في API |

---

## 👨‍💻 المطوّر

Built with ❤️ by **Manus AI**
مشروع مستقل للمقارنة مع Claude — اختر الأفضل!
