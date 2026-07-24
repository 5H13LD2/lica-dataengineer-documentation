# Gulong Mobile — Project Handoff

## Overview

This project is an Expo SDK 57 and React Native application written in strict TypeScript. It combines the original mobile scaffold, a validated warehouse CSV snapshot, the UI design migrated from `home-screen`, and the guest-cart feature migrated from `gulong-cart-package`.

The app currently provides a working branded home screen, tire-size search, text search, product results, catalog browsing, product details, a guest cart, a chat placeholder, and a phone hotline action.

## Current status

| Area | Status | Notes |
| --- | --- | --- |
| Expo application shell | Working | Expo Router with strict TypeScript |
| Home screen | Working | Migrated Gulong.ph mobile design |
| Product catalog | Working with CSV snapshot | 3,133 validated products generated from 3,294 source rows |
| Tire-size search | Working | Cascading selections prevent dead ends |
| Text search | Working | Searches product names, brands, and sizes |
| Product details | Working | Includes single-item and set-of-four cart actions |
| Guest cart | Working in memory | Quantity controls, stock limits, savings, and subtotal |
| Branch data/API | Available | 11 branch fixtures; no branch UI yet |
| Chat | Placeholder | UI only; integration is pending |
| Checkout | Placeholder | Cart CTA currently shows an informational alert |
| Authentication | Not implemented | Add as a complete feature when requirements are ready |

## Work completed

### Project foundation

- Converted the original zero-byte scaffold into a runnable Expo Router project.
- Configured Expo SDK 57, React Native 0.86, React 19, and TypeScript 6.
- Enabled strict TypeScript, unchecked-index validation, and the `@/*` path alias.
- Added the root TanStack Query provider.
- Generated and maintained `package-lock.json` for reproducible npm installs.

### Packages installed

- Expo and Expo Router
- React and React Native
- TanStack Query
- Zustand
- Axios
- React Hook Form
- Zod
- Expo Vector Icons
- React Native Safe Area Context and Screens

### Temporary warehouse snapshot

- Added a documented CSV-to-TypeScript generation pipeline using Zod validation.
- Connected 3,133 valid warehouse products from the July 14, 2026 snapshot.
- Rejected 161 incomplete products instead of allowing invalid tire sizes into the app.
- Preserved snapshot metadata, warehouse discovery, SQL, validation results, and a data dictionary.
- Modeled inventory as unknown because no reliable customer-safe inventory feed was exported.
- Kept the earlier 11-branch fixture temporarily because the warehouse export did not include a reliable branch master.
- Defined shared domain types for products, prices, tire sizes, branches, appointments, and orders.
- Added a simulated API supporting product search, product lookup, brands, branches, and appointment slots.
- Added artificial latency so loading states can be developed and demonstrated.
- Documented refresh, security, and production API migration procedures in `docs/SNAPSHOT_DATA.md`.

### Design migration

- Migrated the `home-screen` brand tokens into the main application.
- Added reusable compatibility exports for colors, spacing, radii, and typography.
- Implemented the Gulong.ph home-page design.
- Implemented cascading Width → Aspect Ratio → Rim Diameter selectors.
- Ensured every selectable size combination is derived from the mock catalog.
- Added branded catalog and search-result product cards.
- Added the Home, Shop Tires, Chat, and Call bottom navigation.
- Added a product-details screen.
- Kept Expo route files thin where possible and placed screen logic in feature folders.

### Cart integration

- Added a guest-first Zustand cart with a stable feature-level API.
- Added live cart badges to the home and product-detail headers.
- Connected catalog cards and product details to the cart.
- Added single-item and set-of-four actions on product details.
- Added quantity steppers and set-of-two/set-of-four quick controls.
- Capped quantities at available mock stock and disabled unavailable quick sets.
- Added item removal, subtotal, promotional savings, and total item selectors.
- Added an empty-cart state and checkout coming-soon handoff.
- Kept cart types, state, components, and screens in separate feature folders for maintainability.

## Current user flows

1. A customer opens the Home tab.
2. They can search by product name, brand, or tire size text.
3. They can alternatively select a valid tire width, aspect ratio, and rim diameter.
4. The app opens a filtered results screen backed by the mock API.
5. Selecting a product opens its product-details screen.
6. Shop Tires displays the full mock catalog.
7. Chat displays an honest coming-soon state.
8. Call launches the device dialer with the configured hotline.
9. Add to Cart updates the live header badge and guest cart.
10. The cart supports quantity changes, tire-set shortcuts, removal, savings, and subtotal calculations.

## Folder structure

```text
gulong-mobile/
├── app/                              # Expo Router route layer
│   ├── _layout.tsx                   # Root providers and navigation stack
│   ├── (tabs)/
│   │   ├── _layout.tsx               # Home, Shop Tires, Chat, Call tabs
│   │   ├── index.tsx                 # Thin route → HomeScreen
│   │   ├── shop.tsx                  # Thin route → CatalogScreen
│   │   ├── chat.tsx                  # Thin route → ChatScreen
│   │   └── call.tsx                  # Route required for intercepted call action
│   ├── cart.tsx                      # Thin route → CartScreen
│   ├── product/
│   │   └── [id].tsx                  # Product-details route
│   └── search-results.tsx            # Thin route → SearchResultsScreen
│
├── src/
│   ├── features/                     # Business features grouped by domain
│   │   ├── branches/
│   │   │   └── api/
│   │   │       ├── branches.api.ts
│   │   │       └── branches.mock.ts
│   │   ├── cart/
│   │   │   ├── components/CartButton.tsx
│   │   │   ├── screens/CartScreen.tsx
│   │   │   ├── store/cart.store.ts
│   │   │   └── types/cart.types.ts
│   │   ├── catalog/
│   │   │   ├── api/
│   │   │   │   ├── catalog.api.ts
│   │   │   │   └── products.mock.ts
│   │   │   ├── components/ProductCard.tsx
│   │   │   └── screens/CatalogScreen.tsx
│   │   ├── home/
│   │   │   └── screens/HomeScreen.tsx
│   │   ├── search/
│   │   │   ├── hooks/useTireSizeOptions.ts
│   │   │   └── screens/SearchResultsScreen.tsx
│   │   └── support/
│   │   │   └── screens/ChatScreen.tsx
│   ├── providers/
│   │   └── QueryProvider.tsx         # TanStack Query client boundary
│   ├── services/
│   │   └── api/mockApi.ts            # Swappable simulated backend
│   ├── data/
│   │   └── generated/                 # Generated snapshot data; do not edit
│   ├── shared/
│   │   └── components/SelectField.tsx
│   ├── theme/
│   │   ├── tokens.ts                 # Design-system source of truth
│   │   ├── colors.ts                 # Compatibility re-export
│   │   ├── spacing.ts                # Compatibility re-export
│   │   └── typography.ts             # Compatibility re-export
│   └── types/
│       └── domain.types.ts           # Shared domain contracts
│
├── docs/
│   └── SNAPSHOT_DATA.md              # CSV workflow and API migration guide
├── exports/
│   └── mobile_snapshot_2026-07-14/   # Warehouse CSVs and audit artifacts
├── scripts/
│   ├── generate-snapshot-data.mjs    # Validates and generates app data
│   └── export_mobile_snapshots.py    # Read-only warehouse export helper
├── .env.example                      # Environment-variable template
├── .gitignore                        # Local/generated file exclusions
├── app.config.ts                     # Expo application configuration
├── expo-env.d.ts                     # Expo TypeScript declarations
├── package.json                      # Scripts and dependencies
├── package-lock.json                 # Locked dependency versions
├── tsconfig.json                     # Strict TypeScript configuration
└── PROJECT_HANDOFF.md                # This document
```

## Architecture conventions

- Files in `app/` should primarily define routes and navigation behavior.
- Business screens, components, hooks, API functions, stores, schemas, and types belong under `src/features/<feature>`.
- Components used by several features belong under `src/shared/components`.
- Cross-feature domain contracts belong under `src/types`.
- `src/theme/tokens.ts` is the design-system source of truth.
- UI code should call feature API/query functions rather than importing mock arrays directly. The tire-size option hook is the current exception because it synchronously derives valid cascading selections.
- The real API can replace `mockApi` while preserving the current consumer-facing function signatures.

## Setup and commands

```bash
cd /home/jerico/Desktop/gulong-mobile/gulong-mobile-scaffold-v2/gulong-mobile
npm install
npm start
```

Other commands:

```bash
npm run android
npm run ios
npm run web
npm run typecheck
npm run data:snapshot
```

## Validation performed

- `npm run typecheck` passes.
- Expo dependency compatibility check passes for SDK 57.
- A production-style Expo web export completes successfully.
- The generator produced 3,133 valid products and rejected 161 invalid/incomplete products.
- The temporary branch fixture contains 11 branches; the warehouse did not provide a reliable branch export.
- Empty scaffold routes and source placeholders were removed so the tree reflects implemented code only.

## Known follow-ups

- Confirm the Call tab hotline. It currently uses `+63 2 8990 0461` from the supplied design package.
- Confirm that production-derived prices, phone numbers, addresses, and coordinates are approved for the target demo or release.
- Add Zustand persistence with AsyncStorage if the guest cart should survive app restarts.
- Replace the cart checkout alert with authentication interception and the real checkout route.
- Replace the chat placeholder with the selected customer-support integration.
- Add authentication, checkout, order history, profile, and support features as complete vertical slices when their requirements are ready.
- Replace the snapshot adapter and `mockApi` with the secured backend client when mobile endpoints are ready.
- Add automated tests for search filtering, cascading tire sizes, and route-level user flows.
- Review npm's remaining moderate transitive advisories during Expo SDK upgrades. Do not run `npm audit fix --force` blindly because npm previously attempted to downgrade Expo to an incompatible SDK.

## Source-package cleanup

The design from `/home/jerico/Desktop/gulong-mobile/home-screen` has been migrated into this project. The original directory was intentionally left unchanged and can be deleted after the migrated screens have been visually reviewed.

The cart package from `/home/jerico/Desktop/gulong-mobile/gulong-mobile-scaffold-v2/gulong-cart-package` has also been integrated. Its source directory was left unchanged and can be deleted after reviewing the cart flow.
