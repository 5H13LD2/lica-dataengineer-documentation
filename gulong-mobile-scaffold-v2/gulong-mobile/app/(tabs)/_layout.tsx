import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';
import { Linking } from 'react-native';
import { colors } from '@/theme/tokens';

export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ headerShown:false,tabBarActiveTintColor:colors.primary,tabBarInactiveTintColor:colors.textSecondary,tabBarLabelStyle:{fontSize:11,fontWeight:'600'},tabBarStyle:{borderTopColor:colors.border,backgroundColor:colors.background} }}>
      <Tabs.Screen name="index" options={{ title:'Home',tabBarIcon:({color,size})=><Ionicons name="home-outline" size={size} color={color}/> }} />
      <Tabs.Screen name="shop" options={{ title:'Shop Tires',tabBarIcon:({color,size})=><Ionicons name="storefront-outline" size={size} color={color}/> }} />
      <Tabs.Screen name="chat" options={{ title:'Chat',tabBarIcon:({color,size})=><Ionicons name="chatbubble-ellipses-outline" size={size} color={color}/> }} />
      <Tabs.Screen name="call" options={{ title:'Call',tabBarIcon:({color,size})=><Ionicons name="call-outline" size={size} color={color}/> }} listeners={{tabPress:(event)=>{event.preventDefault();void Linking.openURL('tel:+63289900461')}}} />
    </Tabs>
  );
}
