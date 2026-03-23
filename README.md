# ARTEMIS

ARTEMIS — интерактивная геоисторическая карта на базе MapLibre и GeoJSON.

Проект показывает, **где** и **когда** происходили события, существовали объекты, действовали маршруты, области влияния и биогеографические ареалы.  
Это образовательный веб-проект с возможностью масштабирования в PWA и дальнейшего развития в полноценную платформу.

---

## Назначение

ARTEMIS решает задачу визуального обучения историческим и географическим данным.

Подходит для:

- истории и исторической географии;
- архитектуры и культурного наследия;
- биографий и маршрутов;
- биогеографии видов;
- проектов с временной и пространственной привязкой.

---

## Основные возможности

- интерактивная карта на MapLibre;
- отображение объектов по слоям;
- фильтрация по времени;
- список объектов и popup-карточки;
- GeoJSON как основной формат данных для карты;
- ETL-пайплайн из Airtable в `/data/*.json`;
- поддержка пользовательского контента (UGC) через backend;
- авторизация без `localStorage`;
- PWA-слой для офлайн-доступа.

---

## Текущая архитектура

### Источник данных
- Airtable — основной источник curated-данных;
- ETL экспортирует данные в репозиторий;
- фронтенд не обращается к Airtable напрямую.

### Фронтенд
- Vanilla JavaScript;
- модули:
  - `js/data.js` — загрузка данных;
  - `js/map.js` — инициализация карты и слоёв;
  - `js/ui.js` — фильтры, список, состояние интерфейса;
  - `js/auth.js` — авторизация;
  - `js/ui.ugc.js` — черновики и пользовательский контент;
  - `js/ui.moderation.js` — модерация;
  - `js/pwa.js` — PWA-слой.

### Backend
- FastAPI;
- auth / drafts / moderation / uploads;
- access token хранится в памяти;
- refresh token — в `httpOnly` cookie.

### CI / ETL
- GitHub Actions;
- dry-run экспорт;
- валидация данных;
- публикация `/data/*.json` и `/data/*.geojson`.

---

## Стек

- **Map**: MapLibre GL JS
- **Frontend**: Vanilla JS (ES modules)
- **Backend**: FastAPI
- **Data source**: Airtable
- **Data format**: JSON / GeoJSON
- **Hosting**: GitHub Pages
- **Automation**: GitHub Actions

---

## Принципы проекта

- только GeoJSON для карты;
- без прямых запросов к Airtable из браузера;
- без `localStorage` и `sessionStorage`;
- минимальный и чистый код;
- карта не пересоздаётся при обновлении данных;
- объекты без геометрии видны в списке, но не отображаются на карте;
- UGC и curated-данные разделены.

---

## Структура проекта

```text
.
├── index.html
├── css/
│   └── style.css
├── js/
│   ├── data.js
│   ├── map.js
│   ├── ui.js
│   ├── auth.js
│   ├── ui.ugc.js
│   ├── ui.moderation.js
│   └── pwa.js
├── scripts/
│   └── export_airtable.py
├── data/
│   ├── features.json
│   ├── features.geojson
│   └── layers.json
├── .github/
│   └── workflows/
│       └── export-airtable.yml
├── manifest.json
├── sw.js
└── README.md