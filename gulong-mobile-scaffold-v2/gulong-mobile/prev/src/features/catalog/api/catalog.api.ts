import { queryOptions } from '@tanstack/react-query';

import { mockApi, type ProductSearchParams } from '@/services/api/mockApi';

export const productKeys = {
  all: ['products'] as const,
  search: (params: ProductSearchParams) => [...productKeys.all, 'search', params] as const,
  detail: (id: string) => [...productKeys.all, 'detail', id] as const,
};

export const productsQuery = (params: ProductSearchParams = {}) =>
  queryOptions({ queryKey: productKeys.search(params), queryFn: () => mockApi.searchProducts(params) });

export const productQuery = (id: string) =>
  queryOptions({ queryKey: productKeys.detail(id), queryFn: () => mockApi.getProduct(id) });
