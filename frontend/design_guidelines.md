# Design Guidelines: Business Hero Frontend

## Design Approach

**Selected System:** Material UI (MUI) - As requested for clean, modern dashboard aesthetic
**Rationale:** Utility-focused SaaS application requiring professional, efficient UX with established patterns for data-dense interfaces

## Core Design Principles

1. **Clarity over decoration** - Information hierarchy drives every layout decision
2. **Consistent spacing** - Predictable patterns for cognitive ease
3. **Purposeful components** - Every element serves the user's workflow

---

## Layout System

**Spacing Scale:** Use MUI's default spacing system (8px base)
- Common values: `spacing(1, 2, 3, 4, 6, 8)` → 8px, 16px, 24px, 32px, 48px, 64px
- Container padding: `p={3}` for cards, `p={4}` for page containers
- Section margins: `mb={4}` between major sections

**Responsive Breakpoints:**
- Mobile: `xs` (0-600px) - Stack all content
- Tablet: `sm/md` (600-960px) - 1-2 column layouts
- Desktop: `lg+` (960px+) - Full multi-column layouts

---

## Typography Hierarchy

**Font Family:** System default (Roboto via MUI)

**Heading Scale:**
- Page titles: `variant="h4"` (34px, semibold)
- Section headers: `variant="h5"` (24px, medium)
- Card titles: `variant="h6"` (20px, medium)
- Subsections: `variant="subtitle1"` (16px, medium)

**Body Text:**
- Primary: `variant="body1"` (16px, regular)
- Secondary/meta: `variant="body2"` (14px, regular)
- Labels: `variant="caption"` (12px, regular, uppercase)

---

## Component Library

### Authentication
**Login Page:**
- Centered card layout (max-width: 400px)
- Paper component with elevation={3}
- TextField components with outlined variant
- Full-width primary Button (contained variant)
- Minimal branding - logo + title in header

### Admin Dashboard
**Layout Structure:**
- AppBar with title "Platform Admin" + user menu
- Drawer navigation (persistent on desktop, temporary on mobile)
- Main content area with Container maxWidth="xl"

**Key Components:**
- **Business Creation:** Dialog with form (TextField for name, Select for timezone)
- **Member Creation:** Multi-step form or single Dialog with Autocomplete for business selection
- **Data Tables:** Use DataGrid or Table with TablePagination
  - Columns: Business name, created date, member count, actions
  - Row actions: IconButton menu (edit, view members, delete)
- **Action Bar:** Buttons in top-right (+ Create Business, + Add Member)

### Business Dashboard
**Layout Structure:**
- AppBar with business name + user menu
- No drawer needed - simpler single-view layout
- TabPanel if multiple sections needed (Profile, Tasks, Calls)

**Profile Section:**
- Paper component with business details in Grid layout
- Read-only TextFields or Typography for clean data display

**Task/Call Lists:**
- Card components for each item
- CardHeader with title + timestamp
- CardActions with completion buttons
- Chip components for status indicators
- Empty state: Box with centered Typography + illustration icon

**Action Buttons:**
- Floating Action Button (FAB) for primary actions (+ Create Task)
- Or contained Buttons in header for multiple actions

---

## Forms & Inputs

**Text Inputs:**
- variant="outlined" (consistent across app)
- fullWidth on mobile, fixed widths on desktop
- Required fields marked with asterisk
- Helper text for validation errors

**Selects/Autocompletes:**
- Use Autocomplete for searchable lists (businesses, users)
- Select for short option lists (roles, timezones)

**Buttons:**
- Primary actions: `variant="contained"` `color="primary"`
- Secondary: `variant="outlined"`
- Destructive: `color="error"`
- Loading states: CircularProgress inside disabled button

---

## Data Display

**Tables:**
- Alternate row colors (striped) for readability
- Sticky header on scroll
- Responsive: Convert to stacked cards on mobile

**Cards:**
- elevation={1} for subtle depth
- elevation={3} for important/interactive cards
- Consistent padding: `p={2}` or `p={3}`

**Status Indicators:**
- Chip components with appropriate colors
- Success: green, Warning: orange, Error: red, Info: blue

---

## Navigation

**Top AppBar:**
- Fixed position
- Title on left, user menu on right
- IconButton for mobile drawer toggle

**Admin Drawer:**
- Width: 240px on desktop
- Navigation items: Dashboard, Businesses, Members, Settings
- Icons from @mui/icons-material (Dashboard, Business, People, Settings)

---

## Responsive Behavior

**Mobile (xs/sm):**
- Single column layouts
- Full-width buttons and cards
- Bottom sheet modals instead of dialogs
- Temporary drawer navigation

**Desktop (md+):**
- Multi-column grids (2-3 columns for cards)
- Fixed drawer navigation
- Wider form layouts with horizontal label alignment

---

## Accessibility

- Use semantic HTML elements
- TextField labels for all inputs
- IconButton aria-label attributes
- Keyboard navigation for all interactive elements
- ARIA roles on custom components

---

## Animation

**Keep Minimal:**
- Drawer slide transitions (built-in)
- Dialog fade-in (built-in)
- Button ripple effects (built-in)
- NO custom scroll animations
- NO page transitions

---

This design leverages MUI's robust component library to deliver a professional, efficient dashboard experience that prioritizes usability and rapid development.