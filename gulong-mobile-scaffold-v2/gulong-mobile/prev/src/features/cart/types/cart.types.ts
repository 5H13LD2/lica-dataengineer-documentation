export interface CartItem {
  productId: string;
  brand: string;
  displayName: string;
  sizeDisplay: string;
  unitPrice: number;
  srp: number;
  quantity: number;
  maxStock: number;
  availabilityEstimated: boolean;
}

export interface CartState {
  items: CartItem[];
  addItem: (product: import('@/types/domain.types').Product, quantity?: number) => void;
  removeItem: (productId: string) => void;
  setQuantity: (productId: string, quantity: number) => void;
  clear: () => void;
}
