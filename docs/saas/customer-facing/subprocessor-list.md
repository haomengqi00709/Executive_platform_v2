# Sub-processor List

**Effective date:** _TBD — set on launch_
**Last updated:** _TBD_

To deliver the service, we share the minimum necessary customer data with
the following third-party sub-processors. Each is bound by its own
contractual terms with us.

## Current sub-processors

| Sub-processor | Purpose | Data accessed | Location | Provider terms |
|---|---|---|---|---|
| **Microsoft Graph API** | OAuth authentication and read access to your M365 data | Mail, calendar, OneDrive metadata and content you authorize, Teams chats with the Audrey bot | Customer's M365 tenant region (set by Microsoft when the tenant was provisioned) | [Microsoft Online Services DPA](https://www.microsoft.com/licensing/docs/view/Microsoft-Products-and-Services-Data-Protection-Addendum-DPA) |
| **Google Gemini API** | AI processing — text generation, audio transcription, video transcription | Email bodies, meeting recording audio and video, document text (in-transit only; per Gemini's paid API terms, not retained for model training) | United States | [Google Cloud DPA](https://cloud.google.com/terms/data-processing-addendum) |
| **Railway** | Application hosting and persistent data storage | All user data at rest, all application logs | US-east region | [Railway DPA](https://railway.com/legal/dpa) |

## What "in-transit only" means for Gemini

When we send your email content or a meeting recording to Gemini for AI
processing, the data travels over TLS to Google's servers, is processed,
and the response is returned. Per Google's paid Gemini API terms, your
content is not retained for model training. The output of the processing
(e.g., a summary) is then stored in Railway as part of your normal
account data.

## How we update this list

We will notify you by email at least 30 days before adding a new
sub-processor or materially changing how an existing one is used. You may
object to a new sub-processor; if we cannot accommodate, you may delete
your account before the change takes effect.

## Contact

To object to a sub-processor change or to ask about our diligence on any
sub-processor, email **_TBD — partner or Jason contact email_**.
