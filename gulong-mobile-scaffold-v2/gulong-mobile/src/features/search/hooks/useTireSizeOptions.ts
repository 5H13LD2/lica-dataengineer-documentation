import { useMemo, useState } from 'react';
import { catalogSnapshot } from '@/features/catalog/data/catalog.snapshot';
const numericSort = (a: string, b: string) => Number(a) - Number(b);
export function useTireSizeOptions() {
  const [width, setWidth] = useState<string | null>(null); const [ratio, setRatio] = useState<string | null>(null); const [rim, setRim] = useState<string | null>(null);
  const widthOptions = useMemo(() => [...new Set(catalogSnapshot.products.map((p) => String(p.tireSize.sectionWidth)))].sort(numericSort), []);
  const ratioOptions = useMemo(() => !width ? [] : [...new Set(catalogSnapshot.products.filter((p) => String(p.tireSize.sectionWidth) === width).map((p) => String(p.tireSize.aspectRatio)))].sort(numericSort), [width]);
  const rimOptions = useMemo(() => !width || !ratio ? [] : [...new Set(catalogSnapshot.products.filter((p) => String(p.tireSize.sectionWidth) === width && String(p.tireSize.aspectRatio) === ratio).map((p) => String(p.tireSize.rimDiameter)))].sort(numericSort), [ratio, width]);
  const selectWidth = (value: string) => { setWidth(value); setRatio(null); setRim(null); }; const selectRatio = (value: string) => { setRatio(value); setRim(null); };
  return { width, ratio, rim, widthOptions, ratioOptions, rimOptions, selectWidth, selectRatio, selectRim: setRim, isComplete: Boolean(width && ratio && rim) };
}
