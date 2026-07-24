# Cart Package — Integration Notes

## Files
- src/features/cart/store/cart.store.ts      — Zustand store + derived selectors
- src/features/cart/components/CartButton.tsx — header cart icon w/ badge
- src/features/cart/screens/CartScreen.tsx    — cart screen
- app/cart.tsx                                — thin route

## Wiring steps
1. Copy files preserving paths.
2. In HomeScreen's header, replace the static cart Ionicons with <CartButton />.
3. In ProductCard (and product details), wire Add to Cart:

   const addItem = useCartStore((s) => s.addItem);
   <Pressable onPress={() => addItem(product)}>...

   Optional UX nicety: addItem(product, 4) on a "Set of 4" button in
   product details — tires sell in sets.
4. "Proceed to Checkout" currently shows an Alert. When we build the
   checkout flow, that handler becomes the auth-interception point
   (useRequireAuth → login modal → resume to /checkout).

## Design decisions
- In-memory store (resets on app restart). To persist across restarts,
  wrap with zustand persist + AsyncStorage later — component code is
  unaffected because everything goes through the store API.
- Quantity is capped at maxStock captured at add time (mock-data honest).
- "Set of 2 / Set of 4" quick chips: tire-domain UX — most orders are
  pairs or full sets, so we cut 3 taps to 1.
- Selectors (selectCartCount etc.) are exported separately so components
  subscribe only to what they render.
