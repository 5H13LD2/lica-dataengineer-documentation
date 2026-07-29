export const colors = {
  primary: '#C00000', primaryPressed: '#9E0000', primarySoft: '#FDF3F1',
  background: '#FFFFFF', surface: '#FFFFFF', surfaceTint: '#FDF3F1',
  textPrimary: '#1E2532', textSecondary: '#667085', textOnPrimary: '#FFFFFF',
  border: '#E8E8EC', borderActive: '#F3C2BC', success: '#1B873F',
  rating: '#F5A623', strikethrough: '#98A2B3',
} as const;
export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const radii = { sm: 8, md: 12, lg: 16, pill: 999 } as const;
export const typography = {
  h1: { fontSize: 24, fontWeight: '800' as const, color: colors.textPrimary },
  h2: { fontSize: 18, fontWeight: '700' as const, color: colors.textPrimary },
  body: { fontSize: 14, fontWeight: '400' as const, color: colors.textSecondary },
  label: { fontSize: 14, fontWeight: '600' as const, color: colors.textPrimary },
  caption: { fontSize: 12, fontWeight: '500' as const, color: colors.textSecondary },
  price: { fontSize: 20, fontWeight: '800' as const, color: colors.textPrimary },
} as const;
