# 🧺 سامانه خشکشویی — Dry Cleaning Service Platform

A full-stack Django platform that turns a dry cleaning shop into an online
service: customers place orders, pay, and track them from their phone (as an
installable PWA), while the shop staff run the entire operation — orders,
pricing, customers, couriers — from a dedicated admin panel.

## ✨ Highlights

- **Order in seconds** — customers pick clothing items by category, choose
  *dry clean + iron* or *iron only*, set quantities, add notes, and request
  either in-person drop-off or courier pickup with a Leaflet.js map-based
  location picker.
- **Live order tracking** — logged-in customers follow every order through
  its lifecycle (`collecting → received → washing → ironing → ready →
  delivered`) in «سفارش‌های من», or jump to one by invoice number.
- **Customer accounts** — customers register/log in with phone + password to
  order, pay, track and use their wallet. Walk-in customers created by staff
  are activated by staff setting a password in the panel (there is no SMS
  verification, so accounts are never claimed online).
- **In-app wallet** — customers can top up a wallet via Zarinpal and pay for
  orders directly from their balance.
- **Online payments** — Zarinpal payment-gateway integration (sandbox by
  default) for both order payments and wallet top-ups.
- **Shop admin panel** (`/panel/`) — a separate, session-based staff login
  for managing orders, customers, the pricing catalog, courier requests, and
  shop settings, without touching Django's own `/admin/`.
- **Smart pricing catalog** — services organized into categories, each with
  its own priced items.
- **Courier dispatch workflow** — customers request pickup with a map pin +
  postal code; staff see and dispatch pending courier requests from the
  panel.
- **Printable receipts** — a clean, print-ready invoice per order, with
  subtotal, 10% tax, and totals.
- **Shamsi (Jalali) dates** — all customer-facing dates are shown in the
  Persian calendar via `jdatetime`.
- **Installable PWA** — manifest, icons, and RTL/Farsi config via
  `django-pwa`, so customers can "install" the tracking app on their phone.
- **Production-ready static files** — served via WhiteNoise, no separate
  static file server needed.

## 🛠 Tech Stack

| Layer      | Technology                                             |
|------------|---------------------------------------------------------|
| Backend    | Django 6.0 (Python)                                     |
| Database   | SQLite (default, swappable via `DATABASES`)             |
| Frontend   | Django templates + Tailwind CSS (prebuilt, see below)   |
| Maps       | Leaflet.js (courier pickup location picker)              |
| Payments   | Zarinpal (sandbox gateway)                               |
| Calendar   | `jdatetime` (Shamsi/Jalali dates for Persian users)      |
| Static     | WhiteNoise                                               |
| PWA        | `django-pwa`                                             |

## 📁 Project Structure

The code is split in two: **`backend/`** is the Django (Python) side, **`frontend/`** is
everything the browser gets — templates, styles, scripts, images and the CSS build.

```
backend/                 Django code (Python only)
  core/                  settings, root URLconf, WSGI/ASGI entry points
  orders/                customer app: models, views, payments, postal lookup,
                         account insights, template tags, migrations, tests
  panel/                 staff panel: views and URLs
frontend/                what the browser gets
  templates/             Django templates (looked up here first)
    home.html            home page skeleton; its parts live in home/
    home/                header, hero, tracking, order form, services, FAQ, footer…
      styles/            the home page's CSS, one file per area
      scripts/           the home page's JavaScript, one file per feature
    account.html         account page skeleton; its parts live in account/
    account/             dashboard, settings, styles and scripts
    components/          pieces shared by several pages (maps, courier form, icons…)
    errors/              base layout of the 400/403/404/500 pages
    panel/               staff panel pages
  static/                served at /static/ — css, js, fonts, images, PWA files
  styles/                Tailwind input (built into static/css/tailwind.css)
  package.json           Tailwind build (kept local, see .gitignore)
manage.py                Django management entry point (adds backend/ to the path)
requirements.txt         Python dependencies
```

### Core models (`backend/orders/models.py`)

- **`Customer`** — name, unique phone number, optional password hash
- **`Wallet`** / **`WalletTransaction`** — per-customer balance and its
  credit/debit history (top-ups, order payments, Zarinpal authority/ref IDs)
- **`Order`** — status, total price, payment state, delivery date, courier
  request/dispatch flags, pickup latitude/longitude/postal code
- **`OrderItem`** — item name, description, quantity, price; automatically
  recalculates the parent order's total (including 10% tax) on save/delete
- **`PriceCategory`** / **`PriceItem`** — the service catalog shown on the
  public pricing page and managed from the panel
- **`ShopSettings`** — singleton model for shop name, tagline, phone, address

## 🚀 Getting Started

### Prerequisites

- Python 3.11+
- pip

### Setup

```bash
git clone <this-repo-url>
cd laundry
python -m venv venv
```

Activate the virtual environment:

```bash
# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

Install dependencies, run migrations, and create a staff/admin user:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
```

Run the development server:

```bash
python manage.py runserver
```

- Customer site: http://127.0.0.1:8000/
- Staff panel: http://127.0.0.1:8000/panel/
- Django admin: http://127.0.0.1:8000/admin/

### Styles (Tailwind)

The Tailwind classes are compiled ahead of time into `frontend/static/css/tailwind.css`
(no CDN, so pages paint without waiting for an in-browser compiler). After
adding or changing Tailwind classes in templates, rebuild it (needs Node.js):

```bash
cd frontend
npm install
npm run build:css
```

`npm run watch:css` rebuilds on every save while you work. Commit the rebuilt
`frontend/static/css/tailwind.css`; the server itself needs no Node.

## ⚙️ Configuration

Project settings live in [`backend/core/settings.py`](backend/core/settings.py) (allowed
hosts, database, PWA app name/theme/icons) and Zarinpal gateway settings live
in [`backend/orders/views.py`](backend/orders/views.py).

Environment variables:

| Variable            | Default                                   | Purpose |
|---------------------|-------------------------------------------|---------|
| `DJANGO_DEBUG`      | `1` under `runserver`, `0` everywhere else | Debug pages expose code and settings — keep it `0` on the server. |
| `DJANGO_SECRET_KEY` | the development key in `settings.py`       | Set a long random value on the server. |
| `MAPIR_API_KEY`     | empty                                     | map.ir key for postal-code lookup (request it from info@map.ir). |
| `MAPIR_POSTAL_URL`  | empty                                     | map.ir postal-code address from their docs, with `{code}` where the postal code goes. Empty = only the 10-digit check. |

With `DEBUG` off, static files are still served by WhiteNoise straight from
`frontend/static/` (`WHITENOISE_USE_FINDERS`), so no `collectstatic` step
is needed. Customers see Persian 404/500 pages from `frontend/templates/`.

### Deploying (PythonAnywhere)

The Django packages live in `backend/`, so the server must import them from there:

- In the WSGI configuration file, add the `backend` folder to the path, e.g.
  `path = '/home/<user>/laundry/backend'` (keep
  `DJANGO_SETTINGS_MODULE = 'core.settings'`).
- If a static-files mapping is set up for `/static/`, point it at
  `/home/<user>/laundry/frontend/static`.

## 🧭 Key Routes

| Path                                   | Description                          |
|-----------------------------------------|---------------------------------------|
| `/`                                      | Home page                             |
| `/pricing/`                              | Public pricing catalog                |
| `/place-order/`                          | Create a new order                    |
| `/customer-login/`, `/customer-register/`| Customer auth                         |
| `/wallet/`                               | Customer wallet + top-up              |
| `/pay/<order_id>/`, `/verify/`           | Zarinpal order payment flow           |
| `/receipt/<order_id>/`                   | Printable receipt                     |
| `/request-courier/`                      | Courier pickup request                |
| `/panel/`                                 | Staff dashboard (session login)       |
| `/panel/orders/`, `/panel/customers/`    | Order & customer management           |
| `/panel/pricing/`                        | Pricing catalog management            |
| `/panel/courier/`                        | Courier request dispatch              |
| `/panel/settings/`                       | Shop settings                         |
| `/admin/`                                 | Django admin                          |

## 🗒 Notes

- `backend/orders/tests.py` contains the app's test suite (orders, payments, wallet,
  auth, reviews, panel) — run it with `python manage.py test orders panel`.
- `inspect_motion.py` is a standalone utility script outside the Django app;
  check its contents if you're unsure it's needed before deploying.
