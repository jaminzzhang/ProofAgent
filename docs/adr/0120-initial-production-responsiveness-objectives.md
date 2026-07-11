# Initial Production Responsiveness Objectives

Accepted.

[FRAME | HIGH] The initial production release acknowledges a governed run request within 500 milliseconds at P95, emits its first SSE status within one second at P95, and starts execution within one second at P95 when an execution slot is available. A standard supported first-release case produces its fully governed final answer within 60 seconds at P95, excluding separately displayed queue time, and every run has a 120-second hard deadline with an explicit terminal timeout state.

[FRAME | HIGH] These objectives are measured against the accepted production capacity envelope with production-equivalent dependencies. Queue time, execution time, provider time, and governance-validation time remain separate measurements so a fast acknowledgement cannot conceal a slow or stuck run.
