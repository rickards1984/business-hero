import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  TextField,
  Typography,
} from '@mui/material';
import { Add as AddIcon, Delete as DeleteIcon } from '@mui/icons-material';
import { apiRequest } from '@/lib/queryClient';

/**
 * BH-010 — create an invoice without a quote.
 *
 * Deliberately shows no running total. The server works out every figure with
 * the same money engine quote conversion uses; a second calculation here would
 * be one more place for totals to disagree (RC1_SCOPE P2 counts seven already).
 * The created invoice's real number and total come back in `onCreated`.
 *
 * Errors render INSIDE the dialog: the panel's page-level alert sits behind
 * the modal, where nobody would see it (audits/TIER1-CORE-FIXES.md §3b).
 */

interface Line {
  description: string;
  quantity: string;
  unit_cost: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: (invoiceNumber: string, total: string) => void;
}

const emptyLine = (): Line => ({ description: '', quantity: '1', unit_cost: '' });

/** apiRequest throws "422: {\"detail\": ...}". Show the server's own words. */
function readableError(err: unknown): string {
  const raw = err instanceof Error ? err.message : '';
  const body = raw.replace(/^\d{3}:\s*/, '');
  try {
    const detail = JSON.parse(body).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return 'Check the dates and amounts: one of them is not in a form the server understands.';
  } catch {
    // not JSON: fall through
  }
  return 'The invoice could not be created. Please try again.';
}

function todayIso(): string {
  const d = new Date();
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

export default function NewInvoiceDialog({ open, onClose, onCreated }: Props) {
  const [customerName, setCustomerName] = useState('');
  const [customerEmail, setCustomerEmail] = useState('');
  const [customerAddress, setCustomerAddress] = useState('');
  const [invoiceDate, setInvoiceDate] = useState(todayIso());
  const [supplyDate, setSupplyDate] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [discount, setDiscount] = useState('');
  const [lines, setLines] = useState<Line[]>([emptyLine()]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const reset = () => {
    setCustomerName('');
    setCustomerEmail('');
    setCustomerAddress('');
    setInvoiceDate(todayIso());
    setSupplyDate('');
    setDueDate('');
    setDiscount('');
    setLines([emptyLine()]);
    setError('');
  };

  const close = () => {
    if (saving) return;
    reset();
    onClose();
  };

  const updateLine = (index: number, field: keyof Line, value: string) => {
    setLines(previous => previous.map((line, i) => (i === index ? { ...line, [field]: value } : line)));
  };

  const submit = async () => {
    setError('');
    if (!customerName.trim()) {
      setError('Add the customer’s name.');
      return;
    }
    const filled = lines.filter(l => l.description.trim() || l.unit_cost.trim());
    if (filled.length === 0) {
      setError('Add at least one line.');
      return;
    }
    setSaving(true);
    try {
      // Money goes as strings: the server converts it exactly, never via float.
      const body: Record<string, unknown> = {
        customer_name: customerName,
        customer_email: customerEmail || null,
        customer_address: customerAddress || null,
        invoice_date: invoiceDate || null,
        supply_date: supplyDate || null,
        due_date: dueDate || null,
        lines: filled.map(l => ({
          description: l.description,
          quantity: l.quantity,
          unit_cost: l.unit_cost,
        })),
      };
      if (discount.trim()) {
        body.discount_amount = discount;
        body.discount_type = 'fixed';
      }
      const response = await apiRequest('POST', '/v1/invoices', body);
      const created = await response.json();
      reset();
      onCreated(created.invoice_number, created.amount);
    } catch (err: unknown) {
      setError(readableError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={close} maxWidth="md" fullWidth>
      <DialogTitle>New invoice</DialogTitle>
      <DialogContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, gap: 2, mt: 1 }}>
          <TextField label="Customer name" required value={customerName}
            onChange={e => setCustomerName(e.target.value)} />
          <TextField label="Customer email" type="email" value={customerEmail}
            onChange={e => setCustomerEmail(e.target.value)} />
          <TextField label="Customer address" multiline minRows={2} value={customerAddress}
            onChange={e => setCustomerAddress(e.target.value)}
            helperText="Every invoice should show the customer’s address. You can save without it, but the PDF will flag it as missing."
            sx={{ gridColumn: { sm: '1 / -1' } }} />
          <TextField label="Invoice date" type="date" value={invoiceDate}
            onChange={e => setInvoiceDate(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField label="Due date" type="date" value={dueDate}
            onChange={e => setDueDate(e.target.value)} InputLabelProps={{ shrink: true }}
            helperText="Leave blank for 30 days" />
          <TextField label="Date of supply (if different)" type="date" value={supplyDate}
            onChange={e => setSupplyDate(e.target.value)} InputLabelProps={{ shrink: true }} />
          <TextField label="Discount (amount)" value={discount} inputMode="decimal"
            onChange={e => setDiscount(e.target.value)} />
        </Box>

        <Typography variant="subtitle2" sx={{ mt: 3, mb: 1 }}>Lines</Typography>
        {lines.map((line, index) => (
          <Box key={index} sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '3fr 1fr 1fr auto' }, gap: 1, mb: 1 }}>
            <TextField label="Description" size="small" value={line.description}
              onChange={e => updateLine(index, 'description', e.target.value)} />
            <TextField label="Qty" size="small" value={line.quantity} inputMode="decimal"
              onChange={e => updateLine(index, 'quantity', e.target.value)} />
            <TextField label="Unit price" size="small" value={line.unit_cost} inputMode="decimal"
              onChange={e => updateLine(index, 'unit_cost', e.target.value)}
              helperText={index === 0 ? 'Excluding VAT' : undefined} />
            <IconButton aria-label="Remove line" disabled={lines.length === 1}
              onClick={() => setLines(previous => previous.filter((_, i) => i !== index))}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Box>
        ))}
        <Button size="small" startIcon={<AddIcon />} onClick={() => setLines(previous => [...previous, emptyLine()])}>
          Add line
        </Button>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
          VAT and totals are worked out when you save, from your VAT settings. The invoice number is issued automatically.
        </Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={close} disabled={saving}>Cancel</Button>
        <Button variant="contained" onClick={submit} disabled={saving}
          startIcon={saving ? <CircularProgress size={18} /> : undefined}>
          {saving ? 'Creating…' : 'Create invoice'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
