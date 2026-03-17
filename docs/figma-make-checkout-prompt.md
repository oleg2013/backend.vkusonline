# Prompt for Figma Make (Claude Opus 4.6) — Checkout Page

## Task

Create a single-page Checkout flow for the VKUS Online e-commerce store (premium tea & coffee). The checkout must be a new route `/#/checkout` that integrates with a real backend API.

## Project Stack

- **React 18** + **Vite 6** + **TypeScript**
- **Tailwind CSS v4** (via `@tailwindcss/vite`)
- **shadcn/ui** (Radix UI primitives) — components already available in `src/app/components/ui/`
- **react-hook-form** v7 for form validation
- **lucide-react** for icons
- **motion** (Framer Motion API) for animations
- **sonner** for toast notifications
- **react-router-dom** v7 with **HashRouter**
- Font: **Inter** (400, 500, 600, 700)
- Colors: black primary, stone-50 background, white cards, gray-100/200/400/500/600 accents, amber-50/500 highlights, green-600 for success

## Existing Code Context

### Cart State (CartContext.tsx)
```typescript
interface CartItem {
  skuId: string;
  familyId: string;
  variantId: string;
  title: string;
  price: number;      // in rubles
  image: string;
  weight: string;
  quantity: number;
}

// Hook: useCart()
// Available: items, totalPrice, totalItems, clearCart()
```

### Router (App.tsx)
Add a new route: `<Route path="/checkout" element={<CheckoutPage />} />`

The CartDrawer already has a button "Оформить заказ" — wire it to `navigate("/checkout")`.

## API Configuration

**Base URL:** `https://api.vkus.online/api/v1`

All endpoints return `{ ok: true, data: {...}, request_id: "..." }` on success, or `{ ok: false, error: {...} }` on failure.

Create a lightweight `api.ts` helper:
```typescript
const API_BASE = "https://api.vkus.online/api/v1";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  const json = await res.json();
  if (!json.ok) throw new Error(json.error?.message || "API Error");
  return json.data;
}
```

## Guest Session

Before any checkout call, ensure a guest session exists:
- Check `localStorage` for key `vkus_guest_session_id`
- If absent, generate UUID v4, store it, and call:
  ```
  POST /guest/session/bootstrap
  Body: { guest_session_id: "<uuid>" }
  ```
- All guest endpoints require header: `X-Guest-Session-ID: <uuid>`

## Page Structure — Single Page with Sections

The checkout page is a single scrollable page with a sticky order summary sidebar (desktop) / bottom sheet (mobile).

### Layout
```
Desktop (md+): 2 columns — left (form sections, ~60%) + right (sticky summary, ~40%)
Mobile: single column, summary at bottom before submit button
```

### Section 1: Customer Info
- Fields: **Имя** (name), **Телефон** (phone), **Email**
- Phone input with mask `+7 (___) ___-__-__` — validate 11 digits
- Email validation via pattern
- All fields required
- Use `react-hook-form` with shadcn `Form`, `FormField`, `FormItem`, `FormLabel`, `FormControl`, `FormMessage`, `Input`

### Section 2: City Selection (Autocomplete)
- Label: **Город доставки**
- Input with debounced autocomplete (300ms)
- API call: `POST /geo/city-suggest` with body `{ query: "..." }`
- Response example:
  ```json
  {
    "suggestions": [
      {
        "value": "г Москва",
        "_clean_name": "Москва",
        "_geo_lat": "55.7558",
        "_geo_lon": "37.6173",
        "data": { "city": "Москва", "city_fias_id": "0c5b2444-...", "geo_lat": "55.7558", "geo_lon": "37.6173" }
      },
      {
        "value": "Забайкальский край, Агинский р-н, пгт Агинское",
        "_clean_name": "Агинское",
        "_geo_lat": "51.1036",
        "_geo_lon": "114.5379",
        "data": { "settlement": "Агинское", "settlement_fias_id": "b9aee6fe-...", "geo_lat": "51.1036", "geo_lon": "114.5379" }
      }
    ]
  }
  ```
- Show dropdown list of suggestions — display `value` as the label in the dropdown (it includes region context for disambiguation)
- User MUST select from the list (no free text)
- On select, store **three values** from the selected suggestion:
  1. `_clean_name` — the **normalised city name** to send to all subsequent API calls (`delivery-options`, `create-order` etc.)
  2. `value` — the full display label to show in the input field after selection
  3. `_geo_lat` / `_geo_lon` — coordinates to centre the PVZ map on the selected city
- **Critical:** when calling `/checkout/delivery-options`, send `_clean_name` (e.g. `"Москва"`) as the `city` field, NOT `value` (e.g. `"г Москва"`). The backend normalises the name too, but sending the clean name is more reliable.

### Section 3: Delivery Provider Selection
- Label: **Служба доставки**
- Triggered after city is selected
- API call: `POST /checkout/delivery-options` with body:
  ```json
  {
    "city": "Москва",
    "cart_items": [{ "sku": "JASMINEG-001", "quantity": 2 }]
  }
  ```
  - Map cart items: `items.map(i => ({ sku: i.skuId, quantity: i.quantity }))`
- Response:
  ```json
  {
    "providers": [
      { "provider": "5post", "name": "5Post", "available": true, "pickup_points_count": 1841, "min_delivery_cost": 175.68, "estimated_days_min": 3, "estimated_days_max": 7 },
      { "provider": "magnit", "name": "Магнит", "available": true, "pickup_points_count": 297, "min_delivery_cost": 183.0, "estimated_days_min": 5, "estimated_days_max": 10 }
    ],
    "card_payment_discount_percent": 5.0
  }
  ```
- Display as RadioGroup cards (shadcn `RadioGroup`):
  - Provider name + "от X руб" + "Y-Z дней" + "N пунктов выдачи"
  - Grey out unavailable providers (available=false)
  - On select: trigger PVZ map

### Section 4: Pickup Point Selection (PVZ)
- Label: **Пункт выдачи**
- This section appears once a delivery provider is selected in Section 3
- Button: **"Выбрать пункт выдачи"** — opens a fullscreen Dialog (shadcn `Dialog`)
- **TWO different strategies** depending on the selected provider:

#### Strategy A: 5Post — Official 5Post Widget
5Post provides an official embeddable JavaScript widget. Use it directly.

**Loading the widget script (once, on first use):**
```typescript
// In a useEffect or lazy loader — load the 5Post widget script
function load5PostWidget(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector('script[src*="5post-widget"]')) {
      resolve(); return;
    }
    const script = document.createElement("script");
    script.src = "https://fivepost.ru/static/5post-widget-v1.0.js";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load 5Post widget"));
    document.head.appendChild(script);
  });
}
```

**Rendering the widget inside the Dialog:**
```typescript
// The 5Post widget exposes a global: window.fivepost.PickupPointsMap
// It renders a full Yandex Map with PVZ markers, filters (Постамат/ПВЗ/Касса),
// address search, and a "Выбрать" button on each point's popup.

// 1. Create a container div inside the Dialog body:
<div id="fivepost-widget-container" className="w-full h-[80vh]" />

// 2. After the Dialog opens and the script is loaded, initialize:
await load5PostWidget();
const widget = new (window as any).fivepost.PickupPointsMap({
  // Render target
  containerElement: document.getElementById("fivepost-widget-container"),
  // Starting city coordinates from the city-suggest response
  city: {
    lat: selectedCityLat,   // _geo_lat from city-suggest
    lon: selectedCityLon,   // _geo_lon from city-suggest
  },
  // Callback when user clicks "Выбрать" on a PVZ
  onSelect: (point: any) => {
    // point contains: id, name, address, type, lat, lon, etc.
    handlePvzSelected("5post", point);
  },
});
```

**After the user selects a PVZ from the 5Post widget:**
1. Close the Dialog
2. Call the backend to get the exact delivery cost:
   ```
   POST /checkout/estimate-delivery
   Body: { provider: "5post", pickup_point_id: point.id, cart_items: [...] }
   ```
   Response: `{ delivery_cost, pickup_point_name, cash_allowed, card_allowed, estimated_days_min, estimated_days_max }`
3. Display the selected PVZ card below the provider selection showing: name, address, delivery cost

**Important 5Post widget notes:**
- The widget uses Yandex Maps v2 internally — no need for a separate Yandex Maps API key
- The widget provides its own search bar, map controls, and point type filters
- The widget opens a balloon/popup when a marker is clicked, showing: point name, address, location description, payment methods, phone, working hours, and a "Выбрать" button
- Widget header should display: **"Выберите пункт"**
- The Dialog should be nearly fullscreen: `max-w-[900px] h-[85vh]` on desktop, `w-full h-full` on mobile

#### Strategy B: Magnit — Custom Yandex Maps Widget
Magnit does NOT provide an embeddable widget. Build a custom PVZ picker using Yandex Maps JS API v3, modeled after the 5Post widget UX.

**Loading Yandex Maps (once, on first use):**
```typescript
function loadYandexMaps(): Promise<void> {
  return new Promise((resolve, reject) => {
    if ((window as any).ymaps3) { resolve(); return; }
    const script = document.createElement("script");
    script.src = "https://api-maps.yandex.ru/v3/?apikey=YOUR_YANDEX_MAPS_KEY&lang=ru_RU";
    script.onload = () => {
      (window as any).ymaps3.ready.then(() => resolve());
    };
    script.onerror = () => reject(new Error("Failed to load Yandex Maps"));
    document.head.appendChild(script);
  });
}
```

**Fetching Magnit PVZ list from our backend:**
```
GET /delivery/magnit/pickup-points?city={_clean_name}&limit=300
```
Response: array of `{ id, name, full_address, lat, lon, cash_allowed, card_allowed }`

**Custom Magnit PVZ Picker Dialog layout:**
```
┌────────────────────────────────────────────────┐
│  ВЫБЕРИТЕ ПУНКТ                            ✕   │
│  ┌──────────────────────────────────────────┐  │
│  │ 🔍  Найти адрес               Москва ▾  │  │
│  └──────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────┐  │
│  │                                          │  │
│  │          Yandex Map (ymaps3)             │  │
│  │     with Magnit PVZ markers              │  │
│  │     (pink/purple pins)                   │  │
│  │                                          │  │
│  │  ┌─────────────────────┐                 │  │
│  │  │ МАГНИТ ПОСТ         │                 │  │
│  │  │ ул. Тверская, д. 12 │  ← popup on    │  │
│  │  │ Стоимость: 183 ₽    │    marker click │  │
│  │  │ Срок: 5-10 дней     │                 │  │
│  │  │ [  ВЫБРАТЬ  ]       │                 │  │
│  │  └─────────────────────┘                 │  │
│  │                                          │  │
│  └──────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘
```

**Implementation details for the custom Magnit widget:**
1. Initialize the map centered on selected city coordinates (`_geo_lat`, `_geo_lon` from city-suggest)
2. Add a marker for each PVZ from the API response (use a colored pin icon — Magnit brand color is red/pink)
3. Use Yandex Maps `YMapMarker` with custom React content for each pin
4. On marker click → show an info panel (overlay or side panel) with:
   - **Title**: "МАГНИТ ПОСТ" + point type
   - **Адрес**: full_address from API
   - **Стоимость доставки**: will be calculated after selection
   - **"ВЫБРАТЬ"** button (full-width, black background, white text)
5. On "ВЫБРАТЬ" click:
   - Call `POST /checkout/estimate-delivery` with `{ provider: "magnit", pickup_point_id, cart_items }`
   - Close the Dialog
   - Display selected PVZ card with name, address, delivery cost
6. Add address search functionality using Yandex Maps geocoder to re-center the map
7. On mobile: the Dialog should be fullscreen, the info panel should slide up from the bottom (bottom sheet)

**Yandex Maps API key:** Use placeholder `YOUR_YANDEX_MAPS_KEY` in the code.

#### Common PVZ selection UX (both providers)
After a PVZ is selected (from either widget), display a card below the provider selection:
```tsx
<Card className="p-4 border-green-200 bg-green-50">
  <div className="flex items-start justify-between">
    <div>
      <p className="font-medium">{pvzName}</p>
      <p className="text-sm text-gray-500">{pvzAddress}</p>
      <p className="text-sm font-medium mt-1">Доставка: {deliveryCost} руб · {daysMin}-{daysMax} дн.</p>
    </div>
    <Button variant="outline" size="sm" onClick={openPvzDialog}>
      Изменить
    </Button>
  </div>
</Card>
```

If the user changes the delivery provider in Section 3, reset the PVZ selection and hide this card.

### Section 5: Payment Method
- Label: **Способ оплаты**
- RadioGroup with 2 options:
  1. **Банковская карта** — "Скидка 5% на товары" badge in green
  2. **Наложенный платёж** — "Оплата при получении"
- COD option only available if selected PVZ has `cash_allowed === true`
- If PVZ doesn't allow cash, show only card option
- Default: card

### Section 6: Create Account (Optional)
- Checkbox: **Создать аккаунт для отслеживания заказов**
- If checked, show password field
- This is optional and can be implemented later — just show the UI

### Section 7: Order Summary (Sidebar / Bottom)
- Sticky on desktop (`sticky top-6`)
- Shows:
  - Item list with images, names, quantities, prices
  - **Товары:** subtotal
  - **Доставка:** delivery cost (or "Выберите ПВЗ" if not selected yet)
  - **Скидка за карту:** -X руб (only if payment_method === "card")
    - Calculate: `subtotal * 0.05`
  - **Итого:** grand total (dynamically calculated)
- Uses Card component with shadow

### Submit Button
- Full-width black button: **"Оформить заказ · X xxx руб"**
- Disabled until all required fields filled
- On click:
  1. Generate idempotency_key: `crypto.randomUUID()`
  2. Call:
     ```
     POST /guest/checkout/create-order
     Header: X-Guest-Session-ID: <uuid>
     Body: {
       items: cart_items.map(i => ({ sku: i.skuId, quantity: i.quantity })),
       delivery_provider: "5post",
       delivery_city: "Москва",  // use _clean_name from city-suggest, NOT the raw "г Москва"
       pickup_point_id: "...",
       pickup_point_name: "...",
       delivery_price: 175.68,
       customer_email: "...",
       customer_phone: "...",
       customer_name: "...",
       idempotency_key: "...",
       payment_method: "card" | "cod"
     }
     ```
  3. Response:
     - **card**: `{ order_number, status: "pending_payment", total, confirmation_url, guest_order_token }`
       → Redirect to `confirmation_url` (YooKassa payment page)
     - **cod**: `{ order_number, status: "processing", total, guest_order_token }`
       → Show success page with order number
  4. On success: clear cart, show toast, navigate to order confirmation

## Order Confirmation Page

Add route `/#/order-success` showing:
- Green checkmark icon
- "Заказ оформлен!"
- Order number
- For card: "Вы будете перенаправлены на страницу оплаты" (then `window.location.href = confirmation_url`)
- For COD: "Оплата при получении в пункте выдачи"

## Design Guidelines

### Visual Style
- Clean, minimal, premium feel
- White card sections on stone-50 background
- Each section as a Card with `p-6 rounded-2xl border border-gray-100`
- Section titles: `text-lg font-semibold text-gray-900`
- Section numbering: circled numbers (1, 2, 3...) in black

### Animations
- Use `motion.div` for section reveals:
  ```tsx
  <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: index * 0.1 }}>
  ```
- Button loading state with spinner animation

### Mobile Responsiveness
- Single column layout on mobile
- Map dialog takes full screen on mobile
- Summary section as bottom sticky bar on mobile
- Proper safe-area padding: `pb-safe`

### Icons to Use (lucide-react)
- `User` — customer info
- `MapPin` — city/address
- `Truck` — delivery
- `CreditCard` — payment
- `ShieldCheck` — security/trust
- `Package` — order items
- `Check` — success
- `Loader2` — loading spinner (animate-spin)

## File Structure to Create

```
src/app/components/checkout/
  CheckoutPage.tsx          — main page with all sections
  CustomerInfoSection.tsx   — name, phone, email form
  CityAutocomplete.tsx      — city search with dropdown
  DeliverySection.tsx       — provider selection + PVZ trigger
  PaymentSection.tsx        — card/cod selection
  OrderSummary.tsx          — sticky sidebar with totals
  FivePostWidgetDialog.tsx  — Dialog that loads & renders the official 5Post widget
  MagnitPvzDialog.tsx       — Dialog with custom Yandex Maps PVZ picker for Magnit
  PvzSelectedCard.tsx       — Card showing the selected PVZ with "Изменить" button
  OrderSuccessPage.tsx      — post-order confirmation
  api.ts                    — API helper functions
  types.ts                  — TypeScript types for checkout
```

## Important Notes

- All text is in **Russian**
- Currency: **руб** (with proper formatting: `1 234.56 руб`)
- Phone format: Russian (+7)
- Do NOT integrate catalog API — product data comes from CartContext
- The `skuId` from CartContext maps directly to `sku` in API calls
- All monetary values in API are in **rubles** (not kopecks)
- Guest session header is `X-Guest-Session-ID` (not Authorization)
