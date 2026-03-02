import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.businesshero.app',
  appName: 'Business Hero',
  webDir: 'dist',

  server: {
    // For development, uncomment and set your local IP:
    // url: 'http://192.168.x.x:5173',
    androidScheme: 'https',
    iosScheme: 'https',
  },

  android: {
    allowMixedContent: true,
  },

  plugins: {
    SplashScreen: {
      launchShowDuration: 2000,
      launchAutoHide: true,
      backgroundColor: '#2563EB',
      showSpinner: false,
      androidSplashResourceName: 'splash',
      iosSplashResourceName: 'splash',
    },
    StatusBar: {
      style: 'LIGHT',
      backgroundColor: '#2563EB',
    },
    Keyboard: {
      resize: 'body',
      style: 'LIGHT',
      resizeOnFullScreen: true,
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
  },
};

export default config;
