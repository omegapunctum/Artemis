## Canonical backend entrypoint
app/  (не api/)

---

## UI / UX Manual Smoke Checks

### 1. Map & Core Navigation
- [ ] Карта загружается без ошибок
- [ ] Объекты отображаются из /data/features.geojson
- [ ] Клик по объекту открывает detail panel
- [ ] Карта не пересоздаётся при фильтрации

### 2. Search
- [ ] Поиск по name_ru / name_en / tags работает
- [ ] Dropdown показывает результаты
- [ ] Клик по результату центрирует карту
- [ ] Empty state отображается корректно

### 3. Timeline & Ribbon
- [ ] Timeline фильтрует объекты по дате
- [ ] Ribbon обновляется синхронно
- [ ] Клик по карточке → центр карты + detail panel
- [ ] Нет конфликтов при смене диапазона

### 4. Detail Panel
- [ ] Открывается из карты / ribbon / search
- [ ] Показывает title, date, description, source
- [ ] Related объекты работают
- [ ] Закрывается по Esc и кнопке
- [ ] Не выходит за viewport

### 5. Filters / Layers / Panels
- [ ] Filters panel открывается/закрывается корректно
- [ ] Layers toggle работает
- [ ] Panels не конфликтуют между собой
- [ ] Click-outside закрывает панели

### 6. UGC (Drafts)
- [ ] Create draft panel открывается
- [ ] Save draft работает
- [ ] Submit → pending работает
- [ ] Validation ошибок отображается
- [ ] My drafts список работает

### 7. Moderation
- [ ] Pending queue загружается
- [ ] Review panel отображает данные
- [ ] Approve работает
- [ ] Reject работает
- [ ] Очередь обновляется без reload

### 8. Error / System States
- [ ] Ошибки отображаются inline (без alert)
- [ ] 401 → session expired UI
- [ ] 403 → forbidden UI
- [ ] Retry работает
- [ ] Success messages отображаются

### 9. PWA / Offline
- [ ] Install prompt появляется корректно
- [ ] Offline state отображается
- [ ] Online restore отображается
- [ ] Update available работает
- [ ] Cached data используется корректно

### 10. Responsive / Mobile
- [ ] UI работает на mobile viewport
- [ ] Detail panel → bottom sheet
- [ ] Panels не конфликтуют
- [ ] Safe-area учитывается
- [ ] Touch controls удобны

### 11. UI States Consistency
- [ ] Hover / focus / selected работают
- [ ] Skeleton states не залипают
- [ ] Empty states корректны
- [ ] Нет визуальных конфликтов

### 12. Overlay & Interaction Stability
- [ ] Esc закрывает верхний слой
- [ ] Нет z-index конфликтов
- [ ] Нет “невидимых” блокирующих слоёв
- [ ] Scroll работает корректно

---

## Known UI Risks

- возможные edge-case баги на iOS PWA
- большие datasets могут влиять на performance
- сложные UGC формы требуют дальнейшего UX улучшения

---

## Performance Notes

- [ ] 500 объектов → UI работает плавно
- [ ] Нет заметных лагов при фильтрации
- [ ] Map interactions остаются быстрыми

---

## Accessibility Notes

- [ ] Focus-visible присутствует
- [ ] Основные действия доступны с клавиатуры
- [ ] Контраст читаемый в тёмной теме

---

## Final Status

READY WITH MINOR RISKS
