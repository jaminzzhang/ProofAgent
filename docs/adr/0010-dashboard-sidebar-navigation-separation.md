# Dashboard Sidebar Navigation Separation

The Dashboard Shell sidebar separates navigation into two sections: MONITORING (Overview, Runs, Handoffs, Approvals) and CONFIGURATION (Agents, Policies, Knowledge Sources, Tools). We chose this because users switch between two distinct mental modes—observing what's happening versus changing how things work—and mixing them creates cognitive overhead.

The alternative of a flat navigation list was rejected because it doesn't signal whether an item is for observation or design-time work. The alternative of role-based sections (Operate, Build) was rejected because it assumes users have fixed roles rather than switching contexts throughout the day.
