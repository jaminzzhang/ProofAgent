# Auto-Save with Manual Publish

Draft Agent configuration changes auto-save to the Agent Configuration Store, but promotion to a Published Agent Version requires an explicit publish action in the Versions Agent Lifecycle Tab. We chose this because auto-save reduces cognitive load and prevents data loss during editing, while explicit publish maintains the governed transition from draft to production that the Agent Publication workflow requires.

The alternative of save button per module was rejected because it creates confusion about which modules have been saved and adds friction to the editing workflow. The alternative of single draft-wide save button was rejected because it doesn't match the iterative nature of configuration editing where users may edit multiple modules before deciding to test or publish.
