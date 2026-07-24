import { useQuery } from '@tanstack/react-query';
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { productsQuery } from '@/features/catalog/api/catalog.api';
import { ProductCard } from '@/features/catalog/components/ProductCard';
import { colors, spacing, typography } from '@/theme/tokens';

export function CatalogScreen() {
  const products = useQuery(productsQuery());
  return <SafeAreaView style={styles.safe} edges={['top']}><View style={styles.header}><Text style={styles.title}>Shop Tires</Text><Text style={styles.sub}>Authentic products and current mock pricing</Text></View>{products.isPending ? <ActivityIndicator style={styles.loader} color={colors.primary} /> : <FlatList data={products.data ?? []} keyExtractor={(item) => item.id} renderItem={({item}) => <ProductCard product={item} />} contentContainerStyle={styles.list} />}</SafeAreaView>;
}
const styles = StyleSheet.create({safe:{flex:1,backgroundColor:colors.background},header:{padding:spacing.lg,borderBottomWidth:1,borderBottomColor:colors.border},title:{...typography.h1},sub:{...typography.body,marginTop:spacing.xs},list:{padding:spacing.lg,gap:spacing.md,paddingBottom:spacing.xxl},loader:{flex:1}});
