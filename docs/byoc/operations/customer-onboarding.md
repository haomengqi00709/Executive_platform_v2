# Customer onboarding — BYOC tier

**Audience:** Jason (engineer) + partner. Used for every new BYOC
deployment. Track customer-specific details (env values, contacts) in
a separate per-customer notes file.

This runbook reflects the IPS Consultancy onboarding as the reference
case. Other customers may have small variations.

## 1. Prerequisites (customer side)

Before vendor can begin:

- [ ] Signed MSA + NDA + IP Assignment + DPA (vendor's legal package).
- [ ] Customer has an Azure subscription with billing set up.
- [ ] Customer designates an Azure admin who can run the steps in
      Section 2.
- [ ] Customer designates a primary user (typically the CEO).
- [ ] Customer agrees on data region (e.g., Canada Central for
      Canadian customers).

## 2. Customer Azure setup

The customer's Azure admin performs these steps. Vendor provides a
checklist; customer executes.

### 2.1 Register Entra ID application

- Entra ID portal → App registrations → New registration.
- Name: `CEO Platform - <Customer>`.
- Supported account types: **Single tenant**.
- Redirect URI: `https://ceo-platform-<customer>.azurewebsites.net/auth/callback`
  (placeholder until App Service is provisioned; update after).
- After creation:
  - Note the **Application (client) ID** → `PROD_CLIENT_ID`.
  - Note the **Directory (tenant) ID** → `TENANT_ID`.
  - Certificates & secrets → New client secret → 24-month expiry →
    note value → `PROD_CLIENT_SECRET`.

### 2.2 Grant Microsoft Graph permissions

In the same Entra ID app:

- API permissions → Microsoft Graph → Delegated permissions:
  - `Mail.Read`
  - `Mail.ReadWrite`
  - `Mail.Send`
  - `Calendars.Read`
  - `Files.Read.All`
  - `Chat.Read.All`
  - `User.Read`
- Admin consent → click Grant.

### 2.3 Issue vendor a service principal

- Azure portal → Subscriptions → Access control (IAM) → Add → New
  role assignment.
- Role: **Contributor** scoped to the resource group
  `ceo-platform-<customer>` (which doesn't exist yet — Azure allows
  pre-assigning; the role becomes effective once the RG is created).
- Stronger: define a custom role allowing only App Service operations
  (no Storage read).
- Principal: vendor's service principal (provided by Jason).
- Vendor SP details to share with customer:
  - **Vendor SP Application (client) ID**: provided in onboarding
    email.
  - **Vendor SP Object ID**: provided.

### 2.4 Provide Gemini API access (option A or B)

- **Option A** (recommended): customer creates their own Google AI
  Studio account, generates an API key, provides to vendor →
  `GEMINI_API_KEY`. Customer pays the Gemini bill directly.
- **Option B**: vendor uses their own Gemini key, includes cost in
  subscription fee.

## 3. Vendor Azure setup

Jason runs these once the customer-side steps are complete.

### 3.1 Resource group

```bash
az group create -n ceo-platform-<customer> -l <customer-region>
```

### 3.2 Storage account

```bash
az storage account create \
  --name ceoplatform<customer>data \
  --resource-group ceo-platform-<customer> \
  --kind StorageV2 \
  --sku Standard_LRS \
  --location <customer-region>

az storage share create \
  --name data \
  --account-name ceoplatform<customer>data
```

### 3.3 Container Registry

```bash
az acr create \
  --name ceoplatform<customer>acr \
  --resource-group ceo-platform-<customer> \
  --sku Basic \
  --admin-enabled true \
  --location <customer-region>
```

### 3.4 Build the container image

```bash
az acr build \
  --registry ceoplatform<customer>acr \
  --image ceo-platform:v1 \
  --image ceo-platform:latest \
  --platform linux/amd64 \
  .
```

### 3.5 App Service plan + App Service

```bash
az appservice plan create \
  --name ceo-platform-<customer>-plan \
  --resource-group ceo-platform-<customer> \
  --is-linux \
  --sku B1 \
  --location <customer-region>

az webapp create \
  --name ceo-platform-<customer> \
  --plan ceo-platform-<customer>-plan \
  --resource-group ceo-platform-<customer> \
  --deployment-container-image-name \
    ceoplatform<customer>acr.azurecr.io/ceo-platform:v1
```

### 3.6 Mount Azure Files

```bash
STORAGE_KEY=$(az storage account keys list \
  --account-name ceoplatform<customer>data \
  --resource-group ceo-platform-<customer> \
  --query "[0].value" -o tsv)

az webapp config storage-account add \
  --name ceo-platform-<customer> \
  --resource-group ceo-platform-<customer> \
  --custom-id ceodata \
  --storage-type AzureFiles \
  --share-name data \
  --account-name ceoplatform<customer>data \
  --access-key "$STORAGE_KEY" \
  --mount-path /mnt/data
```

### 3.7 Configure env vars

```bash
SESSION_SECRET=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')

az webapp config appsettings set \
  --name ceo-platform-<customer> \
  --resource-group ceo-platform-<customer> \
  --settings \
    PROD_CLIENT_ID=<from customer> \
    PROD_CLIENT_SECRET=<from customer> \
    TENANT_ID=<from customer> \
    SESSION_SECRET="$SESSION_SECRET" \
    GEMINI_API_KEY=<vendor-or-customer> \
    DATA_DIR=/mnt/data \
    REDIRECT_URI=https://ceo-platform-<customer>.azurewebsites.net/auth/callback \
    FRONTEND_URL=https://ceo-platform-<customer>.azurewebsites.net \
    APP_URL=https://ceo-platform-<customer>.azurewebsites.net \
    WEBSITES_PORT=8080
```

### 3.8 Update the OAuth redirect URI

Go back to the customer's Entra ID app and verify the redirect URI
matches the actual App Service URL.

### 3.9 Apply hardening defaults

- App Service: enforce HTTPS-only.
- App Service: minimum TLS 1.2.
- Storage account: deny public network access (allow App Service via
  service endpoint if customer wants — optional advanced step).
- Resource group: `CanNotDelete` lock to prevent accidental deletion
  (customer can override).

## 4. Verification

After deployment:

- [ ] `curl https://ceo-platform-<customer>.azurewebsites.net/api/auth/status`
      returns 200.
- [ ] Customer's primary user signs in successfully.
- [ ] Onboarding flow runs (reads inbox, calendar, OneDrive).
- [ ] Audrey Teams bot registers via device flow (separate step;
      customer admin should designate Audrey as a service account in
      their Conditional Access policy if applicable).
- [ ] Each of the 5 modules produces output for the primary user.
- [ ] CRM page populates from the inbox scan.
- [ ] Settings page is reachable and shows correct user info.

## 5. Handover documentation

Provide to customer:

- This onboarding doc (so they understand what was deployed).
- `customer-facing/privacy-policy.md`.
- `customer-facing/subprocessor-list.md`.
- `customer-facing/data-handling-summary.md`.
- A short customer-specific summary listing:
  - Resource group name + region.
  - App URL.
  - How to revoke vendor RBAC access.
  - Where to check Azure Activity Log for vendor activity.
  - Vendor contact info for support.

## 6. Ongoing operations

After onboarding:

- Per-customer GitHub Actions workflow (or shared parameterized
  workflow with per-customer secrets).
- Per-customer monitoring (Azure Monitor availability test).
- Per-customer per-month cost report from Azure to customer.

## 7. Estimated timeline

- Customer Azure setup (Section 2): 1-2 hours of customer admin time.
- Vendor Azure setup (Section 3): 1-2 hours of Jason's time.
- Verification (Section 4): 30 minutes with customer.
- Total: 1 working day from contract signature to live deployment,
  assuming both sides are responsive.

Legal package (MSA + NDA + IP + DPA): 2-3 weeks, $3-5k one-time before
first customer; reused thereafter.
