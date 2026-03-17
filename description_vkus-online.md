# VKUS ONLINE — Полное техническое описание проекта

> Этот документ предназначен для передачи полного контекста проекта в другой диалог с Claude.
> Цель: максимально точно воспроизвести проект, сохранив архитектуру, дизайн-паттерны, логику данных и UX-решения.

---

## 1. Общее описание

**VKUS ONLINE** — премиальный интернет-магазин чая и кофе (vkus.online).
- **Стек:** React 18 + TypeScript + Tailwind CSS v4 + Motion (framer-motion) + react-router-dom (HashRouter)
- **UI-библиотека:** shadcn/ui (Radix-примитивы + Tailwind), lucide-react для иконок
- **Слайдеры:** react-slick + slick-carousel
- **Уведомления:** sonner (toast)
- **Bundler:** Vite
- **Шрифт:** Inter (400, 500, 600, 700) через Google Fonts
- **Подход:** Mobile-first, responsive, SPA с HashRouter

---

## 2. Дизайн-система и визуальный тон

### Палитра
- **Фон:** `stone-50` (основной), `white` (карточки, панели)
- **Текст:** `stone-900` (основной), `stone-500`/`gray-500` (вторичный)
- **Акценты:** `amber-600`/`amber-700` (категории, ссылки в блоге), `emerald` (чай), `amber` (кофе), `rose` (шоколад)
- **Footer:** `bg-[#111]` (почти черный)
- **Корзина бейдж:** `bg-black text-white`
- **Избранное бейдж:** `bg-red-500 text-white`
- **Хедер:** всегда `bg-white`, с `shadow-sm` при скролле

### Типографика
- Заголовки: `font-bold`, `tracking-tight` или `tracking-tighter`
- Логотип: `font-bold text-xl/2xl tracking-tighter uppercase` — текстовый "VKUS ONLINE"
- Карточки: компактная типографика, `text-sm`/`text-xs` для метаданных
- Премиальный тон: "воздушно, современно, легко выбрать"

### Скругления
- Карточки: `rounded-xl` / `rounded-2xl`
- Кнопки: `rounded-full` (иконки), `rounded-xl`/`rounded-2xl` (CTA)
- Модалки: `rounded-[2rem]` / `rounded-[2.5rem]`
- Изображения: `rounded-lg` / `rounded-xl` / `rounded-2xl`

### Анимации (Motion)
- `AnimatePresence` для всех переходов (модалки, поиск, карточки)
- Карточки: `whileInView` fade-in (`opacity: 0, y: 20` -> `opacity: 1, y: 0`)
- Модалки: spring-анимация для drawer (`type: "spring", damping: 28, stiffness: 300`)
- Бейджи: `scale: 0.5 -> 1` при изменении
- Hover на десктопе: `group-hover:scale-105` для изображений, `hover:shadow-xl` для карточек

### Тач-взаимодействия (mobile)
- Long-press peek overlay (iOS-style) на карточках: 350ms нажатие открывает preview
- Auto-open peek через 6 секунд hover
- Body scroll lock при открытом peek
- Tap threshold 8px для отмены жеста

---

## 3. Архитектура приложения

### Файловая структура
```
/src/
  /app/
    App.tsx                    — Корневой компонент (HashRouter + Providers + Routes)
    types.ts                   — CatalogProduct interface
    /components/
      HomePage.tsx             — Главная страница (композиция секций)
      Header.tsx               — Sticky хедер (mobile + desktop)
      Footer.tsx               — Футер
      HeroConcierge.tsx        — Hero-секция с 3-step подбором
      HitsNew.tsx              — "Хиты" горизонтальный scroll
      CatalogV2.tsx            — Каталог с двумя режимами
      FamilyCard.tsx           — Desktop-карточка семейства
      MobileFamilyCard.tsx     — Mobile-карточка семейства (с peek)
      ProductCard.tsx          — Desktop-карточка SKU
      MobileProductCard.tsx    — Mobile-карточка SKU (с peek)
      FamilyDetailModal.tsx    — Модалка товара (family view)
      ProductDetailModal.tsx   — Fallback модалка для unmapped SKU
      CartContext.tsx           — Context + Provider корзины
      CartDrawer.tsx           — Drawer корзины (right-side)
      FavoritesContext.tsx      — Context + Provider избранного (localStorage)
      FavoritesDrawer.tsx       — Drawer избранного
      SearchOverlay.tsx         — Полноэкранный overlay поиска
      QuickPick.tsx             — Мини-конфигуратор фильтров
      Subscription.tsx          — Блок подписки
      WhyUs.tsx                 — "Почему мы" (4 фичи)
      Guides.tsx                — Журнал/гайды
      Reviews.tsx               — Отзывы (слайдер)
      Collections.tsx           — Коллекции (сетка)
      MobileNav.tsx             — Мобильная навигация (не используется в текущей сборке)
      AboutPage.tsx             — Страница "О бренде"
      BlogPage.tsx              — Блог (список)
      BlogPostPage.tsx          — Отдельная статья блога
      HeroSlider.tsx            — Слайдер в Hero AboutPage
      CoffeeSlider.tsx          — Слайдер кофе в AboutPage
      TeaSlider.tsx             — Слайдер чая в AboutPage
    /derived/
      blogData.ts              — Данные блога (статьи)
  /data/
    catalog.ts                 — ЕДИНСТВЕННЫЙ ИСТОЧНИК ИСТИНЫ для каталога
    step1-data.ts              — SKU audit, gold list
    step2-data.ts              — Families DB, migration map
    step3-data.ts              — Taxonomy, tags, brew map
    step4-data.ts              — Relationships, collections, homepage controls
  /derived/
    index.ts                   — Barrel export (данные + адаптеры)
    catalogDerived.ts          — Re-export из catalog.ts
    catalogAdapters.ts         — Чистые функции-адаптеры
  /styles/
    index.css                  — Entry (импортирует fonts, tailwind, theme)
    fonts.css                  — @import Inter от Google Fonts
    tailwind.css               — Tailwind v4 с tw-animate-css
    theme.css                  — Tailwind @theme (font-sans: Inter), custom scrollbar, slick dots
```

### Провайдеры (обертки App)
```tsx
<HashRouter>
  <CartProvider>
    <FavoritesProvider>
      <AppInner />
    </FavoritesProvider>
  </CartProvider>
</HashRouter>
```

### Маршрутизация
- **HashRouter** (не BrowserRouter) — работает в iframe Figma Make
- Маршруты:
  - `/` — HomePage
  - `/about` — AboutPage
  - `/blog` — BlogPage
  - `/blog/:id` — BlogPostPage
  - `/family/*` — HomePage (фон для модалки) + FamilyDetailModal
- Модалка товара синхронизирована с URL: `/family/{familyId}`

---

## 4. Модель данных (критически важная часть)

### 4.1. Двухслойная архитектура данных

**Слой 1: PRODUCTS_DB (канонические SKU)**
```typescript
interface CatalogProduct {
  id: string;           // SKU ID (e.g., "550075", "770009", "703")
  title: string;        // Русское название
  price: number;        // Цена в рублях
  images: string[];     // Массив URL изображений (webp с vkus.com)
  rating: number;       // 4.7–5.0
  tags: string[];       // Хештеги: "#черный", "#premium_line", "#без_кофеина"
  type: "tea" | "coffee" | "accessory";
  subType?: string;     // "black", "herbal", "green", "oolong", "puer", "espresso", "cocoa", "assorted"...
  format?: "loose" | "bags" | "beans" | "ground" | "capsule" | "powder";
  taste?: string[];     // ["spicy", "sweet", "citrus"]
  sku?: string;         // Дублирует id
  composition?: string; // Состав
  internationalName?: string; // Английское название
  weight?: string;      // "120 грамм", "50 пирамидок по 2 грамма"
  description?: string; // Полное описание (с \n\n)
  caffeine?: string;    // "decaf"
}
```
- **~48 SKU** в массиве
- Категории: чай (~34), кофе (~13), горячий шоколад (2)
- Изображения хостятся на `vkus.com/vkusonline/...` (webp)
- URL паттерн: `https://vkus.com/vkusonline/{Tea|Coffee}/{PackType}/{SKU_ID}/{N}.webp`

**Слой 2: Семейства (Families) — derived-данные**
```typescript
interface FamilyEntry {
  familyId: string;           // e.g., "tea_black_english_breakfast"
  familyKey: string;          // "black english breakfast"
  displayNameRu: string;      // "Английский завтрак"
  displayNameEn: string;      // "English Breakfast"
  typeNormalized: string;     // "tea" | "coffee" | "hot_chocolate"
  subTypeNormalized: string;  // "black", "herbal", "oolong", etc.
  notes: string[];            // ["classic", "strong", "ceylon"]
  momentGuess: string;        // "morning" | "day" | "evening"
  moodGuess: string;          // "energy" | "relax" | "focus" | "wellness" | "comfort"
  variants: FamilyVariant[];  // Массив вариантов упаковки
}

interface FamilyVariant {
  variantId: string;        // "bags_20" | "bags_50" | "loose_leaf" | "beans_1kg" | "ground_500g" | "ground_250g" | "powder_1kg" | "box_26" | "box_104"
  skuId: string;            // Ссылка на PRODUCTS_DB
  packagingKind: string;    // "tea_bags_20", "tea_loose_doypack", "coffee_beans_1kg"
  format: string;           // "bags" | "loose" | "beans" | "ground" | "powder"
  weight: string;
  price: number;
  imagesCount: number;
  firstImage: string;
}
```

**MIGRATION_MAP** — связующее звено:
```typescript
interface MigrationEntry {
  skuId: string;      // → PRODUCTS_DB.id
  familyId: string;   // → FamilyEntry.familyId
  variantId: string;  // → FamilyVariant.variantId
}
```

### 4.2. Инварианты данных (НЕЛЬЗЯ нарушать)
1. **images** берутся из SKU выбранного варианта (`products.find(p => p.id === variant.skuId).images`)
2. **description** показывается дословно из SKU (не сокращать, не переписывать)
3. **internationalName** не удалять (можно прятать в аккордеон)
4. **weight** не удалять
5. При переключении варианта упаковки — галерея и превью обновляются из нового SKU

### 4.3. Адаптерный слой (catalogAdapters.ts)
Набор чистых функций для работы с данными:
- `getSkuById(products, skuId)` — найти SKU
- `getFamilyById(familyId)` — найти семейство
- `getFamilyBySkuId(skuId)` — найти семейство по SKU
- `getDefaultVariantId(familyId)` — дефолтный вариант по приоритету:
  - Чай: `bags_20 > bags_50 > loose_leaf`
  - Кофе: `beans_1kg > ground_500g > ground_250g`
  - Шоколад: `powder_1kg`
  - Ассорти: `box_26 > box_104`
- `getPreviewImage(products, familyId, variantId)` — первое изображение
- `getGalleryImages(products, familyId, variantId)` — все изображения
- `getBrewForSku(skuId)` — рекомендации по завариванию
- `getDerivedTagsForFamily(familyId)` — filterTags + marketingTags
- `getSimilarFamilies(familyId)` — похожие по нотам
- `getCrossSellSuggestion(familyId)` — кросс-продажа
- `runCatalogQA(products)` — проверка целостности (dev-only)

### 4.4. Таксономия и фильтры
```
root: tea | coffee | hot_chocolate
tea subtypes: black, green, white, oolong, puer, herbal, fruit, rooibos, assorted
coffee subtypes: espresso_beans, ground, decaf
hot_chocolate subtypes: cocoa_powder

Фильтры:
- format: loose, bags, beans, ground, powder
- mood: energy, relax, comfort, focus, wellness
- moment: morning, day, evening
- notes: citrus, berry, sweet, chocolate, spicy, floral, nutty, creamy, fresh, wood, earth, ginger
```

### 4.5. Коллекции (используются в HitsNew и каталоге)
Предопределенные подборки:
- `col_morning_energy` — Утро и Энергия
- `col_evening_relax` — Вечерний Релакс
- `col_dessert` — Сладкий Момент
- `col_focus_work` — Фокус и Работа
- `col_wellness` — Wellness & Detox
- `col_decaf` — Без Кофеина
- `col_coffee_beans` — Кофе в зернах
- `col_discover` — Открытия
- `col_tea_ceremony` — Чайная церемония
- `col_gifts` — Подарки

### 4.6. Relationships (рекомендации)
- **similar_by_notes** — похожие семейства по вкусовым нотам
- **cross_sell** — кросс-продажи (пример: кофе → какао для моки)
- **mixComposition** — состав наборов-ассорти (какие семейства входят в набор)

---

## 5. Компоненты: подробное описание

### 5.1. Header.tsx (~500 строк)
**Архитектура:** два отдельных блока — mobile (`md:hidden`) и desktop (`hidden md:flex`)

**Mobile хедер:**
- Слева: гамбургер (Menu icon) + логотип "VKUS ONLINE" (Link)
- Справа: поиск (Search), избранное (Heart + бейдж), корзина (ShoppingBag + бейдж)
- **Критичная особенность iOS Safari:** `<input>` поиска **всегда в DOM** (даже когда скрыт), потому что iOS требует синхронный `focus()` в цепочке тач-событий. Когда поиск закрыт — input позиционирован с `opacity: 0.01`, при открытии — transition reveal
- Кнопка "Отмена" для закрытия мобильного поиска

**Desktop хедер:**
- Логотип | Nav (Чай, Кофе, Подарки, Аксессуары, Блог, О бренде) | Search bar (rounded-full) | Избранное + Корзина
- На tablet (md но не lg): гамбургер вместо nav

**Mobile Menu (overlay):**
- Полноэкранный overlay (`fixed inset-0 z-[60]`)
- Категории с иконками и стрелкой ChevronRight
- Ссылки: Каталог, О бренде, Блог, Доставка, Контакты
- При навигации — меню закрывается автоматически

**Логотип click:** вызывает `onLogoClick` → сбрасывает поиск, каталог, concierge; scroll to top с агрессивным multi-target (для работы в iframe)

### 5.2. HeroConcierge.tsx — 3-step подбор напитка
**Step 0:** Выбор категории (Чай/Кофе/Подарки/Шоколад)
- Mobile: компактная 2x2 grid с иконками
- Desktop: 4 крупные карточки с видео-анимацией (webm с vkus.com), показывающие количество вкусов в каждой категории
- Видео на hover/при выборе: `https://vkus.com/vkusonline.content/video/{type}_promo.webm`

**Step 1:** Выбор настроения (Бодрость/Релакс/Фокус/Здоровье/Наслаждение)
- Карточки с иконками (Zap/Moon/Sun/Heart/Sparkles) и описанием

**Step 2:** Результат — 3 рекомендованных товара
- Фильтрация по category + mood через теги
- Карточки с изображением, названием, ценой
- Кнопки: "Начать заново", "Весь каталог"

**Архитектура верстки (desktop):**
```
<section className="relative">
  {/* Background Layer */}
  <div className="absolute inset-0 z-0">
    {/* Video / Image фон */}
  </div>
  {/* Content Container */}
  <div className="relative z-10">
    <div className="bg-white/80 backdrop-blur-2xl max-w-[1060px]">
      {/* Steps content */}
    </div>
  </div>
</section>
```

**Reset:** `resetKey` (число) — при инкременте сбрасывает step/category/mood

### 5.3. CatalogV2.tsx — Каталог с двумя режимами
**Два режима:**
1. **"По Вкусам" (Taste mode):** показывает FamilyCard / MobileFamilyCard — семейства с чипами вариантов
2. **"По Упаковкам" (Product mode):** показывает ProductCard / MobileProductCard — отдельные SKU

**Фильтры:**
- Табы категорий: Все | Чай | Кофе | Шоколад | Подарки (с иконками LayoutGrid/Leaf/Coffee/Candy/Gift)
- Панель фильтров (toggleable): формат, время дня, настроение, ноты вкуса — все chip-based
- Quick Pick сценарии: предустановленные комбинации фильтров ("Утренний ритуал", "Десертный вечер" и т.п.)

**External filter:** `externalFilter: { type: "category" | "search" | "reset", value: string }`
- "category" — устанавливает таб категории
- "search" — фильтр по поисковому запросу
- "reset" — сброс всех фильтров, категории, режима

**Сетка:**
- Mobile: `grid-cols-2` с `MobileFamilyCard`/`MobileProductCard`
- Desktop: `grid-cols-3` или `grid-cols-4` с `FamilyCard`/`ProductCard`

### 5.4. FamilyCard.tsx / MobileFamilyCard.tsx — Карточки семейств
**Desktop FamilyCard:**
- Слайдер изображений с навигацией (ChevronLeft/ChevronRight)
- Variant chips (переключение упаковки, меняет цену/вес/изображения)
- Цена + вес в footer
- Кнопка "В корзину" (Plus icon)
- Кнопка избранного (Heart, заливается красным если в избранном)
- Marketing tags (chips) из derived data
- Brew info (время + температура) если есть
- Hover effects: shadow, image zoom

**MobileFamilyCard (iOS-style peek):**
- Базовая карточка: изображение (aspect-square), название, "от X ₽", variant chip labels
- **Long-press (350ms):** открывает peek overlay с:
  - Полноэкранным backdrop
  - Увеличенной карточкой (portal в body)
  - Навигация по изображениям (swipe dots)
  - Цена, вес, brew info
  - Кнопка "Подробнее" → открывает FamilyDetailModal
- **Auto-open:** через 6 секунд hover (для desktop-превью)
- Body scroll lock при открытом peek

### 5.5. FamilyDetailModal.tsx — Модальное окно товара
- **Full-screen overlay** с spring-анимацией
- **Галерея:** все изображения SKU с навигацией, zoom при клике
- **Variant selector:** горизонтальные чипы (20 шт / 50 шт / Листовой и т.д.)
- **Цена + вес** — обновляются при переключении варианта
- **Описание** — дословно из SKU.description
- **Brew info** — время заваривания, температура (если есть для SKU)
- **Профессиональные детали** (аккордеон): internationalName, SKU ID, формат, состав
- **Рекомендации:** похожие семейства (similar_by_notes) + кросс-продажа
- **Кнопки:** "В корзину" (добавляет через CartContext), "Избранное" (toggle)
- **Навигация:** при клике на рекомендованный товар — `onNavigateFamily` меняет URL (replace)

### 5.6. CartContext.tsx / CartDrawer.tsx — Корзина
**CartItem:**
```typescript
interface CartItem {
  skuId: string;
  familyId: string;
  variantId: string;
  title: string;
  price: number;
  image: string;
  weight: string;
  quantity: number;
}
```
- In-memory state (без persistence)
- `addItem` — если SKU уже есть, увеличивает quantity
- `updateQty(skuId, qty)` — если qty <= 0, удаляет
- `totalItems`, `totalPrice` — computed
- `isCartOpen` / `toggleCart` — управление drawer

**CartDrawer:**
- Right-side drawer (`fixed top-0 right-0 w-full max-w-md`)
- Spring-анимация входа/выхода
- Список товаров с +/- кнопками и удалением
- Total price footer с кнопкой "Оформить заказ"
- Backdrop blur

### 5.7. FavoritesContext.tsx / FavoritesDrawer.tsx — Избранное
- **Persistence:** localStorage (`vkus_favorites`)
- Хранит `Set<string>` из familyId
- `toggle(familyId)` — add/remove
- `isFavorite(familyId)` — проверка
- FavoritesDrawer: аналогичен CartDrawer, показывает карточки с кнопками "В корзину" и "Удалить"

### 5.8. SearchOverlay.tsx — Полноэкранный поиск
- Показывается при `liveSearchText.length >= 1`
- Поиск по: familyId, displayNameRu/En, notes, subType, composition
- Использует `SEARCH_SYNONYMS` для расширения запроса
- Результаты: карточки семейств с изображением, типом, нотами, ценой "от X ₽"
- При малом количестве результатов — показывает SKU-level результаты
- Suggestion chips для быстрых запросов
- Клик по результату → открывает FamilyDetailModal

### 5.9. Остальные секции главной
**HitsNew.tsx** — "Хиты" горизонтальный scroll:
- Собирает товары из нескольких коллекций (col_discover, col_morning_energy, col_dessert...)
- Горизонтальная прокрутка с кнопками навигации
- Карточки: изображение, название, тег коллекции, "от X ₽"
- Клик → FamilyDetailModal

**Subscription.tsx** — Блок подписки:
- Тёмный фон (#2c2520), rounded-[2rem]
- Текст + преимущества (гибкий график, свежесть, пауза)
- CTA кнопка

**WhyUs.tsx** — 4 преимущества:
- Свежесть, Происхождение, Контроль, Доставка
- Иконки в белых квадратах с shadow

**Guides.tsx** — Журнал:
- 3 карточки статей с Unsplash-изображениями
- Категория (badge) + заголовок

**Reviews.tsx** — Отзывы:
- react-slick слайдер, 3/2/1 slides responsive
- Звездный рейтинг, имя, текст

### 5.10. Страницы
**AboutPage.tsx** — О бренде:
- Hero с фото-слайдером (HeroSlider)
- Статистика (StatCard): 2020, 50+ вкусов, 15000+ клиентов, Швейцария
- Секция кофе (CoffeeSlider) и чая (TeaSlider)
- FAQ аккордеон
- Навигация в каталог через custom event `navigate-to-catalog`

**BlogPage.tsx / BlogPostPage.tsx** — Блог:
- Featured-пост (большая карточка)
- Сетка постов
- Фильтр по категориям
- Отдельная страница поста с rich content (h2, h3, paragraph, image, list, quote)
- Related posts

---

## 6. Паттерны взаимодействия

### 6.1. Навигация и состояние
- **Logo click** → полный reset: навигация на `/`, сброс поиска, каталога, concierge. Корзина сохраняется.
- **Category click** (из хедера/concierge) → scroll к каталогу + externalFilter category
- **Search** → overlay в реальном времени; Enter → scroll к каталогу + externalFilter search
- **Product click** → проверка MIGRATION_MAP: если есть семейство → FamilyDetailModal по URL; если нет → fallback ProductDetailModal

### 6.2. iOS Safari совместимость
- Search input always-in-DOM для синхронного focus()
- Aggressive scroll-to-top с multi-target (documentElement, body, window, parent)
- `fontSize: "16px"` на мобильных инпутах (предотвращает zoom)
- `enterKeyHint="search"` для мобильной клавиатуры
- `-webkit-tap-highlight-color: transparent`
- `-webkit-text-size-adjust: 100%`

### 6.3. Скролл
- `no-scrollbar` / `scrollbar-hide` для горизонтальных прокруток
- `overflow-x: hidden` на html и body
- Safe area: `pb-safe { padding-bottom: env(safe-area-inset-bottom) }`

---

## 7. Ключевые архитектурные решения

### 7.1. Абстракция бэкенда (MUST)
Весь бэкенд-код ДОЛЖЕН идти через единый слой абстракции:
- `/src/services/api.ts` — главный адаптер
- Компоненты НИКОГДА не вызывают `supabase.*` или `fetch()` напрямую
- При смене провайдера (Supabase → self-hosted → кастомный) меняется только адаптер

### 7.2. Data flow
```
PRODUCTS_DB (canonical SKUs) → catalog.ts
         ↓
   step1-4-data.ts (enrichment: families, taxonomy, tags, relationships)
         ↓
   catalogDerived.ts (re-export)
         ↓
   catalogAdapters.ts (pure functions: getFamily, getBrew, getSimilar...)
         ↓
   derived/index.ts (barrel export)
         ↓
   Components (import from '../../derived')
```

### 7.3. TypeScript вместо JSON
Изначально данные были в JSON-файлах, но из-за проблем с парсингом в бандлере Figma Make — переведены в `.ts` модули с `export default { ... }`.

### 7.4. Catalog QA
При монтировании App.tsx запускается `runCatalogQA(PRODUCTS_DB)`, который проверяет:
- Все SKU из PRODUCTS_DB есть в MIGRATION_MAP
- Все SKU из MIGRATION_MAP есть в PRODUCTS_DB
- Нет дубликатов
- SKU_GOLD_LIST синхронизирован
Результат логируется в консоль (зеленый PASS / оранжевый FAIL).

---

## 8. CSS и Tailwind v4

### Конфигурация
```css
/* theme.css */
@import "tailwindcss";
@theme {
  --font-sans: 'Inter', system-ui, sans-serif;
}
```

### Кастомные классы
- `.no-scrollbar` / `.scrollbar-hide` — скрытие scrollbar
- `.pb-safe` — safe area для мобильных
- Slick dots кастомизация: серые неактивные, черные активные

### Часто используемые паттерны
```
container mx-auto px-4 md:px-6    — обертка секций
rounded-2xl / rounded-[2rem]      — скругления
bg-white/80 backdrop-blur-2xl     — стеклянные панели
shadow-sm / shadow-xl             — тени
transition-all duration-300        — плавные переходы
```

---

## 9. Зависимости (package.json)

### Основные
- `react` 18.3.1, `react-dom` 18.3.1
- `react-router-dom` ^7.13.0 (HashRouter)
- `motion` 12.23.24 (import from "motion/react")
- `lucide-react` 0.487.0
- `sonner` 2.0.3
- `react-slick` 0.31.0, `slick-carousel` ^1.8.1
- `tailwindcss` 4.1.12
- `tw-animate-css` 1.3.8
- `class-variance-authority` 0.7.1
- `clsx` 2.1.1, `tailwind-merge` 3.2.0

### UI (shadcn/Radix)
- Полный набор `@radix-ui/react-*` компонентов
- `cmdk` 1.1.1

### Дополнительные
- `@mui/material` 7.3.5 + `@emotion/react` + `@emotion/styled`
- `recharts` 2.15.2
- `react-dnd` + `react-dnd-html5-backend`
- `vaul` 1.1.2 (drawer)
- `date-fns` 3.6.0

---

## 10. Важные технические нюансы

### 10.1. При редактировании Header.tsx
Файл ~500 строк с двумя независимыми блоками (mobile + desktop). Автоматические инструменты (fast_apply) неоднократно повреждали десктопную секцию — нужна осторожность.

### 10.2. Image URL паттерны
```
Чай:    https://vkus.com/vkusonline/Tea/{PackType}/{SKU_ID}/{N}.webp
Кофе:   https://vkus.com/vkusonline/Coffee/{PackType}/{SKU_ID}/{N}.webp
Видео:  https://vkus.com/vkusonline.content/video/{name}.webm

PackType: Doypack, 50_Box, 20_Box, Beans, Ground
```

### 10.3. Variant labels (повторяются в нескольких компонентах)
```typescript
const VARIANT_LABELS: Record<string, string> = {
  bags_20: "20 пирамидок",  // или "20 шт" (короткая форма)
  bags_50: "50 пирамидок",
  loose_leaf: "Листовой (Doypack)",
  beans_1kg: "Зёрна 1 кг",
  ground_500g: "Молотый 500 г",
  ground_250g: "Молотый 250 г",
  powder_1kg: "Порошок 1 кг",
  box_26: "Набор 26 шт",
  box_104: "Набор 104 шт",
};
```

### 10.4. z-index карта
- Header: `z-50`
- Mobile menu: `z-[60]`
- Search overlay: между header и modals
- Cart/Favorites drawer: `z-[80]` (backdrop), `z-[81]` (panel)
- FamilyDetailModal: выше всего
- Peek overlay (MobileFamilyCard): portal в body, высокий z-index

---

## 11. Что НЕ реализовано (пока)

- Бэкенд / серверная часть (заготовка Supabase Edge Functions есть, но не подключена)
- Оформление заказа (checkout flow)
- Авторизация пользователей
- Persistence корзины (сейчас только in-memory)
- Реальные платежи
- Доставка (API СДЭК и т.п.)
- Email-уведомления
- Админка / CMS для каталога

---

## 12. Guidelines (правила для AI)

### MUST (жёсткие инварианты)
1. Не терять данные: description, images, internationalName, weight — из канонического PRODUCTS_DB
2. Два режима каталога ("Вкусы" и "Упаковки") работают параллельно
3. Переключение варианта не обнуляет картинки — галерея из SKU варианта
4. Responsive всегда (mobile-first)
5. Доступность (контраст, aria-label, фокус-стейты)
6. Абстракция бэкенда — всё через `/src/services/api.ts`

### SHOULD
- React + TS + Tailwind + motion
- Маленькие компоненты
- "Воздушный" премиальный UI
- Минимум новых библиотек

### Режимы работы
- **MODE: EXPLORE** — можно предлагать альтернативы, менять структуру
- **MODE: BUILD** — минимальные изменения, точечные улучшения
- По умолчанию: EXPLORE
