# Privacy Policy

**Effective date:** 25 March 2026
**Last updated:** 25 March 2026

NeuroStack is an open-source (Apache-2.0) knowledge management tool created by Raphael Southall. This policy explains what data NeuroStack collects, how it is processed, and your rights regarding that data.

**Contact:** [hello@neurostack.sh](mailto:hello@neurostack.sh)
**Website:** [https://neurostack.sh](https://neurostack.sh)

---

## 1. Overview

NeuroStack operates in three modes, each with different data implications:

| Mode | Data leaves your machine? | Account required? |
|------|--------------------------|-------------------|
| **Local (Lite/Full/Community)** | No | No |
| **Cloud** | Yes, when you explicitly push | Yes |
| **Remote MCP** | Search queries only | Yes |

**The core principle:** in local mode, NeuroStack collects zero data. No telemetry, no analytics, no crash reporting, no phone-home behaviour of any kind.

---

## 2. Local Mode (Lite / Full / Community)

### What happens

- Your Markdown vault files are read and indexed into a local SQLite database.
- Vault files are **read-only** -- NeuroStack never modifies your source files.
- The database is stored at `~/.local/share/neurostack/`.
- In Full mode, vault text is sent to a **local** Ollama instance running on `localhost` for embeddings and summaries. This traffic never leaves your machine.

### What is collected

**Nothing.** There is:

- No telemetry
- No analytics
- No usage tracking
- No crash reports sent externally
- No network calls to any external service

### How to delete your data

Delete the database directory at `~/.local/share/neurostack/`. Uninstalling NeuroStack removes all traces.

---

## 3. Cloud Mode

Cloud mode is entirely opt-in. You must explicitly run `neurostack cloud push` to upload any data.

### 3.1 What data is uploaded

When you run `neurostack cloud push`, changed `.md` files from your vault are uploaded via HTTPS to a processing server.

### 3.2 How data is processed

- **Compute:** Google Cloud Run (us-central1) receives and processes your files.
- **AI processing:** Google Gemini API processes your vault text to generate embeddings (gemini-embedding-001) and summaries/triples (gemini-2.5-flash).
- **Storage:** The resulting indexed SQLite database is stored in Google Cloud Storage (gs://neurostack-prod, southamerica-east1), isolated under your user prefix (`vaults/{user_id}/`).

### 3.3 Data retention

- **Uploaded vault files are not retained after indexing completes.** Only the processed SQLite database is stored.
- Your indexed database remains in cloud storage until you delete your account.
- You can download your database at any time with `neurostack cloud pull`. After download, all searches run locally.

### 3.4 Server-side queries

When you use `neurostack cloud query`, your search query is sent to Cloud Run, which searches against your cached indexed database and returns results. No vault files are transmitted during queries.

---

## 4. Remote MCP Mode

When you connect an AI assistant (Claude, ChatGPT, etc.) to `https://mcp.neurostack.sh/mcp`:

- **Authentication** is handled via OAuth 2.1 wrapping Firebase Auth (Google sign-in).
- **Search queries** are sent to Cloud Run and executed against your indexed database.
- **No vault files are transmitted** during MCP queries -- only search queries and search results.

---

## 5. Authentication and Accounts

When you create a NeuroStack account (required for Cloud and Remote MCP modes only):

| Data collected | Purpose | Where stored |
|---------------|---------|-------------|
| Email address | Account identification, communication | Firebase Auth, Firestore |
| Display name | Account display | Firebase Auth, Firestore |
| User ID | Internal identifier | Firebase Auth, Firestore |
| Tier level | Billing and feature access | Firestore |
| Account creation date | Record keeping | Firestore |
| API key hashes (SHA-256) | API authentication | Firestore |
| Usage counts | Enforcing tier limits | Firestore |

**We never store plaintext API keys.** Only SHA-256 hashes are retained. Authentication uses the device code flow for CLI login.

---

## 6. Billing

Billing is handled entirely by **Stripe** (operating under SolidPlus LTD).

- NeuroStack **never sees, stores, or processes** your payment card numbers or bank details.
- Stripe processes payments in accordance with [Stripe's privacy policy](https://stripe.com/privacy).
- NeuroStack stores only your subscription tier level and usage counts.

---

## 7. Third-Party Sub-Processors

The following third parties process data only in Cloud and Remote MCP modes:

| Sub-processor | Purpose | Data processed | Location |
|--------------|---------|---------------|----------|
| Google Cloud Run | Compute / indexing / queries | Vault files (during indexing), search queries | us-central1 |
| Google Cloud Storage | Database storage | Indexed SQLite database | southamerica-east1 |
| Google Gemini API | Embedding and summary generation | Vault text (during indexing) | Google API infrastructure |
| Firebase Auth | Authentication | Email, display name, OAuth tokens | Google infrastructure |
| Cloud Firestore | User records | User profile, API key hashes, usage data | Google infrastructure |
| Stripe | Payment processing | Payment information (handled by Stripe directly) | Stripe infrastructure |

Google's data processing terms apply to all Google Cloud services listed above. See [Google Cloud Data Processing Terms](https://cloud.google.com/terms/data-processing-addendum).

---

## 8. Data Security

- All data in transit is encrypted via **HTTPS/TLS**.
- Cloud-stored databases are **tenant-isolated** by user ID prefix.
- Database downloads use **signed URLs** with limited validity.
- API key authentication uses **constant-time comparison** to prevent timing attacks.
- Vault files are **not retained** after indexing -- only the derived database is stored.

---

## 9. Your Rights

You have the right to:

- **Access** your data -- download your indexed database with `neurostack cloud pull`.
- **Delete** your data -- run `neurostack cloud delete-account` to permanently delete your account, all stored databases, and all associated records.
- **Export** your data -- your vault files remain on your local machine at all times. The indexed database can be downloaded at any time.
- **Withdraw consent** -- stop using cloud features at any time. Your local installation continues to work independently.

For users in the EU/EEA, you additionally have the right to:

- **Rectification** -- request correction of inaccurate personal data.
- **Restriction** -- request restricted processing of your data.
- **Portability** -- receive your personal data in a structured, machine-readable format.
- **Object** -- object to processing of your personal data.
- **Lodge a complaint** with your local data protection authority.

To exercise any of these rights, contact [hello@neurostack.sh](mailto:hello@neurostack.sh).

---

## 10. International Data Transfers

Cloud mode processes data on Google Cloud infrastructure in the United States (us-central1) and stores indexed databases in South America (southamerica-east1). For users in the EU/EEA, transfers to the US are covered by Google's Data Processing Addendum, which includes EU Standard Contractual Clauses. See [Google's compliance documentation](https://cloud.google.com/privacy/gdpr).

---

## 11. Cookies

The NeuroStack dashboard at `app.neurostack.sh` uses **only essential cookies** for Firebase Auth session management. There are:

- No tracking cookies
- No third-party advertising cookies
- No analytics cookies

---

## 12. Children's Privacy

NeuroStack is not intended for use by anyone under the age of 13. We do not knowingly collect personal information from children under 13. If you believe a child under 13 has provided personal information, contact [hello@neurostack.sh](mailto:hello@neurostack.sh) and we will delete it.

---

## 13. Changes to This Policy

We will update this policy as NeuroStack evolves. Material changes will be announced via the project's GitHub repository and changelog. Continued use of cloud features after changes constitutes acceptance of the updated policy.

---

## 14. Contact

For privacy questions, data requests, or concerns:

- **Email:** [hello@neurostack.sh](mailto:hello@neurostack.sh)
- **GitHub:** [https://github.com/neurostackai/neurostack](https://github.com/neurostackai/neurostack)
