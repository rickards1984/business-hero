/**
 * Phone number input with country code selector.
 * Defaults to +44 (UK).
 */

import { useEffect, useState } from 'react';
import { Box, MenuItem, Select, TextField } from '@mui/material';

const COUNTRY_OPTIONS = [
  { value: '+44', label: '🇬🇧 +44' },
  { value: '+1', label: '🇺🇸 +1' },
  { value: '+353', label: '🇮🇪 +353' },
  { value: '+61', label: '🇦🇺 +61' },
  { value: '+64', label: '🇳🇿 +64' },
  { value: '+49', label: '🇩🇪 +49' },
  { value: '+33', label: '🇫🇷 +33' },
  { value: '+39', label: '🇮🇹 +39' },
  { value: '+34', label: '🇪🇸 +34' },
];

interface PhoneInputProps {
  value: string;
  onChange: (fullNumber: string) => void;
  placeholder?: string;
  disabled?: boolean;
  fullWidth?: boolean;
  size?: 'small' | 'medium';
}

export default function PhoneInput({
  value,
  onChange,
  placeholder = '7885 249 222',
  disabled = false,
  fullWidth = false,
  size = 'medium',
}: PhoneInputProps) {
  const [countryCode, setCountryCode] = useState('+44');
  const [number, setNumber] = useState('');

  useEffect(() => {
    if (value) {
      if (value.startsWith('+44')) {
        setCountryCode('+44');
        setNumber(value.slice(3).replace(/\s/g, ''));
      } else if (value.startsWith('+')) {
        const match = value.match(/^\+\d{1,3}/);
        const code = match?.[0] || '+44';
        setCountryCode(code);
        setNumber(value.slice(code.length).replace(/\s/g, ''));
      } else {
        setNumber(value.replace(/\s/g, ''));
      }
    } else {
      setCountryCode('+44');
      setNumber('');
    }
  }, [value]);

  const handleNumberChange = (newNumber: string) => {
    const cleaned = newNumber.replace(/[^\d]/g, '');
    setNumber(cleaned);
    onChange(`${countryCode}${cleaned}`);
  };

  const handleCountryChange = (code: string) => {
    setCountryCode(code);
    onChange(`${code}${number}`);
  };

  return (
    <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center', flex: fullWidth ? 1 : undefined }}>
      <Select
        value={countryCode}
        onChange={(e) => handleCountryChange(e.target.value)}
        disabled={disabled}
        size={size}
        sx={{
          minWidth: 100,
          '& .MuiSelect-select': { py: size === 'small' ? 1 : 1.5 },
        }}
      >
        {COUNTRY_OPTIONS.map((opt) => (
          <MenuItem key={opt.value} value={opt.value}>
            {opt.label}
          </MenuItem>
        ))}
      </Select>
      <TextField
        type="tel"
        value={number}
        onChange={(e) => handleNumberChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        size={size}
        fullWidth={fullWidth}
        sx={{ flex: fullWidth ? 1 : undefined }}
        inputProps={{
          inputMode: 'numeric',
          pattern: '[0-9]*',
          maxLength: 15,
        }}
      />
    </Box>
  );
}
