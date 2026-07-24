import { Ionicons, MaterialCommunityIcons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useTireSizeOptions } from '@/features/search/hooks/useTireSizeOptions';
import { CartButton } from '@/features/cart/components/CartButton';
import { SelectField } from '@/shared/components/SelectField';
import { colors, radii, spacing, typography } from '@/theme/tokens';

type SearchMode = 'size' | 'car';

export function HomeScreen() {
  const [mode, setMode] = useState<SearchMode>('size');
  const [query, setQuery] = useState('');
  const size = useTireSizeOptions();
  const submitTextSearch = () => query.trim() && router.push({ pathname: '/search-results', params: { q: query.trim() } });
  const submitSizeSearch = () => size.isComplete && router.push({ pathname: '/search-results', params: { width: size.width!, ratio: size.ratio!, rim: size.rim! } });

  return <SafeAreaView style={styles.safe} edges={['top']}>
    <View style={styles.header}>
      <Pressable hitSlop={8} accessibilityLabel="Menu"><Ionicons name="menu" size={26} color={colors.textPrimary} /></Pressable>
      <Text style={styles.logo}>gulong.ph</Text>
      <CartButton />
    </View>
    <View style={styles.searchBar}>
      <TextInput style={styles.searchInput} placeholder="Search tires, brands, sizes…" placeholderTextColor={colors.textSecondary} value={query} onChangeText={setQuery} onSubmitEditing={submitTextSearch} returnKeyType="search" />
      <Pressable onPress={submitTextSearch} hitSlop={8} accessibilityLabel="Search"><Ionicons name="search" size={20} color={colors.textSecondary} /></Pressable>
    </View>
    <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator={false}>
      <View style={styles.hero}>
        <View style={styles.ratingRow}><View style={styles.stars}>{[1,2,3,4,5].map((i) => <Ionicons key={i} name="star" size={16} color={colors.rating} />)}</View><Text style={styles.ratingScore}>4.8</Text></View>
        <View style={styles.verifiedRow}><Text style={typography.caption}>Rated by 1,470 verified customers</Text><Ionicons name="checkmark-circle" size={14} color={colors.textSecondary} style={styles.verifiedIcon} /></View>
        <Text style={styles.h1}>Buy Tires Online{`\n`}in the Philippines</Text>
        <Text style={styles.heroSub}>Search by tire size or car model to find quality tires with free installation across the Philippines.</Text>
        <View style={styles.modeRow}>
          <ModeCard active={mode === 'size'} label="Search By Tire Size" onPress={() => setMode('size')} icon={<MaterialCommunityIcons name="tire" size={18} color={mode === 'size' ? colors.primary : colors.textPrimary} />} />
          <ModeCard active={mode === 'car'} label="Search By Car Model" onPress={() => setMode('car')} icon={<Ionicons name="car-sport" size={18} color={mode === 'car' ? colors.primary : colors.textPrimary} />} />
        </View>
      </View>
      {mode === 'size' ? <View style={styles.formSection}>
        <View style={styles.sizeExplainer}><View style={styles.sizeLabels}><Text style={styles.sizeLabel}>Width</Text><Text style={styles.sizeLabel}>Aspect{`\n`}Ratio</Text><Text style={styles.sizeLabel}>Rim{`\n`}Diameter</Text></View><View style={styles.sizeSample}><Text style={styles.sizeSampleText}>185 / 60 R15</Text></View><Text style={styles.sizeHint}>Find these numbers on your tire&apos;s sidewall</Text></View>
        <SelectField placeholder="Width" value={size.width} options={size.widthOptions} onSelect={size.selectWidth} />
        <SelectField placeholder="Aspect Ratio" value={size.ratio} options={size.ratioOptions} onSelect={size.selectRatio} disabled={!size.width} />
        <SelectField placeholder="Rim Diameter" value={size.rim} options={size.rimOptions} onSelect={size.selectRim} disabled={!size.ratio} />
        <Pressable style={[styles.cta, !size.isComplete && styles.ctaDisabled]} disabled={!size.isComplete} onPress={submitSizeSearch}><Text style={styles.ctaText}>Search for Tires</Text></Pressable>
      </View> : <View style={styles.formSection}><View style={styles.comingSoon}><Ionicons name="construct-outline" size={20} color={colors.textSecondary} /><Text style={[typography.body, styles.flex]}>Search by car model is coming in the next build. Use tire size search for now.</Text></View></View>}
    </ScrollView>
  </SafeAreaView>;
}

function ModeCard({ active, label, icon, onPress }: { active: boolean; label: string; icon: React.ReactNode; onPress: () => void }) {
  return <Pressable style={[styles.modeCard, active && styles.modeCardActive]} onPress={onPress}>{icon}<Text style={[styles.modeText, active && styles.modeTextActive]}>{label}</Text></Pressable>;
}

const styles = StyleSheet.create({
  safe:{flex:1,backgroundColor:colors.background}, header:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',paddingHorizontal:spacing.lg,paddingVertical:spacing.md}, logo:{fontSize:24,fontWeight:'800',color:colors.primary,letterSpacing:-0.5},
  searchBar:{flexDirection:'row',alignItems:'center',marginHorizontal:spacing.lg,marginBottom:spacing.md,paddingHorizontal:spacing.lg,borderWidth:1,borderColor:colors.border,borderRadius:radii.md}, searchInput:{flex:1,paddingVertical:12,fontSize:14,color:colors.textPrimary}, scroll:{paddingBottom:spacing.xxl},
  hero:{backgroundColor:colors.surfaceTint,paddingHorizontal:spacing.lg,paddingVertical:spacing.xl}, ratingRow:{flexDirection:'row',alignItems:'center',justifyContent:'center',gap:spacing.sm}, stars:{flexDirection:'row',gap:2}, ratingScore:{fontSize:15,fontWeight:'700',color:colors.rating}, verifiedRow:{flexDirection:'row',alignItems:'center',justifyContent:'center',marginTop:spacing.xs,marginBottom:spacing.lg}, verifiedIcon:{marginLeft:4},
  h1:{...typography.h1,textAlign:'center',lineHeight:32}, heroSub:{...typography.body,textAlign:'center',marginTop:spacing.sm,marginBottom:spacing.lg,lineHeight:20}, modeRow:{flexDirection:'row',gap:spacing.md}, modeCard:{flex:1,flexDirection:'row',alignItems:'center',justifyContent:'center',gap:spacing.sm,backgroundColor:colors.surface,borderWidth:1,borderColor:colors.border,borderRadius:radii.md,paddingVertical:14,paddingHorizontal:spacing.sm}, modeCardActive:{borderColor:colors.primary,backgroundColor:colors.surfaceTint}, modeText:{fontSize:13,fontWeight:'700',color:colors.textPrimary}, modeTextActive:{color:colors.primary},
  formSection:{paddingHorizontal:spacing.lg,paddingTop:spacing.lg}, sizeExplainer:{alignItems:'center',marginBottom:spacing.lg}, sizeLabels:{flexDirection:'row',gap:spacing.xl,marginBottom:spacing.sm}, sizeLabel:{fontSize:13,fontWeight:'800',color:colors.primary,textAlign:'center'}, sizeSample:{backgroundColor:colors.textPrimary,borderRadius:radii.pill,paddingHorizontal:spacing.xl,paddingVertical:spacing.sm}, sizeSampleText:{fontSize:22,fontWeight:'800',color:'#FF4D4D',letterSpacing:2}, sizeHint:{...typography.caption,marginTop:spacing.sm}, cta:{backgroundColor:colors.primary,borderRadius:radii.md,alignItems:'center',paddingVertical:16,marginTop:spacing.sm}, ctaDisabled:{opacity:.45}, ctaText:{fontSize:16,fontWeight:'800',color:colors.textOnPrimary}, comingSoon:{flexDirection:'row',gap:spacing.md,alignItems:'center',backgroundColor:colors.surfaceTint,borderRadius:radii.md,padding:spacing.lg}, flex:{flex:1},
});
