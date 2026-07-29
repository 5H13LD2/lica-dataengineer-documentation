import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ProductCard } from '@/features/catalog/components/ProductCard';
import { mockApi } from '@/services/api/mockApi';
import { colors, spacing, typography } from '@/theme/tokens';

export function SearchResultsScreen() {
  const params = useLocalSearchParams<{q?:string;width?:string;ratio?:string;rim?:string}>();
  const products = useQuery({queryKey:['products','search-results',params.q,params.width,params.ratio,params.rim],queryFn:()=>mockApi.searchProducts({query:params.q,sectionWidth:params.width?Number(params.width):undefined,aspectRatio:params.ratio?Number(params.ratio):undefined,rimDiameter:params.rim?Number(params.rim):undefined})});
  const title=params.q?`“${params.q}”`:`${params.width}/${params.ratio} R${params.rim}`;
  return <SafeAreaView style={styles.safe} edges={['top']}><View style={styles.header}><Pressable onPress={()=>router.back()} hitSlop={8}><Ionicons name="arrow-back" size={24} color={colors.textPrimary}/></Pressable><Text style={styles.title}>{title}</Text><View style={styles.spacer}/></View>{products.isPending?<ActivityIndicator style={styles.center} color={colors.primary} size="large"/>:<FlatList data={products.data??[]} keyExtractor={(item)=>item.id} renderItem={({item})=><ProductCard product={item}/>} contentContainerStyle={styles.list} ListHeaderComponent={<Text style={styles.count}>{products.data?.length??0} tires found</Text>} ListEmptyComponent={<View style={styles.empty}><Ionicons name="search" size={40} color={colors.border}/><Text style={[typography.body,styles.emptyText]}>No tires match this search yet.{`\n`}Try another size or brand.</Text></View>}/>}</SafeAreaView>;
}
const styles=StyleSheet.create({safe:{flex:1,backgroundColor:colors.background},header:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',padding:spacing.lg,borderBottomWidth:1,borderBottomColor:colors.border},title:{...typography.h2},spacer:{width:24},center:{flex:1},list:{padding:spacing.lg,gap:spacing.md},count:{...typography.caption,marginBottom:spacing.xs},empty:{alignItems:'center',padding:spacing.xl},emptyText:{marginTop:spacing.md,textAlign:'center'}});
