// src/services/api/mockApi.ts
// Simulated API layer. TanStack Query hooks call these functions exactly as they
// would call real endpoint functions — swap the implementation, keep the signatures.

import { catalogSnapshot } from '@/features/catalog/data/catalog.snapshot';
import { MOCK_BRANCHES } from '@/features/branches/api/branches.mock';
import type { Product, Branch, AppointmentSlot } from '@/types/domain.types';

/** Simulates network latency (250–600ms) so loading states are visible in the prototype. */
const delay = () => new Promise<void>((r) => setTimeout(r, 250 + Math.random() * 350));

export interface ProductSearchParams {
  sectionWidth?: number;
  aspectRatio?: number;
  rimDiameter?: number;
  brand?: string;
  query?: string;
}

export const mockApi = {
  async searchProducts(params: ProductSearchParams = {}): Promise<Product[]> {
    await delay();
    return catalogSnapshot.products.filter((p) => {
      if (params.sectionWidth && p.tireSize.sectionWidth !== params.sectionWidth) return false;
      if (params.aspectRatio && p.tireSize.aspectRatio !== params.aspectRatio) return false;
      if (params.rimDiameter && p.tireSize.rimDiameter !== params.rimDiameter) return false;
      if (params.brand && p.brand.toLowerCase() !== params.brand.toLowerCase()) return false;
      if (params.query) {
        const q = params.query.toLowerCase();
        if (!p.displayName.toLowerCase().includes(q) && !p.tireSize.display.toLowerCase().includes(q)) {
          return false;
        }
      }
      return true;
    });
  },

  async getProduct(id: string): Promise<Product> {
    await delay();
    const product = catalogSnapshot.products.find((p) => p.id === id);
    if (!product) throw new Error(`Product ${id} not found`);
    return product;
  },

  async getBrands(): Promise<string[]> {
    await delay();
    return [...new Set(catalogSnapshot.products.map((p) => p.brand))].sort();
  },

  async getBranches(): Promise<Branch[]> {
    await delay();
    return MOCK_BRANCHES;
  },

  async getAppointmentSlots(branchId: string, date: string): Promise<AppointmentSlot[]> {
    await delay();
    const times = ['09:00', '10:00', '11:00', '13:00', '14:00', '15:00', '16:00'];
    // Deterministic pseudo-availability so the UI is stable across renders
    return times.map((time, i) => ({
      id: `${branchId}-${date}-${time}`,
      branchId,
      date,
      time,
      available: (i + date.length + Number(branchId)) % 3 !== 0,
    }));
  },
};
