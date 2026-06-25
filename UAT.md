# UAT Checklist (M9)

## WhatsApp ordering

- [ ] Send message to WhatsApp business number → receive AI greeting
- [ ] Choose restaurant (Kababjees or KFC) → menu shown with prices
- [ ] Place order with name + address → confirm YES → receive confirmation
- [ ] Order appears on tenant dashboard within 2 seconds

## Tenant dashboard

- [ ] Login as `owner@kababjees.local` / `owner123`
- [ ] Live Orders kanban shows new order in **placed** column
- [ ] Click Advance → status moves through pipeline
- [ ] Customer receives WhatsApp status update

## Menu management

- [ ] Add menu item with new price
- [ ] Agent quotes updated price on next WhatsApp conversation

## Analytics

- [ ] Overview shows revenue, orders, AOV after placing test orders
- [ ] Charts render without errors

## Admin

- [ ] Login as `admin@platform.local` / `admin123`
- [ ] Platform overview shows tenant count
- [ ] Provision new tenant → status becomes active after worker runs

## Security

- [ ] Invalid webhook signature returns 403
- [ ] Tenant A token cannot access tenant B data
- [ ] `GET /health` reports database + redis status
