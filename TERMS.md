# NeuroStack Terms of Service

**Effective date:** 27 March 2026
**Last updated:** 27 March 2026

---

## 1. Acceptance of Terms

By creating a NeuroStack account, accessing the NeuroStack Cloud service, or using any cloud-hosted features (including Remote MCP), you agree to be bound by these Terms of Service ("Terms"). If you do not agree to these Terms, do not use the NeuroStack Cloud service.

These Terms apply to the **NeuroStack Cloud service** operated by SolidPlus LTD. The open-source NeuroStack software, licensed under Apache-2.0, may be used independently without accepting these Terms. However, any use of cloud-hosted features — including indexing, search, Remote MCP, and account management — is governed by these Terms.

---

## 2. Service Description

### 2.1 Open-source software (not covered by these Terms)

NeuroStack's core software is open-source under the Apache-2.0 licence. You may install it locally, run it against your own infrastructure, and modify it freely under that licence. Local usage does not involve any data processing by SolidPlus LTD and is outside the scope of these Terms.

### 2.2 Cloud service (covered by these Terms)

NeuroStack Cloud is a managed service that provides:

- **Cloud indexing** — upload vault files for server-side embedding, summarisation, and knowledge graph extraction.
- **Cloud search** — query your indexed database via `neurostack cloud query` or the Remote MCP endpoint at `mcp.neurostack.sh`.
- **Account management** — authentication via Firebase Auth (Google OAuth), API key management, and usage tracking.
- **Billing** — subscription management and payment processing via Stripe.

The Cloud service runs on Google Cloud Platform (Cloud Run, Cloud Storage, Firestore) and uses the Gemini API for AI processing.

---

## 3. Account Registration and Security

### 3.1 Account creation

To use NeuroStack Cloud, you must create an account by authenticating via Google OAuth through Firebase Auth. You must provide accurate information and keep your account details up to date.

### 3.2 Account security

You are responsible for:

- Maintaining the confidentiality of your API keys and authentication credentials.
- All activity that occurs under your account.
- Notifying us promptly at [hello@neurostack.sh](mailto:hello@neurostack.sh) if you become aware of any unauthorised access to your account.

We store API keys as SHA-256 hashes and never retain plaintext keys. However, you are solely responsible for safeguarding your keys after generation.

### 3.3 One account per person

Each account is for a single individual. You may not share account credentials or API keys with others. Organisation and team features, if offered in the future, will have separate terms.

---

## 4. Acceptable Use Policy

You agree to use NeuroStack Cloud in a manner that is lawful, respectful, and consistent with the intended purpose of the service. You may use the service to:

- Index and search your personal or professional knowledge base.
- Connect AI assistants via Remote MCP for knowledge retrieval.
- Manage and organise your notes, documents, and research.

You must not use the service in any way that violates applicable law or regulation, infringes the rights of others, or compromises the integrity and availability of the service for other users.

---

## 5. Prohibited Content and Abuse

### 5.1 Prohibited content

You must not upload, index, or process through NeuroStack Cloud any content that:

- Violates any applicable law or regulation.
- Infringes the intellectual property rights of any third party.
- Contains malware, viruses, or any code designed to disrupt, damage, or gain unauthorised access to systems.
- Is designed to exploit or harm minors in any way.
- Constitutes illegal pornography, incitement to violence, or terrorism-related material.

### 5.2 Abuse of the service

You must not:

- Attempt to access another user's data or account.
- Reverse-engineer, decompile, or attempt to extract the source code of proprietary cloud components (the open-source components are freely available under Apache-2.0).
- Use the service to build a competing product by systematically extracting proprietary features or methodologies.
- Circumvent usage limits, rate limits, or other technical restrictions.
- Use automated means to create accounts or generate excessive load on the service.
- Resell or redistribute access to the Cloud service without prior written consent.

### 5.3 Enforcement

We reserve the right to suspend or terminate accounts that violate this section, with or without notice, depending on the severity of the violation. Where practicable, we will provide notice and an opportunity to remedy the violation before taking action.

---

## 6. Service Availability

### 6.1 No uptime guarantee for free tier

NeuroStack Cloud runs on Google Cloud Run, which scales to zero when not in use. The free tier is provided **as-is** with **no uptime guarantee, no SLA, and no guarantee of availability**. The service may be unavailable due to maintenance, scaling delays, infrastructure issues, or capacity constraints.

### 6.2 Paid tier availability

Paid tiers may include availability commitments as specified in the applicable plan description. Any such commitments will be documented separately and form part of these Terms by reference.

### 6.3 Maintenance and changes

We may modify, suspend, or discontinue any part of the Cloud service at any time. We will make reasonable efforts to provide advance notice of material changes. We are not liable for any modification, suspension, or discontinuation of the service.

### 6.4 Data durability

While we use industry-standard infrastructure (Google Cloud Storage) to store your indexed data, we do not guarantee against data loss. You are responsible for maintaining local copies of your vault files. NeuroStack is designed so that your original vault files always remain on your local machine — the cloud stores only derived indexed data that can be regenerated.

---

## 7. Free Tier and Paid Tiers

### 7.1 Free tier

The free tier provides access to NeuroStack Cloud with usage limits as described on [neurostack.sh](https://neurostack.sh). The free tier:

- Has no uptime or availability guarantee.
- May be subject to rate limiting and capacity constraints.
- May be modified or discontinued at any time.

### 7.2 Paid tiers

Paid subscriptions are available with increased limits, priority processing, and additional features as described on [neurostack.sh](https://neurostack.sh). Paid tiers:

- Are billed via Stripe on a recurring basis (monthly or annual, depending on the plan selected).
- Renew automatically unless cancelled before the end of the billing period.
- May be cancelled at any time. Cancellation takes effect at the end of the current billing period; no partial refunds are issued for the remaining period.

### 7.3 Payment terms

- All payments are processed by Stripe. SolidPlus LTD does not store payment card details.
- Prices are listed on [neurostack.sh](https://neurostack.sh) and may be changed with 30 days' notice.
- If payment fails, we may suspend access to paid features until payment is resolved. Your data will be retained for a reasonable period to allow you to resolve payment issues or downgrade to the free tier.

### 7.4 Refunds

Refunds are handled on a case-by-case basis. Contact [hello@neurostack.sh](mailto:hello@neurostack.sh) for refund requests.

---

## 8. Intellectual Property

### 8.1 Your content

You retain all rights, title, and interest in your vault data, including any files you upload, the content of your notes, and any intellectual property contained within them. Uploading content to NeuroStack Cloud does not transfer ownership of that content to us.

We claim no intellectual property rights over your vault data. The indexed representations (embeddings, summaries, knowledge graph triples) derived from your content are considered your data and are subject to the same ownership.

### 8.2 Licence to operate

By uploading content to NeuroStack Cloud, you grant us a limited, non-exclusive, non-transferable licence to process your content solely for the purpose of providing the service (indexing, search, and retrieval). This licence terminates when you delete your account or remove your data.

### 8.3 NeuroStack software and branding

The NeuroStack name, logo, and branding are the property of SolidPlus LTD. The open-source NeuroStack software is licensed under Apache-2.0. Proprietary cloud components, infrastructure, and service-specific features remain the intellectual property of SolidPlus LTD.

### 8.4 Feedback

If you provide feedback, suggestions, or feature requests, you grant us a non-exclusive, royalty-free, perpetual licence to use that feedback to improve the service without obligation to you.

---

## 9. Account Termination and Data Deletion

### 9.1 Termination by you

You may delete your account at any time by running `neurostack cloud delete-account`. Upon deletion:

- Your indexed database is permanently deleted from Google Cloud Storage.
- Your user record is deleted from Firestore.
- Your authentication record is deleted from Firebase Auth.
- All API key hashes associated with your account are deleted.
- Usage records are deleted.

### 9.2 Termination by us

We may suspend or terminate your account if:

- You breach these Terms, including the Acceptable Use Policy or Prohibited Content provisions.
- Your account has been inactive for an extended period (we will provide at least 90 days' notice before deletion due to inactivity).
- We are required to do so by law.
- The service is discontinued.

Where practicable, we will provide notice and an opportunity to export your data before termination.

### 9.3 Effect of termination

Upon termination, your right to access the Cloud service ceases immediately. Data deletion follows the process described in the [Data Processing Agreement](DPA.md), Section 8.

### 9.4 Survival

Sections that by their nature should survive termination — including Intellectual Property, Liability Limitations, Indemnification, and Governing Law — will survive.

---

## 10. Liability Limitations

### 10.1 Disclaimer of warranties

To the maximum extent permitted by applicable law, NeuroStack Cloud is provided **"as is"** and **"as available"**, without warranties of any kind, whether express, implied, or statutory, including but not limited to implied warranties of merchantability, fitness for a particular purpose, and non-infringement.

We do not warrant that the service will be uninterrupted, error-free, or secure, or that any defects will be corrected.

### 10.2 Limitation of liability

To the maximum extent permitted by applicable law, SolidPlus LTD shall not be liable for any indirect, incidental, special, consequential, or punitive damages, including but not limited to loss of profits, data, or goodwill, arising out of or in connection with your use of the service.

Our total aggregate liability for any claims arising out of or relating to these Terms or the service shall not exceed the greater of: (a) the total amount you paid to us in the 12 months preceding the claim, or (b) GBP 100.

### 10.3 Exceptions

Nothing in these Terms excludes or limits liability for:

- Death or personal injury caused by negligence.
- Fraud or fraudulent misrepresentation.
- Any other liability that cannot be excluded or limited under applicable law.

---

## 11. Indemnification

You agree to indemnify, defend, and hold harmless SolidPlus LTD and its directors, officers, and employees from and against any claims, damages, losses, liabilities, and expenses (including reasonable legal fees) arising out of or in connection with:

- Your use of the Cloud service.
- Your violation of these Terms.
- Your violation of any applicable law or regulation.
- Any content you upload or process through the service that infringes the rights of a third party.

---

## 12. Modification of Terms

We may update these Terms from time to time to reflect changes in the service, legal requirements, or business practices.

### 12.1 Notice of changes

We will notify you of material changes to these Terms by:

- Sending a notification to the email address associated with your account, and/or
- Displaying a prominent notice within the service or on [neurostack.sh](https://neurostack.sh).

We will provide at least 30 days' notice before material changes take effect.

### 12.2 Explicit consent required

Material changes to these Terms require your **explicit consent**. Continued use of the service after notification does **not** constitute acceptance. If you do not affirmatively accept updated Terms within 60 days of notification, your access to the Cloud service may be suspended until you accept the updated Terms or delete your account.

### 12.3 Non-material changes

Minor corrections, clarifications, or formatting changes that do not alter the substance of these Terms may be made without prior notice.

---

## 13. Governing Law and Dispute Resolution

### 13.1 Governing law

These Terms shall be governed by and construed in accordance with the laws of **England and Wales**, without regard to conflict of law principles.

### 13.2 Jurisdiction

Any disputes arising out of or in connection with these Terms shall be subject to the exclusive jurisdiction of the courts of **England and Wales**.

### 13.3 Informal resolution

Before initiating formal proceedings, both parties agree to attempt to resolve disputes informally by contacting [hello@neurostack.sh](mailto:hello@neurostack.sh). We will make reasonable efforts to resolve complaints within 30 days.

---

## 14. Age Restriction

You must be at least **16 years of age** to create a NeuroStack account or use the Cloud service. This requirement is set in accordance with GDPR Article 8 and the UK Age Appropriate Design Code. If we become aware that a user is under 16, we will terminate their account and delete their data.

If you are between 16 and 18 years of age, you confirm that you have obtained consent from a parent or guardian to use the service.

---

## 15. General Provisions

### 15.1 Entire agreement

These Terms, together with the [Data Processing Agreement](DPA.md) and any applicable plan terms, constitute the entire agreement between you and SolidPlus LTD regarding the NeuroStack Cloud service.

### 15.2 Severability

If any provision of these Terms is found to be unenforceable, the remaining provisions shall remain in full force and effect.

### 15.3 Waiver

Failure to enforce any provision of these Terms does not constitute a waiver of that provision or any other provision.

### 15.4 Assignment

You may not assign your rights or obligations under these Terms without our prior written consent. We may assign our rights and obligations without restriction.

---

## 16. Contact Information

For questions about these Terms, the NeuroStack Cloud service, or to report abuse:

- **Email:** [hello@neurostack.sh](mailto:hello@neurostack.sh)
- **Website:** [https://neurostack.sh](https://neurostack.sh)
- **GitHub:** [https://github.com/neurostackai/neurostack](https://github.com/neurostackai/neurostack)

**SolidPlus LTD**
A company registered in England and Wales.
