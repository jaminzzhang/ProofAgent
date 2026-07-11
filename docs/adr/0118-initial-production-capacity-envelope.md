# Initial Production Capacity Envelope

Accepted.

[FRAME | HIGH] The initial production release must support 20 simultaneously online authenticated operators, admit no more than five governed run executions at once, and hold no more than 50 additional run requests in a bounded queue. Requests beyond that envelope fail explicitly with an overload response and retry guidance rather than creating unbounded work or timing out invisibly.

[FRAME | HIGH] A production-equivalent load and soak test must prove this envelope together with queue ordering, cancellation, restart recovery, per-operator fairness, and the accepted availability and latency objectives. Raising these limits later requires a new capacity result, not only a configuration change.
