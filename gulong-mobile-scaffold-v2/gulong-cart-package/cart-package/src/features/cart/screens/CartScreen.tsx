// src/features/cart/screens/CartScreen.tsx
// Guest cart: line items with quantity steppers, tire-set quick picks (2/4),
// order summary with savings, and a checkout CTA (auth gate arrives with the
// checkout flow next sprint).

import React from 'react';
import {
  Alert,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import {
  selectCartCount,
  selectCartSavings,
  selectCartSubtotal,
  useCartStore,
  type CartItem,
} from '@/features/cart/store/cart.store';
import { colors, radii, spacing, typography } from '@/theme/tokens';

const peso = (n: number) =>
  '₱' + n.toLocaleString('en-PH', { minimumFractionDigits: 2 });

function QuantityStepper({ item }: { item: CartItem }) {
  const setQuantity = useCartStore((s) => s.setQuantity);
  return (
    <View style={styles.stepperRow}>
      <View style={styles.stepper}>
        <Pressable
          style={styles.stepBtn}
          onPress={() => setQuantity(item.productId, item.quantity - 1)}
          hitSlop={6}
        >
          <Ionicons name="remove" size={16} color={colors.textPrimary} />
        </Pressable>
        <Text style={styles.stepValue}>{item.quantity}</Text>
        <Pressable
          style={[styles.stepBtn, item.quantity >= item.maxStock && styles.stepBtnDisabled]}
          onPress={() => setQuantity(item.productId, item.quantity + 1)}
          hitSlop={6}
        >
          <Ionicons name="add" size={16} color={colors.textPrimary} />
        </Pressable>
      </View>
      {/* Tires are bought in pairs/sets — quick picks reduce taps */}
      {[2, 4].map((n) => (
        <Pressable
          key={n}
          style={[styles.setChip, item.quantity === n && styles.setChipActive]}
          onPress={() => setQuantity(item.productId, n)}
        >
          <Text
            style={[styles.setChipText, item.quantity === n && styles.setChipTextActive]}
          >
            Set of {n}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

function CartLine({ item }: { item: CartItem }) {
  const removeItem = useCartStore((s) => s.removeItem);
  return (
    <View style={styles.card}>
      <View style={styles.cardTop}>
        <Text style={styles.brand}>{item.brand.toUpperCase()}</Text>
        <Pressable onPress={() => removeItem(item.productId)} hitSlop={8}>
          <Ionicons name="trash-outline" size={18} color={colors.textSecondary} />
        </Pressable>
      </View>
      <Text style={styles.name}>{item.displayName}</Text>
      <Text style={styles.size}>{item.sizeDisplay}</Text>
      <View style={styles.lineBottom}>
        <QuantityStepper item={item} />
        <Text style={styles.linePrice}>{peso(item.unitPrice * item.quantity)}</Text>
      </View>
    </View>
  );
}

export default function CartScreen() {
  const items = useCartStore((s) => s.items);
  const count = useCartStore(selectCartCount);
  const subtotal = useCartStore(selectCartSubtotal);
  const savings = useCartStore(selectCartSavings);

  const onCheckout = () => {
    // Auth interception point: useRequireAuth() gates this when the
    // checkout flow lands next sprint.
    Alert.alert(
      'Checkout',
      'Checkout with installation booking is coming in the next build.',
    );
  };

  if (items.length === 0) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <Header count={0} />
        <View style={styles.empty}>
          <View style={styles.emptyIcon}>
            <Ionicons name="cart-outline" size={36} color={colors.primary} />
          </View>
          <Text style={[typography.h2, { marginTop: spacing.lg }]}>
            Your cart is empty
          </Text>
          <Text style={[typography.body, styles.emptySub]}>
            Find the right tires for your vehicle and they'll show up here.
          </Text>
          <Pressable style={styles.cta} onPress={() => router.push('/(tabs)')}>
            <Text style={styles.ctaText}>Search for Tires</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <Header count={count} />
      <FlatList
        data={items}
        keyExtractor={(i) => i.productId}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => <CartLine item={item} />}
      />
      <View style={styles.summary}>
        {savings > 0 && (
          <View style={styles.summaryRow}>
            <Text style={styles.savingsLabel}>You're saving</Text>
            <Text style={styles.savingsValue}>{peso(savings)}</Text>
          </View>
        )}
        <View style={styles.summaryRow}>
          <Text style={typography.label}>Subtotal ({count} tires)</Text>
          <Text style={styles.subtotal}>{peso(subtotal)}</Text>
        </View>
        <Text style={typography.caption}>
          Free installation included · Final total at checkout
        </Text>
        <Pressable style={styles.cta} onPress={onCheckout}>
          <Text style={styles.ctaText}>Proceed to Checkout</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

function Header({ count }: { count: number }) {
  return (
    <View style={styles.header}>
      <Pressable onPress={() => router.back()} hitSlop={8}>
        <Ionicons name="arrow-back" size={24} color={colors.textPrimary} />
      </Pressable>
      <Text style={typography.h2}>
        My Cart{count > 0 ? ` (${count})` : ''}
      </Text>
      <View style={{ width: 24 }} />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  list: { padding: spacing.lg, gap: spacing.md },
  card: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    padding: spacing.lg,
  },
  cardTop: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  brand: {
    fontSize: 11,
    fontWeight: '800',
    color: colors.primary,
    letterSpacing: 0.8,
  },
  name: { ...typography.label, marginTop: 2 },
  size: { ...typography.caption, marginTop: 2, marginBottom: spacing.md },
  lineBottom: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  stepperRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  stepper: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
  },
  stepBtn: { paddingHorizontal: spacing.sm, paddingVertical: 6 },
  stepBtnDisabled: { opacity: 0.35 },
  stepValue: {
    minWidth: 28,
    textAlign: 'center',
    fontSize: 14,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  setChip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.md,
    paddingVertical: 5,
  },
  setChipActive: {
    borderColor: colors.primary,
    backgroundColor: colors.surfaceTint,
  },
  setChipText: { fontSize: 11, fontWeight: '700', color: colors.textSecondary },
  setChipTextActive: { color: colors.primary },
  linePrice: { fontSize: 15, fontWeight: '800', color: colors.textPrimary },
  summary: {
    borderTopWidth: 1,
    borderTopColor: colors.border,
    padding: spacing.lg,
    gap: spacing.sm,
    backgroundColor: colors.surface,
  },
  summaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  savingsLabel: { fontSize: 13, fontWeight: '600', color: colors.success },
  savingsValue: { fontSize: 13, fontWeight: '800', color: colors.success },
  subtotal: { ...typography.price },
  cta: {
    backgroundColor: colors.primary,
    borderRadius: radii.md,
    alignItems: 'center',
    paddingVertical: 16,
    marginTop: spacing.sm,
  },
  ctaText: { fontSize: 16, fontWeight: '800', color: colors.textOnPrimary },
  empty: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.xl,
  },
  emptyIcon: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.surfaceTint,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptySub: {
    textAlign: 'center',
    marginTop: spacing.sm,
    marginBottom: spacing.lg,
  },
});
