# Payment Gateways & In-App Purchase Architecture

Authoritative guide for handling multiple billing providers safely in Rashaqa Android.

---

## 1. Multi-Gateway Landscape
Rashaqa supports multiple payment solutions depending on user country, platform, and subscription tier:
- **Google Play Billing 8.3**: Standard in-app subscriptions and consumables via `BillingClient`.
- **RevenueCat 10.16 (`com.revenuecat.purchases`)**: Cross-platform subscription management under `domain/data.payment.newPayment`.
- **Fawry Pay**: Local cash/wallet payment in Egypt.
- **Credit Card / Visa / Web Gateways**: Direct gateway checkout.

---

## 2. Google Play Billing Rules
1. **Purchase Acknowledgment (CRITICAL)**:
   - Every non-consumable purchase and subscription MUST be acknowledged via `billingClient.acknowledgePurchase()` within 3 days, otherwise Google Play will automatically refund and revoke the purchase.
2. **Pending Transactions**:
   - Always handle `PurchaseState.PENDING` (e.g. cash payments or parental approval). Never grant entitlement until `PurchaseState.PURCHASED`.
3. **Double-Purchase Prevention**:
   - Never auto-trigger purchase flows on screen re-entry. UI effects for checkout dialogs MUST be one-shot (`Channel` / `sendEvent()` / `consume-to-null`).

---

## 3. RevenueCat Integration Rules
- Initialize once in `MyApplication.kt` with `Purchases.configure(...)`.
- Identify user with `Purchases.sharedInstance.logIn(userId)`.
- Check entitlements via `Purchases.sharedInstance.getCustomerInfoWith(...)`.
- Use `PurchasesUI` paywalls where applicable.

---

## 4. Safety & Security Guardrails
- ❌ **NEVER complete a real charge or purchase during testing**.
- ❌ **NEVER log full credit card numbers, CVVs, or unmasked auth payloads**.
- ❌ **Always verify server-side receipts** via backend API before granting permanent VIP status.
