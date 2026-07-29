import { queryOptions } from '@tanstack/react-query';

import { mockApi } from '@/services/api/mockApi';

export const branchesQuery = queryOptions({
  queryKey: ['branches'],
  queryFn: () => mockApi.getBranches(),
});
