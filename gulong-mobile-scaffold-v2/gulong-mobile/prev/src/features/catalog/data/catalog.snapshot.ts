import { SNAPSHOT_PRODUCTS } from '@/data/generated/products.snapshot';
import { SNAPSHOT_METADATA } from '@/data/generated/snapshot.metadata';

/** Temporary snapshot adapter. Replace this module with an API repository later. */
export const catalogSnapshot = {
  products: SNAPSHOT_PRODUCTS,
  metadata: SNAPSHOT_METADATA,
};
