import { Ionicons } from '@expo/vector-icons';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, typography } from '@/theme/tokens';
export function ChatScreen(){return <SafeAreaView style={styles.safe} edges={['top']}><View style={styles.center}><View style={styles.icon}><Ionicons name="chatbubble-ellipses" size={36} color={colors.primary}/></View><Text style={[typography.h2,styles.title]}>Chat with our tire experts</Text><Text style={[typography.body,styles.sub]}>Our customer service team can recommend the right tires and help book installation. Chat is coming in the next build.</Text></View></SafeAreaView>}
const styles=StyleSheet.create({safe:{flex:1,backgroundColor:colors.background},center:{flex:1,alignItems:'center',justifyContent:'center',padding:spacing.xl},icon:{width:72,height:72,borderRadius:36,backgroundColor:colors.surfaceTint,alignItems:'center',justifyContent:'center'},title:{marginTop:spacing.lg},sub:{textAlign:'center',marginTop:spacing.sm,lineHeight:20}});
