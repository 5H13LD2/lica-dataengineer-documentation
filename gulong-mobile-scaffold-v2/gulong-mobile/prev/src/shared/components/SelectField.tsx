import { Ionicons } from '@expo/vector-icons';
import { useState } from 'react';
import { FlatList, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { colors, radii, spacing, typography } from '@/theme/tokens';

interface SelectFieldProps { placeholder: string; value: string | null; options: string[]; onSelect: (value: string) => void; disabled?: boolean; }

export function SelectField({ placeholder, value, options, onSelect, disabled = false }: SelectFieldProps) {
  const [open, setOpen] = useState(false);
  return <>
    <Pressable accessibilityLabel={placeholder} accessibilityRole="button" disabled={disabled} onPress={() => setOpen(true)} style={[styles.field, disabled && styles.fieldDisabled]}>
      <Text style={value ? styles.value : styles.placeholder}>{value ?? placeholder}</Text>
      <Ionicons name="chevron-down" size={18} color={colors.textSecondary} />
    </Pressable>
    <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
      <View style={styles.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={() => setOpen(false)} accessibilityLabel="Close picker" />
        <View style={styles.sheet}>
          <View style={styles.sheetHandle} /><Text style={styles.sheetTitle}>{placeholder}</Text>
          <FlatList data={options} keyExtractor={(item) => item} renderItem={({ item }) => <Pressable style={styles.option} onPress={() => { onSelect(item); setOpen(false); }}><Text style={[styles.optionText, item === value && styles.optionTextActive]}>{item}</Text>{item === value && <Ionicons name="checkmark" size={18} color={colors.primary} />}</Pressable>} />
        </View>
      </View>
    </Modal>
  </>;
}

const styles = StyleSheet.create({
  field: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.md, paddingHorizontal: spacing.lg, paddingVertical: 14, marginBottom: spacing.md },
  fieldDisabled: { opacity: 0.5 }, placeholder: { ...typography.body }, value: { ...typography.label }, backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.35)', justifyContent: 'flex-end' },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: radii.lg, borderTopRightRadius: radii.lg, paddingHorizontal: spacing.lg, paddingBottom: spacing.xl, maxHeight: '60%' },
  sheetHandle: { alignSelf: 'center', width: 40, height: 4, borderRadius: radii.pill, backgroundColor: colors.border, marginVertical: spacing.md }, sheetTitle: { ...typography.h2, marginBottom: spacing.md },
  option: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 14, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border }, optionText: { ...typography.label }, optionTextActive: { color: colors.primary },
});
