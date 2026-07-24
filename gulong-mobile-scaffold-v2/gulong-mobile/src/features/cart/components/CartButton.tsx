import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { selectCartCount, useCartStore } from '@/features/cart/store/cart.store';
import { colors } from '@/theme/tokens';

/** Header action shared by screens that need live cart-count feedback. */
export function CartButton() {
  const count = useCartStore(selectCartCount);
  return (
    <Pressable onPress={() => router.push('/cart')} hitSlop={8} accessibilityRole="button" accessibilityLabel={`Cart, ${count} items`}>
      <View>
        <Ionicons name="cart" size={24} color={colors.primary} />
        {count > 0 && <View style={styles.badge}><Text style={styles.badgeText}>{count > 99 ? '99+' : count}</Text></View>}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  badge: { position: 'absolute', top: -6, right: -8, minWidth: 16, height: 16, borderRadius: 8, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 3 },
  badgeText: { fontSize: 9, fontWeight: '800', color: colors.textOnPrimary },
});
