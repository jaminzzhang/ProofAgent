# Answer-Ready Convergence Signal

Accepted.

The Controlled ReAct Loop will treat Accepted Evidence with no unresolved subgoals as an answer-ready convergence signal. After an Observation Action produces Accepted Evidence and its Observation Record summary declares no unresolved subgoals, the next Plan Round's Eligible Action Set is narrowed to `GENERATE_FINAL_ANSWER` and `REFUSE`; additional Observation Actions remain allowed only when a compound request leaves explicit unresolved subgoals.

We choose this over waiting for action repetition or evidence saturation because real runs can waste a full retrieval round after enough evidence already exists, while Action Constraint and Observation Records still preserve safe handling of incomplete compound tasks.
