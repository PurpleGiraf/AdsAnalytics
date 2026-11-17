# API access: what to apply for, and in what order

Last checked: 17 Nov 2026. Platforms change these rules often, so re-check each link before you start.

**Why this comes first:** none of the code works until each platform approves us. Reviews take days to weeks, and Google Business Profile can take months. Apply for everything this week, then build while we wait.

## Before you start (do once)

1. **Use a Purple Giraffe company account, not a personal one**, for every developer account below. If the person leaves, we must not lose access to every client's data.
2. **Have these ready**, because every form asks for them:
   - Company legal name and ABN
   - Website: purplegiraffe.com.au, with a **public privacy policy page** that says what data the reporting tool reads and how it is stored
   - A short description you can paste everywhere:
     > "PG Analytics is an internal reporting tool used by Purple Giraffe, a digital marketing agency, to produce performance reports for clients who have authorised us to manage their advertising accounts. It reads campaign performance data only (read-only), stores it in Australia, and does not create or change campaigns."
3. **Create one Google Cloud project** called `pg-analytics-prod`. Google Ads, GA4, Search Console and Business Profile all hang off this one project.

## Priority order (longest wait first)

| # | Platform | Why this position | Typical wait |
|---|---|---|---|
| 1 | Google Business Profile | Quota is 0 until Google manually approves. Reports of weeks to months | Weeks to months |
| 2 | Meta (Facebook / Instagram) | Business verification, then App Review | 1 to 4 weeks |
| 3 | Google Ads | Brand verification, then Basic access | Days to 2 weeks |
| 4 | LinkedIn Ads | Advertising API product review | Days to weeks |
| 5 | TikTok Ads | App review | About 2 to 7 business days |
| 6 | Google OAuth app verification (GA4, Search Console) | Needed before clients can connect without "unverified app" warnings | Up to about 10 business days |
| 7 | Microsoft Ads | Developer token. Agency use can take up to 5 business days | Up to 5 business days |

---

## 1. Google Business Profile (start today)

New projects get **0 requests per minute** until Google approves the project. Enabling the API is not enough, and every call fails with a 429 error until then.

1. In Google Cloud Console, open `pg-analytics-prod` and copy the **Project number** (not the Project ID).
2. Go to the Business Profile API prerequisites page: https://developers.google.com/my-business/content/prereqs
3. Open the **GBP API contact form**, choose **"Application for Basic API Access"**, and fill it in with the project number and our use case (reporting on profiles we manage for clients).
4. To check if you're approved, look at the quota in Cloud Console: **0 QPM = not approved, 300 QPM = approved**. Don't submit a "quota increase" request while it's 0, because that's the wrong form.
5. After approval, enable the Business Profile APIs (Business Profile Performance API, Account Management, Business Information).

Heads up: other developers report waiting weeks with no reply, and Google prioritises based on how many profiles you manage. Mention how many client profiles we manage.

## 2. Meta (Facebook and Instagram ads, Pages, Instagram organic)

1. **Business verification** in Meta Business Settings (Security Centre), with ABN and company documents. Needed before Advanced Access.
2. Create an app at https://developers.facebook.com with the **"Measure ad performance data with Marketing API"** use case, connected to our business portfolio.
3. Request these permissions only (read-only, keep the list short):
   - `ads_read` (ad performance)
   - `business_management` (to see client ad accounts shared with our business)
   - `pages_read_engagement`, `read_insights`, `pages_show_list` (Facebook Page insights)
   - `instagram_basic`, `instagram_manage_insights` (Instagram organic)
   - **Do not** request `ads_management`. We never change campaigns.
4. Submit **App Review** for Advanced Access. We need it because the ad accounts belong to *other businesses* (our clients).
5. For running the data pulls, create a **system user** in Business Settings with a token, and assign it each client ad account (view performance).
6. Watch for this: full Marketing API access needs at least 500 calls in 15 days with an error rate under 15%, and Meta can move the app back to limited access.

## 3. Google Ads

Developer tokens were sunset on 9 Sep 2026. Access now belongs to the **Google Cloud project**.

1. In `pg-analytics-prod`, enable the **Google Ads API** and open its overview page.
2. Complete **brand verification** for the project (OAuth consent screen with our logo, domain and privacy policy). It's a prerequisite for Basic.
3. Confirm the current level shows **Explorer** (usually automatic), then expand "Upgrade access level" and click **Apply for access** to Basic.
4. Limits: Explorer allows 2,880 operations a day on real accounts, Basic allows 15,000. Basic is plenty for us. Standard (unlimited) takes about 10 business days if we ever need it.
5. Make sure our **Google Ads manager account (MCC)** has every client account linked. The connector reads clients through it.

## 4. LinkedIn Ads

1. Create an app at https://developer.linkedin.com, linked to the **Purple Giraffe LinkedIn Company Page** (a page admin must approve the link).
2. In the app's **Products** tab, request the **Advertising API** and complete the access form.
3. You start on the **Development** tier, which is limited. Once the integration works, request **Standard** tier through the Developer Support Portal.
4. Scopes we need: `r_ads`, `r_ads_reporting`, and `r_organization_social` (for creatives and organic).
5. LinkedIn tokens expire: access tokens after 60 days, refresh tokens after 12 months. The app must warn us before they lapse.

## 5. TikTok Ads

1. Use the TikTok **API for Business** portal (business-api.tiktok.com), not "TikTok for Developers", which doesn't cover ads.
2. Create a developer app, request **Reporting** and **Ad Account Management (read)** scopes, and submit. Approval typically takes 2 to 7 business days. If rejected, make the description clearer and resubmit.
3. Each client's **Business Center** must grant our app access to their advertiser accounts.
4. Test with the sandbox account while waiting.

## 6. Google OAuth verification (GA4 and Search Console)

1. In `pg-analytics-prod`, enable the **Google Analytics Data API**, **Google Analytics Admin API** and **Search Console API**.
2. Set up the OAuth consent screen (same brand verification as Google Ads), with scopes `analytics.readonly` and `webmasters.readonly`.
3. Submit for verification and plan for about 10 business days.
4. **Simpler option for our own access:** create a **service account** and add its email as a Viewer on each client's GA4 property and as a user on each Search Console property. That avoids OAuth for clients we already manage.

## 7. Microsoft Advertising

1. Sign in at https://ads.microsoft.com as the **Super Admin** of our agency (manager) account.
2. Go to **Settings > Developer settings > Request Token**. If you're managing accounts for others, it can take up to 5 business days.
3. Register an app in **Microsoft Entra ID** for OAuth (scope `https://ads.microsoft.com/msads.manage offline_access`).
4. Refresh tokens expire after 90 days without use, so the app must sync at least weekly.

---

## Tracking sheet

| Platform | Applied (date) | Approved (date) | Owner | Notes |
|---|---|---|---|---|
| Google Business Profile | | | | |
| Meta business verification | | | | |
| Meta App Review | | | | |
| Google Ads Basic | | | | |
| LinkedIn Advertising API | | | | |
| TikTok | | | | |
| Google OAuth verification | | | | |
| Microsoft Ads dev token | | | | |

## Sources
- Google Ads access levels: https://developers.google.com/google-ads/api/docs/api-policy/access-levels
- Business Profile prerequisites: https://developers.google.com/my-business/content/prereqs
- LinkedIn Advertising API: https://developer.linkedin.com/product-catalog/marketing/advertising-api
- LinkedIn access tiers: https://learn.microsoft.com/en-us/linkedin/marketing/integrations/marketing-tiers
- Microsoft Ads getting started: https://learn.microsoft.com/advertising/guides/get-started
- Airbyte connector docs (permissions and limits per platform): https://docs.airbyte.com/integrations/sources/
