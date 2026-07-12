# Knowledge Models Use A Separate Private Serving Plane

Accepted.

[FRAME | HIGH] Heavyweight OCR, layout analysis, embedding, reranking, and Knowledge-bearing language-model inference run as versioned services on a company-controlled Private Knowledge Model Serving Plane. Proof Agent calls them through governed internal adapters and retains authority over policy gates, secret handles, model-version references, Knowledge artifact fingerprints, evidence admission, and audit; API, Knowledge Worker, and retrieval process roles do not host those models in-process. We accept an additional internal serving boundary because coupling model memory, GPU scheduling, upgrades, and failures to Knowledge Worker lifecycle would prevent independent scaling and make the selected private-processing, corpus-capacity, and activation objectives difficult to enforce.
