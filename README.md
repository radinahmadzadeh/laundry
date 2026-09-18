# 🧺 Dry Cleaning Service Platform

A modern Django platform that turns a dry cleaning shop into a full online
experience — customers order and track their laundry from their phone,
while the shop runs the whole operation from one clean admin panel.

## ✨ Highlights

- **Order in seconds** — pick items by category, choose *dry clean + iron*
  or *iron only*, set quantities, and choose in-person or courier delivery
  with a map-based location picker.
- **Live tracking** — customers follow their order from *received* all the
  way to *delivered*, using just their phone number and invoice number.
- **Instant accounts** — a customer profile is created automatically on the
  first order, no signup forms required.
- **One dashboard to run it all** — orders, customers, prices, and shop
  details are all managed from the Django admin.
- **Smart pricing catalog** — services organized into categories, each with
  its own items and prices.
- **Built-in payments** — Zarinpal integration for secure online checkout.
- **Courier pickup** — customers drop a pin on the map and enter a postal
  code for doorstep pickup.
- **Printable receipts** — a clean invoice for every order.

## 🛠 Tech Stack

Django · Tailwind CSS · Leaflet.js · Zarinpal · `jdatetime` (Shamsi calendar)

## 🧩 Core Models

- `Customer` — name, phone
- `Order` — status, price, payment state, delivery info
- `OrderItem` — item name, quantity, price (auto-updates order total)
- `PriceCategory` / `PriceItem` — the service catalog
- `ShopSettings` — shop name, tagline, phone, address