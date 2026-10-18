import { useMediaQuery } from '@mui/material';
import { Capacitor } from '@capacitor/core';

/** The ONE "is this the phone layout?" decision, shared by the shell and the
 *  pages inside it (Codex NS-B7 review 1, finding 7): ≤768px, or any native
 *  (Capacitor) app whatever its width. */
export function useShellMobile(): boolean {
  const narrow = useMediaQuery('(max-width: 768px)');
  return narrow || Capacitor.isNativePlatform();
}
