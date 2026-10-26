# Gastro 360

**Digital menu for restaurants and bars, with ordering from the table and a kitchen display.** Free software ([EUPL-1.2](LICENSE.en)), self-hosted, no telemetry.

[Castellano](README.md)

Guests scan the QR code on their table, see each dish with photos and a layer-by-layer breakdown, remove ingredients, add extras and send the order. The kitchen gets it instantly on its own screen and the guest follows its status on their phone. The owner manages everything from a browser-based back office.

## Features

- **Menu and table ordering**: one QR per table, order notes, prices always computed by the server, live status (received, preparing, ready, served). Installable as an app (PWA).
- **Kitchen display**: columns per status, large buttons, sound alert and waiting time.
- **Allergens**: the 14 mandatory allergens (EU Regulation 1169/2011), with icons and names, telling "no allergens declared" apart from "not reviewed yet".
- **Loyalty stamp card**: anonymous, on the web or in Apple Wallet and Google Wallet.
- **Consent-only promotions**: unticked checkbox, stored proof of consent, unsubscribe link in every message. Sent by email (Brevo) or as a Wallet card notification.
- **Table reservations**: capacity per time slot, automatic or manual approval, a link for guests to check or cancel.
- **Takeaway and delivery orders**: delivery area by postcode, opening hours, minimum order and delivery fee; guests pay on delivery or pickup.
- **Back office**: dishes, sides, ingredients and photos, tables and printable QR codes, monthly figures and order export to CSV or Excel.
- **Eight languages**: Spanish, English, Catalan, Simplified Chinese, French, German, Italian and Portuguese, shipped with the app (no online translation service).
- **White label**: each venue's name, logo, colours and texts live in its own folder (`restaurantes/<venue>/marca.json`).

**What it does not do:** it takes no payments (no payment gateway), prints no receipts and issues no invoices. Payment stays at the restaurant's till.

**Privacy:** the browser only talks to your server. The server only reaches the Internet through channels you configure (Brevo, Apple/Google Wallet, Telegram); a fresh install makes no outgoing connections.

## Install

You only need Docker with Compose:

```
git clone https://github.com/gastro-360/gastro-360.git && cd gastro-360
./instalar.sh                # local trial with a demo restaurant
./instalar.sh --produccion   # real server, with your domain and automatic HTTPS
```

When it finishes, the installer prints the addresses of the menu, the kitchen (`/cocina`) and the back office (`/admin`), plus the back-office password (shown once). In trial mode email and Wallet are simulated and nothing leaves your machine.

- Without Docker (Python 3.10+): [docs/INSTALAR-AVANZADO.md](docs/INSTALAR-AVANZADO.md).
- Settings: [`.env.example`](.env.example) documents every variable.
- Full technical manual: [docs/MANUAL.md](docs/MANUAL.md).

The code, its comments and the documentation are written in Spanish.

## Tests

```
tests/unitarias.sh                        # unit tests (one process per module)
tests/contenedor.sh                       # against the Docker container
tests/e2e.sh                              # browser (Playwright) at 360 and 1280 px
tests/privacidad.sh                       # the browser requests nothing from other hosts
```

## Licence and warranty

[EUPL-1.2](LICENSE.en). Provided **without any warranty** ([SUPPORT.md](SUPPORT.md)). Third-party components: [THIRD-PARTY.md](THIRD-PARTY.md). The legal texts in `docs/legal/` are templates: have a professional review them before use.

Contributing: [CONTRIBUTING.md](CONTRIBUTING.md). Security: [SECURITY.md](SECURITY.md).
