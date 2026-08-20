# Ad Mediation, GDPR & Privacy Architecture

Authoritative guide for Google Mobile Ads (GMA), multi-network mediation, Google UMP consent, and `:gdpr` module compliance in Rashaqa Android.

---

## 1. User Privacy & Google UMP Consent (`:gdpr`)
- **Google UMP SDK (`com.google.android.ump:user-messaging-platform:3.2.0`)**:
  - Centralized consent flow: `UserMessagingPlatform.getConsentInformation(context)`.
  - Must request consent update (`requestConsentInfoUpdate`) before initializing AdMob or loading personalized ads in EEA/UK regions.
  - Test Device IDs: Never hardcode production device IDs in test configurations.
- **`:gdpr` Module Isolation**:
  - Keep GDPR consent logic decoupled from feature UI.
  - Never bypass consent checks to force ad loads.

---

## 2. Ad Mediation Ecosystem & Adapters
Rashaqa integrates Google AdMob with an extensive mediation waterfall:
- **Networks**: Meta Audience Network, Unity Ads, Mintegral, Vungle, InMobi, Pangle, Criteo, Fyber.
- **Custom Local Library**: `ads-librarry-android-release_20.2.1.aar` / `madar_ads_library`.
- **Supported Formats**:
  - **Banner Ads**: Embedded in XML/Compose with adaptive sizing.
  - **Interstitial Ads**: Preloaded before transition points (e.g. after saving workout or completing a challenge).
  - **Rewarded Video Ads**: Triggered for user rewards (e.g. bonus points in `pointSystem` or unlocking features).
  - **App Open Ads**: Managed during splash/re-entry transitions.

---

## 3. Performance & Threading Rules
- **UI Thread Dispatch**:
  - Ad loading callbacks and `ad.show(activity)` MUST be invoked on the **Main Thread**.
- **Preload & Caching**:
  - Always preload interstitial and rewarded ads in advance; never block user navigation waiting for network ad responses.
- **Null & Dismiss Safety**:
  - Always check `isLoaded` and handle `onAdFailedToLoad` / `onAdFailedToShowFullScreenContent` gracefully so user flow is never blocked if ads fail.

---

## 4. ProGuard & Release Protection
- Mediation SDKs use reflection extensively.
- **ProGuard Rules**: Never remove `-keep` rules for AdMob adapters or mediation partner SDKs in `app/proguard-rules.pro`.

---

## 5. Review Guard Rules for Ads & Privacy
- ❌ **NEVER bypass GDPR/UMP consent verification**.
- ❌ **NEVER block user progression if an ad fails to load**.
- ❌ **NEVER display ads over sensitive checkout/payment screens**.
