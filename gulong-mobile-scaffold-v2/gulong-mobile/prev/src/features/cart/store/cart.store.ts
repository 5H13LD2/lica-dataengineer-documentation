import { create } from 'zustand';

import type { CartState } from '@/features/cart/types/cart.types';

/** Guest-first cart. Persistence can be added here without changing consumers. */
export const useCartStore = create<CartState>((set) => ({
  items: [],
  addItem: (product, requestedQuantity = 1) =>
    set((state) => {
      if (product.inStock === false || product.stock === 0 || requestedQuantity <= 0) return state;

      const existing = state.items.find((item) => item.productId === product.id);
      if (existing) {
        return {
          items: state.items.map((item) =>
            item.productId === product.id
              ? { ...item, quantity: Math.min(item.quantity + requestedQuantity, item.maxStock) }
              : item,
          ),
        };
      }

      return {
        items: [...state.items, {
          productId: product.id,
          brand: product.brand,
          displayName: product.displayName,
          sizeDisplay: product.tireSize.display,
          unitPrice: product.price.promo ?? product.price.srp,
          srp: product.price.srp,
          // The limit is cart UX only when inventory is absent; it is not a stock claim.
          quantity: Math.min(requestedQuantity, product.stock ?? 8),
          maxStock: product.stock ?? 8,
          availabilityEstimated: product.stock === null,
        }],
      };
    }),
  removeItem: (productId) => set((state) => ({ items: state.items.filter((item) => item.productId !== productId) })),
  setQuantity: (productId, quantity) => set((state) => ({
    items: quantity <= 0
      ? state.items.filter((item) => item.productId !== productId)
      : state.items.map((item) => item.productId === productId ? { ...item, quantity: Math.min(quantity, item.maxStock) } : item),
  })),
  clear: () => set({ items: [] }),
}));

// Selectors keep components subscribed only to the derived value they render.
export const selectCartCount = (state: CartState) => state.items.reduce((total, item) => total + item.quantity, 0);
export const selectCartSubtotal = (state: CartState) => state.items.reduce((total, item) => total + item.unitPrice * item.quantity, 0);
export const selectCartSavings = (state: CartState) => state.items.reduce((total, item) => total + (item.srp - item.unitPrice) * item.quantity, 0);
