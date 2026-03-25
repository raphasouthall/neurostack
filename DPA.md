# Data Processing Agreement

**Effective date:** 25 March 2026
**Last updated:** 25 March 2026

This Data Processing Agreement ("DPA") forms part of the NeuroStack Terms of Service between Raphael Southall, operating NeuroStack ("Processor", "we", "us"), and the individual or entity using NeuroStack Cloud or Remote MCP features ("Controller", "you").

This DPA applies **only** to Cloud Mode and Remote MCP Mode. Local mode involves no data processing by NeuroStack and is outside the scope of this agreement.

**Contact:** [hello@neurostack.sh](mailto:hello@neurostack.sh)

---

## 1. Definitions

| Term | Meaning |
|------|---------|
| **Personal Data** | Any information relating to an identified or identifiable natural person, as defined in GDPR Article 4(1). In the context of NeuroStack, this includes account information and any personal data contained within vault files you upload. |
| **Controller** | You, the NeuroStack user. You determine the purposes and means of processing your vault data. |
| **Processor** | NeuroStack (Raphael Southall). We process your data on your behalf to provide indexing, search, and related services. |
| **Sub-processor** | A third party engaged by the Processor to process Personal Data on behalf of the Controller. |
| **Processing** | Any operation performed on Personal Data, including collection, storage, indexing, retrieval, and deletion. |
| **Data Subject** | An identifiable natural person whose Personal Data is processed. |
| **Supervisory Authority** | An independent public authority responsible for monitoring GDPR compliance. |

---

## 2. Scope and Purpose

### 2.1 Scope

This DPA covers the processing of Personal Data that occurs when you:

- Upload vault files via `neurostack cloud push`
- Use server-side search via `neurostack cloud query`
- Connect AI assistants via Remote MCP at `mcp.neurostack.sh`
- Create and maintain a NeuroStack account

### 2.2 Processing purposes

We process your data solely for the following purposes:

- **Indexing:** Generating embeddings, summaries, and knowledge graph triples from your uploaded vault files.
- **Search:** Executing queries against your indexed database and returning results.
- **Authentication:** Verifying your identity and managing your account.
- **Billing:** Tracking usage against tier limits and processing subscription payments via Stripe.

### 2.3 Categories of data

| Category | Examples | Retention |
|----------|---------|-----------|
| Account data | Email, display name, user ID | Until account deletion |
| Vault content | Markdown files uploaded via cloud push | Deleted after indexing completes |
| Indexed data | SQLite database (embeddings, summaries, triples) | Until account deletion |
| Usage data | Query counts, note counts | Until account deletion |
| Authentication data | API key hashes (SHA-256), OAuth tokens | Until account deletion or key revocation |
| Payment data | Handled entirely by Stripe -- NeuroStack stores tier level only | Per Stripe's retention policy |

---

## 3. Controller Obligations

As Controller, you are responsible for:

- Ensuring you have a lawful basis to process any Personal Data contained in your vault files.
- Not uploading vault content that you do not have the right to process.
- Informing any Data Subjects whose Personal Data may be included in your vault files.

---

## 4. Processor Obligations

We will:

- Process Personal Data **only** on your documented instructions (i.e., the operations you initiate via NeuroStack commands and the MCP interface).
- Not process your data for any purpose other than providing the NeuroStack service.
- Not sell, share, or use your data for advertising, profiling, or training AI models.
- Ensure that persons authorised to process Personal Data are bound by confidentiality obligations.
- Implement appropriate technical and organisational security measures (see Section 6).
- Assist you in fulfilling Data Subject rights requests.
- Delete or return all Personal Data upon termination of the service (see Section 8).
- Make available information necessary to demonstrate compliance with this DPA.

---

## 5. Sub-Processors

### 5.1 Authorised sub-processors

You authorise the use of the following sub-processors:

| Sub-processor | Processing activity | Location | Their DPA |
|--------------|---------------------|----------|-----------|
| **Google Cloud Run** | Compute: receives vault files for indexing, executes search queries | us-central1 (Iowa, US) | [Google Cloud DPA](https://cloud.google.com/terms/data-processing-addendum) |
| **Google Cloud Storage** | Stores indexed SQLite databases | southamerica-east1 (Sao Paulo, BR) | [Google Cloud DPA](https://cloud.google.com/terms/data-processing-addendum) |
| **Google Gemini API** | Generates embeddings and summaries from vault text during indexing | Google API infrastructure | [Google API Terms](https://ai.google.dev/gemini-api/terms) |
| **Firebase Auth** | Authentication and session management | Google infrastructure | [Firebase DPA](https://firebase.google.com/terms/data-processing-terms) |
| **Cloud Firestore** | Stores user records, API key hashes, usage data | Google infrastructure | [Firebase DPA](https://firebase.google.com/terms/data-processing-terms) |
| **Stripe** | Payment processing (under SolidPlus LTD) | Stripe infrastructure | [Stripe DPA](https://stripe.com/legal/dpa) |

### 5.2 Changes to sub-processors

We will notify you of any new sub-processors by updating this DPA and announcing the change via the project's GitHub repository. You may object to a new sub-processor by contacting [hello@neurostack.sh](mailto:hello@neurostack.sh) within 30 days of notification.

### 5.3 Sub-processor liability

We remain fully liable for the acts and omissions of our sub-processors with respect to the processing of your Personal Data.

---

## 6. Security Measures

We implement the following technical and organisational measures:

### 6.1 Data in transit

- All data transmitted between your device and NeuroStack servers is encrypted via **HTTPS/TLS**.
- All communication with sub-processors uses encrypted channels.

### 6.2 Data at rest

- Indexed databases in Google Cloud Storage are encrypted at rest using Google-managed encryption keys.
- Database downloads use **signed URLs** with time-limited validity.

### 6.3 Access control

- **Tenant isolation:** Each user's data is stored under a unique prefix (`vaults/{user_id}/`), preventing cross-user access.
- API key authentication uses **constant-time comparison** to prevent timing attacks.
- API keys are stored as **SHA-256 hashes** -- plaintext keys are never retained.
- OAuth 2.1 with Firebase Auth for account access.

### 6.4 Data minimisation

- Uploaded vault files are **not retained** after indexing completes.
- Only the derived indexed database is stored.
- NeuroStack never stores payment card details -- Stripe handles all payment data.

### 6.5 Operational security

- Infrastructure runs on Google Cloud Platform with its [security practices](https://cloud.google.com/security).
- No persistent servers -- Cloud Run scales to zero, reducing attack surface.
- No shared databases between users.

---

## 7. Data Breach Notification

In the event of a Personal Data breach:

- We will notify you **without undue delay** and in any event within **72 hours** of becoming aware of the breach.
- Notification will include: the nature of the breach, categories and approximate number of Data Subjects affected, likely consequences, and measures taken or proposed to mitigate the breach.
- Notification will be sent to the email address associated with your NeuroStack account.
- We will cooperate with you and any supervisory authority in investigating and resolving the breach.

---

## 8. Data Deletion and Return

### 8.1 During the service

- You can download your indexed database at any time using `neurostack cloud pull`.
- Your vault files remain on your local machine -- they are never the sole copy held by NeuroStack.

### 8.2 Account deletion

When you run `neurostack cloud delete-account`:

- Your indexed database is permanently deleted from Google Cloud Storage.
- Your user record is deleted from Firestore.
- Your authentication record is deleted from Firebase Auth.
- All API key hashes associated with your account are deleted.
- Usage records are deleted.

### 8.3 Post-termination

After account deletion, we will have no copies of your Personal Data, with the exception of:

- Data retained in sub-processor backups that are automatically purged according to their retention schedules.
- Data we are required to retain by applicable law.

---

## 9. Data Subject Rights

We will assist you in responding to Data Subject requests, including:

- **Access** -- providing copies of Personal Data we hold.
- **Rectification** -- correcting inaccurate data.
- **Erasure** -- deleting Personal Data (achievable via `neurostack cloud delete-account`).
- **Portability** -- providing data in a structured, machine-readable format (SQLite database via `neurostack cloud pull`).
- **Restriction and objection** -- restricting or ceasing processing upon request.

If we receive a Data Subject request directly, we will redirect the Data Subject to you unless legally required to respond directly.

---

## 10. Audit Rights

You may request reasonable information about our data processing practices to verify compliance with this DPA. Requests should be directed to [hello@neurostack.sh](mailto:hello@neurostack.sh).

We will provide:

- Written responses to audit questionnaires.
- Summaries of relevant third-party audit reports or certifications held by our sub-processors (e.g., Google Cloud SOC 2 reports).

On-site audits are not available given the serverless nature of the infrastructure. All compute runs on Google Cloud Platform, which maintains [comprehensive compliance certifications](https://cloud.google.com/security/compliance).

---

## 11. International Data Transfers

### 11.1 Transfer locations

| Data | Location | Transfer mechanism |
|------|----------|-------------------|
| Vault files (during indexing) | us-central1 (US) | Google Cloud DPA with EU SCCs |
| Indexed database | southamerica-east1 (Brazil) | Google Cloud DPA with EU SCCs |
| Account data | Google infrastructure | Firebase DPA with EU SCCs |
| Payment data | Stripe infrastructure | Stripe DPA with EU SCCs |

### 11.2 Safeguards for EU/EEA transfers

For transfers of Personal Data from the EU/EEA to countries without an adequacy decision, we rely on:

- **EU Standard Contractual Clauses (SCCs)** incorporated into our sub-processors' data processing agreements (Google Cloud DPA, Firebase DPA, Stripe DPA).
- Google's commitment to challenge disproportionate government access requests, as documented in their [transparency reports](https://transparencyreport.google.com/).

### 11.3 UK transfers

For transfers from the UK, we rely on the UK International Data Transfer Addendum to the EU SCCs, as incorporated by our sub-processors.

---

## 12. GDPR Compliance

### 12.1 Legal basis for processing

As Processor, we process Personal Data on the basis of your instructions (GDPR Article 28). As Controller, you are responsible for establishing a lawful basis (e.g., legitimate interest, consent) for any Personal Data in your vault files.

For account data, we process on the basis of **contract performance** (providing the NeuroStack service) and **legitimate interest** (preventing abuse, maintaining security).

### 12.2 Data Protection Impact Assessment

Given that NeuroStack processes vault content that may contain sensitive personal data, you may need to conduct a Data Protection Impact Assessment (DPIA) under GDPR Article 35. We will provide reasonable assistance if requested.

### 12.3 Records of processing

We maintain records of processing activities as required by GDPR Article 30(2).

---

## 13. Term and Termination

- This DPA is effective for as long as you maintain a NeuroStack account with cloud features.
- Upon account deletion, the data deletion provisions in Section 8 apply.
- Sections that by their nature should survive termination (data deletion obligations, liability, audit rights) will survive.

---

## 14. Liability

Our liability under this DPA is subject to the limitations set out in the NeuroStack Terms of Service. Nothing in this DPA limits liability for breaches of data protection law that cannot be limited under applicable law.

---

## 15. Amendments

We may update this DPA to reflect changes in our processing activities, sub-processors, or applicable law. Material changes will be announced via the project's GitHub repository. Continued use of cloud features after notification constitutes acceptance.

---

## 16. Contact

For questions about this DPA, data processing practices, or to exercise your rights:

- **Email:** [hello@neurostack.sh](mailto:hello@neurostack.sh)
- **GitHub:** [https://github.com/neurostackai/neurostack](https://github.com/neurostackai/neurostack)
