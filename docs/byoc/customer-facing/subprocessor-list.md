# Sub-processor List — BYOC tier

**Effective date:** _TBD_
**Last updated:** _TBD_

To deliver the service, we share the minimum necessary customer data
with the following third-party sub-processors. Each is bound by its
own contractual terms with us.

## Current sub-processors

| Sub-processor | Purpose | Data accessed | Location | Provider terms |
|---|---|---|---|---|
| **Microsoft Graph API** | OAuth authentication and read access to your M365 data | Mail, calendar, OneDrive metadata and content you authorize, Teams chats with the Audrey bot | Customer's M365 tenant region | [Microsoft Online Services DPA](https://www.microsoft.com/licensing/docs/view/Microsoft-Products-and-Services-Data-Protection-Addendum-DPA) |
| **Google Gemini API** | AI processing — text generation, audio transcription, video transcription | Email bodies, meeting recording audio and video, document text (in-transit only; per Gemini's paid API terms, not retained for model training) | United States | [Google Cloud DPA](https://cloud.google.com/terms/data-processing-addendum) |

## Why Railway is not listed

Unlike the SaaS tier, Railway is not used in BYOC deployments. The
application runs in your own Azure App Service; the data lives in your
own Azure Storage account.

## Why your own Azure is not listed

The Azure subscription hosting the service is yours. We are not a
processor for your Azure environment — you control it directly. The
Microsoft Online Services Agreement that you signed with Microsoft for
your Azure subscription governs how Microsoft handles your data at the
infrastructure level.

## Vendor-side artifacts

To deploy and operate the service, we use:

- **GitHub** — private repository hosting our source code.
- **Azure Container Registry** in your subscription — stores the
  application image we built for you.

GitHub holds only our source code, not your data. The image in your
ACR also holds only our code — your data does not appear in any image
we publish.

## How we update this list

We will notify you by email at least 30 days before adding a new
sub-processor or materially changing how an existing one is used. You
may object to a new sub-processor; if we cannot accommodate, you may
terminate the service before the change takes effect.

## Contact

To object to a sub-processor change: **_TBD — partner or Jason email_**.
