---
status: accepted
---

# Import only server-generated metadata workbooks

[FRAME | HIGH] Proof Agent accepts metadata workbook imports only as returns of an Insurance Rule Metadata Workbook Export generated from server authority and bound to an exact Source, document revision, canonical anchor set, and metadata-review generation. Operators and external automation may edit governed cells after requesting the export, but cannot originate a blank import workbook or supply internal anchor identities as authority. This extra export step prevents wrong-revision, stale-anchor, cross-environment, and guessed-identity imports while retaining offline bulk editing; workbook protection remains a usability aid and every field is revalidated server-side.
