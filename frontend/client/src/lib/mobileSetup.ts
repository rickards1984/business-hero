import { Capacitor } from '@capacitor/core';
import { App } from '@capacitor/app';
import { StatusBar, Style } from '@capacitor/status-bar';
import { Keyboard } from '@capacitor/keyboard';
import { Browser } from '@capacitor/browser';

export const initMobileApp = async () => {
  if (!Capacitor.isNativePlatform()) return;

  try {
    await StatusBar.setStyle({ style: Style.Light });
    await StatusBar.setBackgroundColor({ color: '#2563EB' });
  } catch (_) {
    // StatusBar not available on this platform
  }

  App.addListener('backButton', ({ canGoBack }) => {
    if (canGoBack) {
      window.history.back();
    } else {
      App.exitApp();
    }
  });

  App.addListener('appStateChange', ({ isActive }) => {
    if (isActive) {
      console.log('[BusinessHero] App resumed');
    }
  });

  try {
    Keyboard.addListener('keyboardWillShow', (info) => {
      document.body.style.setProperty('--keyboard-height', `${info.keyboardHeight}px`);
      document.body.classList.add('keyboard-visible');
    });

    Keyboard.addListener('keyboardWillHide', () => {
      document.body.style.setProperty('--keyboard-height', '0px');
      document.body.classList.remove('keyboard-visible');
    });
  } catch (_) {
    // Keyboard plugin not available on this platform
  }
};

/**
 * Open a URL using the system browser on native platforms,
 * or via normal navigation on web. Useful for OAuth flows
 * that don't work well inside a WebView.
 */
export const openExternalUrl = async (url: string) => {
  if (Capacitor.isNativePlatform()) {
    await Browser.open({ url });
  } else {
    window.location.assign(url);
  }
};
