import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { colors, radii, spacing, typography } from '@/theme/tokens';
import type { Product } from '@/types/domain.types';
import { useCartStore } from '@/features/cart/store/cart.store';

const peso = (value: number) => `₱${value.toLocaleString('en-PH', { minimumFractionDigits: 2 })}`;

export function ProductCard({ product }: { product: Product }) {
  const sellingPrice = product.price.promo ?? product.price.srp;
  const addItem = useCartStore((state) => state.addItem);
  return <Pressable style={styles.card} onPress={() => router.push({ pathname: '/product/[id]', params: { id: product.id } })}>
    <View style={styles.top}><Text style={styles.brand}>{product.brand.toUpperCase()}</Text><View style={styles.chip}><Text style={styles.chipText}>{product.tireSize.display}</Text></View></View>
    <Text style={styles.name}>{product.name}</Text>
    <View style={styles.priceRow}><Text style={styles.price}>{peso(sellingPrice)}</Text>{product.price.promo !== null && <Text style={styles.srp}>{peso(product.price.srp)}</Text>}</View>
    <View style={styles.bottom}><Text style={styles.stock}>{product.inStock === null ? 'Availability to confirm' : product.inStock ? `${product.stock} in stock` : 'Out of stock'}</Text><Pressable accessibilityLabel={`Add ${product.displayName} to cart`} disabled={product.inStock === false} onPress={() => addItem(product)} style={[styles.add, product.inStock === false && styles.disabled]}><Ionicons name="cart-outline" size={14} color={colors.primary} /><Text style={styles.addText}>Add to Cart</Text></Pressable></View>
  </Pressable>;
}

const styles = StyleSheet.create({
  card:{backgroundColor:colors.surface,borderWidth:1,borderColor:colors.border,borderRadius:radii.md,padding:spacing.lg}, top:{flexDirection:'row',justifyContent:'space-between',alignItems:'center',marginBottom:spacing.xs}, brand:{fontSize:11,fontWeight:'800',color:colors.primary,letterSpacing:.8}, chip:{backgroundColor:colors.surfaceTint,borderRadius:radii.pill,paddingHorizontal:spacing.md,paddingVertical:3}, chipText:{fontSize:12,fontWeight:'700',color:colors.textPrimary}, name:{...typography.h2,marginBottom:spacing.sm}, priceRow:{flexDirection:'row',alignItems:'baseline',gap:spacing.sm,marginBottom:spacing.sm}, price:{...typography.price}, srp:{fontSize:13,color:colors.strikethrough,textDecorationLine:'line-through'}, bottom:{flexDirection:'row',justifyContent:'space-between',alignItems:'center'}, stock:{fontSize:12,fontWeight:'700',color:colors.success}, add:{flexDirection:'row',alignItems:'center',gap:4,borderWidth:1,borderColor:colors.primary,borderRadius:radii.sm,paddingHorizontal:spacing.md,paddingVertical:6}, addText:{fontSize:12,fontWeight:'700',color:colors.primary},disabled:{opacity:.4},
});
