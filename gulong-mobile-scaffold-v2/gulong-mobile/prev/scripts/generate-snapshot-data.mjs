#!/usr/bin/env node

import { parse } from 'csv-parse/sync';
import { readFileSync, readdirSync, statSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { z } from 'zod';

const root = resolve(import.meta.dirname, '..');
const exportsRoot = join(root, 'exports');
const snapshotName = process.env.MOBILE_SNAPSHOT || readdirSync(exportsRoot)
  .filter((name) => name.startsWith('mobile_snapshot_') && statSync(join(exportsRoot, name)).isDirectory())
  .sort()
  .at(-1);

if (!snapshotName) throw new Error('No mobile_snapshot_* directory found under exports/.');
const snapshotDir = join(exportsRoot, snapshotName);
const outputDir = join(root, 'src', 'data', 'generated');

const readCsv = (name) => parse(readFileSync(join(snapshotDir, name), 'utf8'), {
  columns: true,
  bom: true,
  skip_empty_lines: true,
  trim: true,
});

const boolean = z.enum(['true', 'false']).transform((value) => value === 'true');
const optionalText = z.string().transform((value) => value || null);
const brandSchema = z.object({ brand_id: z.string().min(1), brand_name: z.string().min(1), is_active: boolean, updated_at: z.string() });
const productSchema = z.object({
  product_id: z.string().min(1), sku: z.string().min(1), brand_id: z.string().min(1),
  product_name: z.string().min(1), display_name: z.string().min(1), description: z.string(),
  category: z.string(), load_index: optionalText, speed_rating: optionalText,
  is_light_truck: boolean, image_url: optionalText, is_active: boolean, updated_at: z.string(),
});
const sizeSchema = z.object({
  product_id: z.string().min(1), section_width: z.coerce.number().int().positive(),
  aspect_ratio: z.coerce.number().int().positive(), rim_diameter: z.coerce.number().int().positive(),
  size_display: z.string().min(1), is_light_truck: boolean, updated_at: z.string(),
});
const priceSchema = z.object({
  product_id: z.string().min(1), srp: z.coerce.number().positive(),
  promo_price: z.string().transform((value) => value ? Number(value) : null), currency: z.literal('PHP'),
  promo_start_at: z.string(), promo_end_at: z.string(), is_current: boolean, updated_at: z.string(),
});

const parseRows = (name, schema) => {
  const valid = [];
  const invalid = [];
  for (const [index, row] of readCsv(name).entries()) {
    const result = schema.safeParse(row);
    if (result.success) valid.push(result.data);
    else invalid.push({ row: index + 2, id: row.product_id ?? row.brand_id ?? '', issues: result.error.issues.map((issue) => issue.message) });
  }
  return { valid, invalid };
};

const brands = parseRows('brands.csv', brandSchema);
const products = parseRows('products.csv', productSchema);
const sizes = parseRows('tire_sizes.csv', sizeSchema);
const prices = parseRows('product_prices.csv', priceSchema);
const brandById = new Map(brands.valid.filter((brand) => brand.is_active).map((brand) => [brand.brand_id, brand]));
const sizeByProduct = new Map(sizes.valid.map((size) => [size.product_id, size]));
const priceByProduct = new Map(prices.valid.filter((price) => price.is_current).map((price) => [price.product_id, price]));

const generated = [];
const rejectedJoins = [];
for (const product of products.valid) {
  const brand = brandById.get(product.brand_id);
  const size = sizeByProduct.get(product.product_id);
  const price = priceByProduct.get(product.product_id);
  if (!product.is_active || !brand || !size || !price || (price.promo_price !== null && price.promo_price >= price.srp)) {
    rejectedJoins.push(product.product_id);
    continue;
  }
  generated.push({
    id: product.product_id, sku: product.sku, brand: brand.brand_name, name: product.product_name,
    displayName: product.display_name, description: product.description || null,
    category: product.category || null, imageUrl: product.image_url,
    tireSize: { sectionWidth: size.section_width, aspectRatio: size.aspect_ratio, rimDiameter: size.rim_diameter, display: size.size_display, isLightTruck: size.is_light_truck },
    loadIndex: product.load_index, speedRating: product.speed_rating,
    price: { srp: price.srp, promo: price.promo_price, currency: 'PHP' },
    stock: null, inStock: null,
  });
}

const manifest = readCsv('export_manifest.csv');
const validation = readCsv('validation_report.csv');
const rejectedProductIds = new Set([
  ...products.invalid.map((row) => row.id),
  ...sizes.invalid.map((row) => row.id),
  ...prices.invalid.map((row) => row.id),
  ...rejectedJoins,
].filter(Boolean));
const sourceExportedAt = manifest.find((row) => row.file_name === 'products.csv')?.exported_at ?? null;
const metadata = {
  snapshot: snapshotName,
  generatedAt: sourceExportedAt,
  sourceExportedAt,
  sourceProductRows: products.valid.length + products.invalid.length,
  generatedProducts: generated.length,
  rejectedProducts: rejectedProductIds.size,
  validationErrors: validation.filter((row) => row.severity === 'error').length,
  validationWarnings: validation.filter((row) => row.severity === 'warning').length,
  inventoryAvailable: false,
};

mkdirSync(outputDir, { recursive: true });
writeFileSync(join(outputDir, 'products.snapshot.ts'), `// AUTO-GENERATED by npm run data:snapshot. Do not edit manually.\nimport type { Product } from '@/types/domain.types';\nexport const SNAPSHOT_PRODUCTS = ${JSON.stringify(generated)} as const satisfies readonly Product[];\n`);
writeFileSync(join(outputDir, 'snapshot.metadata.ts'), `// AUTO-GENERATED by npm run data:snapshot. Do not edit manually.\nexport const SNAPSHOT_METADATA = ${JSON.stringify(metadata, null, 2)} as const;\n`);
console.log(`Generated ${generated.length} products from ${snapshotName}; rejected ${metadata.rejectedProducts} invalid/incomplete products.`);
