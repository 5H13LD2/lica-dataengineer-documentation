import type { ExpoConfig } from 'expo/config';

const config: ExpoConfig = {
  name: 'Gulong.ph',
  slug: 'gulong-mobile',
  version: '0.1.0',
  orientation: 'portrait',
  scheme: 'gulong',
  userInterfaceStyle: 'automatic',
  plugins: ['expo-router'],
  experiments: { typedRoutes: true },
  web: { bundler: 'metro' },
};

export default config;
