import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Alert, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { selectCartCount, selectCartSavings, selectCartSubtotal, useCartStore } from '@/features/cart/store/cart.store';
import type { CartItem } from '@/features/cart/types/cart.types';
import { colors, radii, spacing, typography } from '@/theme/tokens';

const peso = (value: number) => `₱${value.toLocaleString('en-PH', { minimumFractionDigits: 2 })}`;

function QuantityStepper({ item }: { item: CartItem }) {
  const setQuantity = useCartStore((state) => state.setQuantity);
  return (
    <View style={styles.stepperRow}>
      <View style={styles.stepper}>
        <Pressable accessibilityLabel="Decrease quantity" style={styles.stepButton} onPress={() => setQuantity(item.productId, item.quantity - 1)} hitSlop={6}>
          <Ionicons name="remove" size={16} color={colors.textPrimary} />
        </Pressable>
        <Text style={styles.stepValue}>{item.quantity}</Text>
        <Pressable accessibilityLabel="Increase quantity" disabled={item.quantity >= item.maxStock} style={[styles.stepButton, item.quantity >= item.maxStock && styles.disabled]} onPress={() => setQuantity(item.productId, item.quantity + 1)} hitSlop={6}>
          <Ionicons name="add" size={16} color={colors.textPrimary} />
        </Pressable>
      </View>
      {[2, 4].map((quantity) => {
        const unavailable = quantity > item.maxStock;
        return <Pressable key={quantity} disabled={unavailable} style={[styles.setChip, item.quantity === quantity && styles.setChipActive, unavailable && styles.disabled]} onPress={() => setQuantity(item.productId, quantity)}>
          <Text style={[styles.setChipText, item.quantity === quantity && styles.setChipTextActive]}>Set of {quantity}</Text>
        </Pressable>;
      })}
    </View>
  );
}

function CartLine({ item }: { item: CartItem }) {
  const removeItem = useCartStore((state) => state.removeItem);
  return (
    <View style={styles.card}>
      <View style={styles.cardTop}><Text style={styles.brand}>{item.brand.toUpperCase()}</Text><Pressable accessibilityLabel={`Remove ${item.displayName}`} onPress={() => removeItem(item.productId)} hitSlop={8}><Ionicons name="trash-outline" size={18} color={colors.textSecondary} /></Pressable></View>
      <Text style={styles.name}>{item.displayName}</Text><Text style={styles.size}>{item.sizeDisplay}{item.availabilityEstimated ? ' · Availability to confirm' : ''}</Text>
      <View style={styles.lineBottom}><QuantityStepper item={item} /><Text style={styles.linePrice}>{peso(item.unitPrice * item.quantity)}</Text></View>
    </View>
  );
}

export function CartScreen() {
  const items = useCartStore((state) => state.items);
  const count = useCartStore(selectCartCount);
  const subtotal = useCartStore(selectCartSubtotal);
  const savings = useCartStore(selectCartSavings);

  if (items.length === 0) return <SafeAreaView style={styles.safe} edges={['top']}><Header count={0} /><View style={styles.empty}><View style={styles.emptyIcon}><Ionicons name="cart-outline" size={36} color={colors.primary} /></View><Text style={[typography.h2, styles.emptyTitle]}>Your cart is empty</Text><Text style={[typography.body, styles.emptySub]}>Find the right tires for your vehicle and they&apos;ll show up here.</Text><Pressable style={styles.cta} onPress={() => router.replace('/(tabs)')}><Text style={styles.ctaText}>Search for Tires</Text></Pressable></View></SafeAreaView>;

  return <SafeAreaView style={styles.safe} edges={['top']}>
    <Header count={count} />
    <FlatList data={items} keyExtractor={(item) => item.productId} contentContainerStyle={styles.list} renderItem={({ item }) => <CartLine item={item} />} />
    <View style={styles.summary}>
      {savings > 0 && <View style={styles.summaryRow}><Text style={styles.savings}>You&apos;re saving</Text><Text style={styles.savings}>{peso(savings)}</Text></View>}
      <View style={styles.summaryRow}><Text style={typography.label}>Subtotal ({count} tires)</Text><Text style={styles.subtotal}>{peso(subtotal)}</Text></View>
      <Text style={typography.caption}>Free installation included · Final total at checkout</Text>
      <Pressable style={styles.cta} onPress={() => Alert.alert('Checkout', 'Checkout with installation booking is coming in the next build.')}><Text style={styles.ctaText}>Proceed to Checkout</Text></Pressable>
    </View>
  </SafeAreaView>;
}

function Header({ count }: { count: number }) { return <View style={styles.header}><Pressable accessibilityLabel="Go back" onPress={() => router.back()} hitSlop={8}><Ionicons name="arrow-back" size={24} color={colors.textPrimary} /></Pressable><Text style={typography.h2}>My Cart{count > 0 ? ` (${count})` : ''}</Text><View style={styles.headerSpacer} /></View>; }

const styles = StyleSheet.create({
  safe:{flex:1,backgroundColor:colors.background}, header:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',paddingHorizontal:spacing.lg,paddingVertical:spacing.md,borderBottomWidth:1,borderBottomColor:colors.border}, headerSpacer:{width:24}, list:{padding:spacing.lg,gap:spacing.md},
  card:{backgroundColor:colors.surface,borderWidth:1,borderColor:colors.border,borderRadius:radii.md,padding:spacing.lg}, cardTop:{flexDirection:'row',justifyContent:'space-between',alignItems:'center'}, brand:{fontSize:11,fontWeight:'800',color:colors.primary,letterSpacing:.8}, name:{...typography.label,marginTop:2}, size:{...typography.caption,marginTop:2,marginBottom:spacing.md}, lineBottom:{flexDirection:'row',justifyContent:'space-between',alignItems:'center'}, linePrice:{fontSize:15,fontWeight:'800',color:colors.textPrimary},
  stepperRow:{flexDirection:'row',alignItems:'center',gap:spacing.sm}, stepper:{flexDirection:'row',alignItems:'center',borderWidth:1,borderColor:colors.border,borderRadius:radii.sm}, stepButton:{paddingHorizontal:spacing.sm,paddingVertical:6}, stepValue:{minWidth:28,textAlign:'center',fontSize:14,fontWeight:'700',color:colors.textPrimary}, disabled:{opacity:.35}, setChip:{borderWidth:1,borderColor:colors.border,borderRadius:radii.pill,paddingHorizontal:spacing.md,paddingVertical:5}, setChipActive:{borderColor:colors.primary,backgroundColor:colors.surfaceTint}, setChipText:{fontSize:11,fontWeight:'700',color:colors.textSecondary}, setChipTextActive:{color:colors.primary},
  summary:{borderTopWidth:1,borderTopColor:colors.border,padding:spacing.lg,gap:spacing.sm,backgroundColor:colors.surface}, summaryRow:{flexDirection:'row',justifyContent:'space-between',alignItems:'center'}, savings:{fontSize:13,fontWeight:'800',color:colors.success}, subtotal:{...typography.price}, cta:{backgroundColor:colors.primary,borderRadius:radii.md,alignItems:'center',paddingVertical:16,marginTop:spacing.sm,paddingHorizontal:spacing.xl}, ctaText:{fontSize:16,fontWeight:'800',color:colors.textOnPrimary},
  empty:{flex:1,alignItems:'center',justifyContent:'center',padding:spacing.xl}, emptyIcon:{width:72,height:72,borderRadius:36,backgroundColor:colors.surfaceTint,alignItems:'center',justifyContent:'center'}, emptyTitle:{marginTop:spacing.lg}, emptySub:{textAlign:'center',marginTop:spacing.sm,marginBottom:spacing.lg},
});
