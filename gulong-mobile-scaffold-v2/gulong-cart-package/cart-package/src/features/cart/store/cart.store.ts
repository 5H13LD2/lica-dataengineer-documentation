// src/features/cart/store/cart.store.ts
// Guest-first local cart. In-memory for the prototype (survives navigation,
// resets on app restart). To persist later: wrap with zustand/middleware
// persist + @react-native-async-storage/async-storage — no API changes needed.

import { create } from 'zustand';
import type { Product } from '@/types/domain.types';

export interface CartItem {
  productId: string;
  brand: string;
  displayName: string;
  sizeDisplay: string;
  unitPrice: number;
  srp: number;
  quantity: number;
  maxStock: number;
}

interface CartState {
  items: CartItem[];
  addItem: (product: Product, quantity?: number) => void;
  removeItem: (productId: string) => void;
  setQuantity: (productId: string, quantity: number) => void;
  clear: () => void;
}

export const useCartStore = create<CartState>((set) => ({
  items: [],

  addItem: (product, quantity = 1) =>
    set((state) => {
      const existing = state.items.find((i) => i.productId === product.id);
      if (existing) {
        return {
          items: state.items.map((i) =>
            i.productId === product.id
              ? { ...i, quantity: Math.min(i.quantity + quantity, i.maxStock) }
              : i,
          ),
        };
      }
      const unitPrice = product.price.promo ?? product.price.srp;
      return {
        items: [
          ...state.items,
          {
            productId: product.id,
            brand: product.brand,
            displayName: product.displayName,
            sizeDisplay: product.tireSize.display,
            unitPrice,
            srp: product.price.srp,
            quantity: Math.min(quantity, product.stock),
            maxStock: product.stock,
          },
        ],
      };
    }),

  removeItem: (productId) =>
    set((state) => ({ items: state.items.filter((i) => i.productId !== productId) })),

  setQuantity: (productId, quantity) =>
    set((state) => ({
      items:
        quantity <= 0
          ? state.items.filter((i) => i.productId !== productId)
          : state.items.map((i) =>
              i.productId === productId
                ? { ...i, quantity: Math.min(quantity, i.maxStock) }
                : i,
            ),
    })),

  clear: () => set({ items: [] }),
}));

// ---- Derived selectors (use these in components to avoid re-render storms) ----

export const selectCartCount = (s: CartState) =>
  s.items.reduce((sum, i) => sum + i.quantity, 0);

export const selectCartSubtotal = (s: CartState) =>
  s.items.reduce((sum, i) => sum + i.unitPrice * i.quantity, 0);

export const selectCartSavings = (s: CartState) =>
  s.items.reduce((sum, i) => sum + (i.srp - i.unitPrice) * i.quantity, 0);
