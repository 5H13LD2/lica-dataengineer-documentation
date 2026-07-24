// src/types/domain.types.ts
// Domain models for the Gulong.ph mobile app prototype.
// Shapes are informed by the actual backend schema (product, product_price, branch tables)
// so the swap from mock -> real API needs minimal remapping.

export interface TireSize {
  sectionWidth: number;
  aspectRatio: number;
  rimDiameter: number;
  /** Human-readable size, e.g. "205/55 R16" */
  display: string;
  isLightTruck: boolean;
}

export interface ProductPrice {
  srp: number;
  /** Null when no active promo */
  promo: number | null;
  currency: 'PHP';
}

export interface Product {
  id: string;
  sku: string;
  brand: string;
  name: string;
  displayName: string;
  description?: string | null;
  category?: string | null;
  imageUrl?: string | null;
  tireSize: TireSize;
  loadIndex: string | null;
  speedRating: string | null;
  price: ProductPrice;
  /** Null when the snapshot has no reliable inventory feed. */
  stock: number | null;
  /** Null means availability must be confirmed by the production API. */
  inStock: boolean | null;
}

export interface Branch {
  id: string;
  name: string;
  address: string;
  area: string;
  phone: string;
  coordinates: { latitude: number; longitude: number };
  services: string[];
  /** Minimum days before an installation appointment can be booked */
  leadDays: number;
}

export interface AppointmentSlot {
  id: string;
  branchId: string;
  /** ISO date, e.g. "2026-07-18" */
  date: string;
  /** 24h time, e.g. "09:00" */
  time: string;
  available: boolean;
}

export type OrderStatus =
  | 'pending'
  | 'confirmed'
  | 'ready_for_installation'
  | 'completed'
  | 'cancelled';

export interface OrderItem {
  productId: string;
  displayName: string;
  quantity: number;
  unitPrice: number;
}

export interface Order {
  id: string;
  orderNumber: string;
  status: OrderStatus;
  items: OrderItem[];
  branchId: string;
  appointmentDate: string | null;
  totalAmount: number;
  createdAt: string;
}
